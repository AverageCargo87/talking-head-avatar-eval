#!/usr/bin/env python3
"""Run Wan2.1 InfiniteTalk in ComfyUI headlessly, through its HTTP API, on a 12 GB GPU.

No ComfyUI window: the graph is built here as an API-format prompt, queued with POST
/prompt and polled through /history. Frames are written to disk window by window by the
sampler (``output_path``), then ffmpeg stitches them with the audio, shifted by
``--av-shift`` seconds.

    # one host, 640x640
    python local/comfy_infinitetalk.py --img lena-640.png --audio lena-10s.wav \
        --w 640 --h 640 --name lena-10s --out-dir out --comfy-input /path/to/ComfyUI/input \
        --prompt "A young woman ... talks to the camera in a calm, friendly and warm manner ..."

    # two hosts in one shot: each voice track has silence where the other one speaks
    python local/comfy_infinitetalk.py --img two-hosts-832x480.png \
        --audio lena-track.wav --audio2 artem-track.wav --mix dialogue.wav \
        --masks mask-lena.png,mask-artem.png,mask-background.png \
        --w 832 --h 480 --name two-hosts --out-dir out --comfy-input /path/to/ComfyUI/input

    # only build the graph (no ComfyUI needed), e.g. to inspect or import it
    python local/comfy_infinitetalk.py --img a.png --audio a.wav --name x --dump-graph graph.json

Image, audio and mask names are file names inside ComfyUI's input folder (that is how its
LoadImage/LoadAudio nodes address files). Model names must match your ComfyUI models
folders; see local/WEIGHTS.md.
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

SINGLE = "Wan2_1-InfiniteTalk_Single_Q8.gguf"
MULTI = "Wan2_1-InfiniteTalk_Multi_Q8.gguf"
BASE = "wan2.1-i2v-14b-480p-Q4_K_M.gguf"
LORA = "lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors"
VAE = "Wan2_1_VAE_bf16.safetensors"
CLIP_VISION = "open-clip-xlm-roberta-large-vit-huge-14_visual_fp16.safetensors"
TEXT_ENCODER = "umt5-xxl-enc-fp8_e4m3fn.safetensors"
WAV2VEC = "wav2vec2-chinese-base_fp16.safetensors"

DEFAULT_PROMPT = ("A person sits in a cozy podcast studio and talks to the camera in a calm, friendly and warm "
                  "manner, like an experienced TV presenter, with small, precise lip movements and natural blinking.")
# At cfg = 1 (the lightx2v distillation LoRA) the negative prompt has NO effect; only the
# positive prompt steers. It is kept because the sampler node requires the input.
NEGATIVE = ("bright tones, overexposed, static, blurred details, subtitles, style, works, paintings, images, static, "
            "overall gray, worst quality, low quality, JPEG compression residue, ugly, incomplete, extra fingers, "
            "poorly drawn hands, poorly drawn faces, deformed, disfigured, misshapen limbs, fused fingers, still picture, "
            "messy background, three legs, many people in the background, walking backwards")


def build_graph(a, out_dir: str) -> dict:
    """The InfiniteTalk graph in ComfyUI API format (node id -> {class_type, inputs})."""
    multi = a.audio2 is not None
    g = {
        "1": {"class_type": "MultiTalkModelLoader", "inputs": {"model": a.multitalk_model or (MULTI if multi else SINGLE)}},
        "2": {"class_type": "WanVideoBlockSwap", "inputs": {
            "blocks_to_swap": a.swap, "offload_img_emb": False, "offload_txt_emb": False, "use_non_blocking": False,
            "vace_blocks_to_swap": 0, "prefetch_blocks": 0, "block_swap_debug": False}},
        "3": {"class_type": "WanVideoLoraSelect", "inputs": {"lora": a.lora, "strength": 1.0, "low_mem_load": False,
                                                              "merge_loras": False}},
        "4": {"class_type": "WanVideoModelLoader", "inputs": {
            "model": a.model, "base_precision": "fp16_fast", "quantization": "disabled", "load_device": "offload_device",
            "attention_mode": a.attn, "block_swap_args": ["2", 0], "lora": ["3", 0], "multitalk_model": ["1", 0]}},
        "5": {"class_type": "WanVideoVAELoader", "inputs": {"model_name": VAE, "precision": "bf16"}},
        "6": {"class_type": "LoadWanVideoClipTextEncoder", "inputs": {"model_name": CLIP_VISION, "precision": "fp16",
                                                                       "load_device": "offload_device"}},
        "7": {"class_type": "LoadImage", "inputs": {"image": a.img}},
        "8": {"class_type": "WanVideoClipVisionEncode", "inputs": {
            "clip_vision": ["6", 0], "image_1": ["7", 0], "strength_1": 1.0, "strength_2": 1.0, "crop": "center",
            "combine_embeds": "average", "force_offload": True, "tiles": 0, "ratio": 0.5}},
        "9": {"class_type": "LoadAudio", "inputs": {"audio": a.audio}},
        "10": {"class_type": "Wav2VecModelLoader", "inputs": {"model": WAV2VEC, "base_precision": "fp16",
                                                              "load_device": "main_device"}},
        "11": {"class_type": "MultiTalkWav2VecEmbeds", "inputs": {
            "wav2vec_model": ["10", 0], "audio_1": ["9", 0], "normalize_loudness": True, "num_frames": a.frames,
            "fps": 25.0, "audio_scale": a.audio_scale, "audio_cfg_scale": 1.0, "multi_audio_type": "para"}},
        "12": {"class_type": "WanVideoImageToVideoMultiTalk", "inputs": {
            "vae": ["5", 0], "width": a.w, "height": a.h, "frame_window_size": 81, "motion_frame": 9,
            "force_offload": False, "colormatch": "disabled", "start_image": ["7", 0], "tiled_vae": False,
            "clip_embeds": ["8", 0], "mode": "infinitetalk", "output_path": out_dir.replace(os.sep, "/")}},
        "13": {"class_type": "WanVideoTextEncodeCached", "inputs": {
            "model_name": TEXT_ENCODER, "precision": "bf16", "positive_prompt": a.prompt, "negative_prompt": NEGATIVE,
            "quantization": "fp8_e4m3fn", "use_disk_cache": True, "device": "gpu"}},
        "14": {"class_type": "WanVideoSampler", "inputs": {
            "model": ["4", 0], "image_embeds": ["12", 0], "text_embeds": ["13", 0], "multitalk_embeds": ["11", 0],
            "steps": a.steps, "cfg": 1.0, "shift": a.shift, "seed": a.seed, "force_offload": True,
            "scheduler": "dpm++_sde", "riflex_freq_index": 0, "denoise_strength": 1.0, "batched_cfg": False,
            "rope_function": "comfy", "start_step": 0, "end_step": -1, "add_noise_to_samples": True}},
        "15": {"class_type": "WanVideoPassImagesFromSamples", "inputs": {"samples": ["14", 0]}},
        "16": {"class_type": "PreviewAny", "inputs": {"source": ["15", 1]}},
    }
    if multi:
        g["17"] = {"class_type": "LoadAudio", "inputs": {"audio": a.audio2}}
        g["11"]["inputs"]["audio_2"] = ["17", 0]
    if a.masks:
        # Explicit masks [speaker 1, speaker 2, background], white = object, red channel.
        # The wrapper's own "split the frame in half" masks were created AFTER the sampler
        # had read ref_target_masks and crashed it, so we always pass our own. A multi-page
        # TIFF does not work either: LoadImage reads only its first page.
        batch = {}
        for i, f in enumerate(a.masks.split(",")):
            g[str(18 + i)] = {"class_type": "LoadImageMask", "inputs": {"image": f, "channel": "red"}}
            batch[f"masks.mask{i}"] = [str(18 + i), 0]
        g["30"] = {"class_type": "BatchMasksNode", "inputs": batch}
        g["11"]["inputs"]["ref_target_masks"] = ["30", 0]
    return g


# urllib with NO proxy: a system-wide proxy (VPN clients set one) would otherwise swallow
# requests to the local ComfyUI server.
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def api(base: str, path: str, data=None, timeout=60):
    req = urllib.request.Request(base.rstrip("/") + path, data=json.dumps(data).encode() if data is not None else None,
                                 headers={"Content-Type": "application/json"})
    return json.load(OPENER.open(req, timeout=timeout))


def stitch(frames_dir: str, audio: str, out_mp4: str, av_shift: float) -> None:
    """Frames + audio -> mp4. The audio starts ``av_shift`` seconds early; its tail is padded.

    SyncNet put InfiniteTalk output at -2 frames consistently (audio 80 ms behind the lips);
    with the audio 0.08 s earlier it reads 0 (confidence 7.68 -> 7.78 on one host).
    """
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-framerate", "25", "-i", os.path.join(frames_dir, "frame_%05d.png"),
                    "-ss", str(av_shift), "-i", audio, "-af", "apad", "-c:v", "libx264", "-crf", "17",
                    "-preset", "slow", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest", out_mp4],
                   check=True)


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--img", required=True, help="start image (file name in ComfyUI's input folder)")
    ap.add_argument("--audio", required=True, help="voice of speaker 1 (file name in ComfyUI's input folder)")
    ap.add_argument("--audio2", help="voice of speaker 2: switches to the multi-speaker model")
    ap.add_argument("--mix", help="audio for the final clip (default: --audio)")
    ap.add_argument("--masks", help="speaker1,speaker2,background mask files (input folder)")
    ap.add_argument("--name", required=True, help="output name")
    ap.add_argument("--w", type=int, default=640)
    ap.add_argument("--h", type=int, default=640)
    ap.add_argument("--frames", type=int, default=2000, help="maximum frames at 25 fps")
    ap.add_argument("--steps", type=int, default=6, help="6 with the lightx2v distillation LoRA")
    ap.add_argument("--shift", type=float, default=11.0)
    ap.add_argument("--seed", type=int, default=2)
    ap.add_argument("--swap", type=int, default=30, help="transformer blocks swapped to RAM (12 GB VRAM)")
    ap.add_argument("--model", default=BASE)
    ap.add_argument("--multitalk-model", help=f"override {SINGLE} / {MULTI}")
    ap.add_argument("--lora", default=LORA)
    ap.add_argument("--attn", default="sageattn", help="sageattn (57 s/step on an RTX 3060) or sdpa (90 s/step)")
    ap.add_argument("--audio-scale", type=float, default=1.0, help="how strongly the voice drives the face")
    ap.add_argument("--prompt", default=DEFAULT_PROMPT)
    ap.add_argument("--av-shift", type=float, default=0.08, help="seconds the audio starts earlier than the video")
    ap.add_argument("--comfy-url", default=os.environ.get("COMFY_URL", "http://localhost:8188"))
    ap.add_argument("--comfy-input", default=os.environ.get("COMFY_INPUT"),
                    help="ComfyUI input folder, to find the audio for the final mux")
    ap.add_argument("--out-dir", default="out", help="frames go to <out-dir>/<name>/, the clip to <out-dir>/<name>.mp4")
    ap.add_argument("--check", action="store_true", help="queue the graph and remove it at once (validation only)")
    ap.add_argument("--dump-graph", help="write the API graph to this JSON file and exit")
    ap.add_argument("--poll", type=float, default=20.0)
    return ap.parse_args(argv)


def main(argv=None):
    a = parse_args(argv)
    if a.dump_graph:
        # keep the output path exactly as given, so a dumped graph carries no local paths
        graph = build_graph(a, os.path.join(a.out_dir, a.name))
        with open(a.dump_graph, "w", encoding="utf-8", newline="\n") as f:
            json.dump(graph, f, indent=1)
            f.write("\n")
        print("graph written to", a.dump_graph)
        return 0
    # ComfyUI runs in its own working directory: hand it an absolute output path
    out_root = os.path.abspath(a.out_dir)
    frames_dir = os.path.join(out_root, a.name)
    graph = build_graph(a, frames_dir)
    os.makedirs(frames_dir, exist_ok=True)
    body = {"client_id": str(uuid.uuid4()), "prompt": graph}
    if a.check:
        try:
            r = api(a.comfy_url, "/prompt", body)
            print("graph accepted", r)
            api(a.comfy_url, "/queue", {"delete": [r["prompt_id"]]})
            print("removed from the queue")
        except urllib.error.HTTPError as e:
            print("ERROR", e.read().decode()[:2000])
            return 1
        return 0
    t0 = time.time()
    pid = api(a.comfy_url, "/prompt", body)["prompt_id"]
    print("prompt", pid, flush=True)
    while True:
        time.sleep(a.poll)
        h = api(a.comfy_url, "/history/" + pid)
        if pid in h:
            st = h[pid].get("status", {})
            print("status", st.get("status_str"), flush=True)
            if st.get("status_str") != "success":
                for m in st.get("messages", []):
                    if m[0] == "execution_error":
                        print(json.dumps(m[1], ensure_ascii=False)[:3000])
                return 1
            break
        n = len(glob.glob(os.path.join(frames_dir, "*", "frame_*.png")))
        print(f"{(time.time() - t0) / 60:.1f} min, frames {n}", flush=True)
    sub = sorted(glob.glob(os.path.join(frames_dir, "*_output")), key=os.path.getmtime)[-1]
    mix = a.mix or a.audio
    audio = mix if os.path.isabs(mix) or not a.comfy_input else os.path.join(a.comfy_input, mix)
    mp4 = os.path.join(out_root, a.name + ".mp4")
    stitch(sub, audio, mp4, a.av_shift)
    print("DONE", mp4, f"{(time.time() - t0) / 60:.1f} min", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
