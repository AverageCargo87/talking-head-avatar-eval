#!/usr/bin/env python3
"""BATCH LIP-SYNC: every line of a lesson with ONE model load.

Why: prerender/lipsync_run.py starts a process per line, and loading the weights alone
costs about 37 s (measured 2026-08-04 at three points: time = 37 s + 1.9 s per diffusion
step). Over the 70 lines of one textbook section that is 43 minutes of pure idling. Here
the pipeline is built once and the lines go through it in a loop.

Input is a JSON job list:
  [{"audio": "path/to/line.mp3", "out": "path/to/clip.mp4"}, ...]

Run with the interpreter of the LatentSync environment (CUDA torch):
  python prerender/lipsync_batch.py --jobs jobs.json --face face.png [--idle idle.mp4]

Finished clips are skipped, so a run can be interrupted and resumed. Plugs into
prerender/make-teacher-clips.mjs as
  LIPSYNC_BATCH_CMD="python prerender/lipsync_batch.py --jobs {jobs} --face {face}"
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

# The Windows console lives in cp1251 and ANY character outside it crashes print() with
# UnicodeEncodeError. Caught twice: the script finished all the work, died on the last line
# of its report, and the caller reported "batch failed" with every clip on disk.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# "version -> (weights, config)" pairs. Never mix them: a foreign config loads without an
# error and silently ruins the picture. Details in prerender/lipsync_run.py.
VERSIONS = {
    "1.5": ("latentsync_unet_15.pt", "stage2.yaml"),
    "1.6": ("latentsync_unet.pt", "stage2_512.yaml"),
}


def sh(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        sys.stderr.write((p.stderr or p.stdout or "")[-1500:] + "\n")
        raise SystemExit(f"failed: {' '.join(str(c) for c in cmd[:3])}...")
    return p


def audio_seconds(path):
    p = sh(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", path])
    return float(json.loads(p.stdout)["format"]["duration"])


def build_source(face, idle, seconds, width, dest):
    """Idle clip of the right length: a looped live clip or a still frame."""
    w = width - (width % 2)
    vf = f"scale={w}:-2,pad=ceil(iw/2)*2:ceil(ih/2)*2"
    src = ["-stream_loop", "-1", "-i", idle] if idle else ["-loop", "1", "-i", face]
    sh(["ffmpeg", "-y", "-loglevel", "error", *src, "-t", f"{seconds:.3f}", "-r", "25", "-an", "-vf", vf,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", dest])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--jobs", required=True, help="JSON list of {audio, out}")
    ap.add_argument("--face", required=True)
    ap.add_argument("--engine", help="LatentSync checkout (default: $LATENTSYNC_DIR)")
    ap.add_argument("--idle", help="live idle clip (without it: a still frame)")
    ap.add_argument("--ver", choices=sorted(VERSIONS), default="1.5")
    ap.add_argument("--size", type=int, default=512)
    ap.add_argument("--steps", type=int, default=20)
    ap.add_argument("--guidance", type=float, default=1.5)
    # The engine writes ~4.4 Mbit/s: 14.6 MB for a 28-second line, close to 700 MB for one
    # section, exactly what weak student devices cannot take. Measured 2026-08-05 on one line:
    # 768/crf26 = 4.7 MB, 768/crf30 = 2.7, 512/crf26 = 2.1, 512/crf30 = 1.3. In the lesson
    # panel the face is small and no difference is visible.
    ap.add_argument("--out-width", type=int, default=512, help="width of the delivered clip")
    ap.add_argument("--out-crf", type=int, default=28, help="compression: higher = smaller file")
    a = ap.parse_args()

    engine = os.path.abspath(a.engine or os.environ.get("LATENTSYNC_DIR") or "")
    if not a.engine and not os.environ.get("LATENTSYNC_DIR"):
        raise SystemExit("set LATENTSYNC_DIR (or --engine) to your LatentSync checkout")
    with open(a.jobs, encoding="utf-8") as f:
        jobs = json.load(f)
    jobs = [j for j in jobs if not os.path.exists(j["out"])]
    if not jobs:
        print("everything is already rendered")
        return

    ckpt_name, config_name = VERSIONS[a.ver]
    ckpt = os.path.join(engine, "checkpoints", ckpt_name)
    config_path = os.path.join(engine, "configs", "unet", config_name)
    for path, what in ((ckpt, f"weights {ckpt_name}"), (config_path, "config")):
        if not os.path.exists(path):
            raise SystemExit(f"missing {what}: {path}")

    # The engine looks for its configs/ and checkpoints/ RELATIVE to the working directory,
    # so we chdir into it; all our paths are made absolute first.
    face = os.path.abspath(a.face)
    idle = os.path.abspath(a.idle) if a.idle else None
    for j in jobs:
        j["audio"] = os.path.abspath(j["audio"])
        j["out"] = os.path.abspath(j["out"])
    os.environ.setdefault("HF_HUB_OFFLINE", "1")      # see lipsync_run.py: the network kills renders
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    sys.path.insert(0, engine)
    os.chdir(engine)

    # Pipeline setup follows LatentSync scripts/inference.py (Apache-2.0, ByteDance): https://github.com/bytedance/LatentSync
    import torch
    from accelerate.utils import set_seed
    from DeepCache import DeepCacheSDHelper
    from diffusers import AutoencoderKL, DDIMScheduler
    from latentsync.models.unet import UNet3DConditionModel
    from latentsync.pipelines.lipsync_pipeline import LipsyncPipeline
    from latentsync.whisper.audio2feature import Audio2Feature
    from omegaconf import OmegaConf

    config = OmegaConf.load(config_path)
    dtype = torch.float16 if torch.cuda.get_device_capability()[0] > 7 else torch.float32

    t0 = time.time()
    whisper = "checkpoints/whisper/tiny.pt" if config.model.cross_attention_dim == 384 else "checkpoints/whisper/small.pt"
    audio_encoder = Audio2Feature(model_path=whisper, device="cuda", num_frames=config.data.num_frames,
                                  audio_feat_length=config.data.audio_feat_length)
    vae = AutoencoderKL.from_pretrained("stabilityai/sd-vae-ft-mse", torch_dtype=dtype)
    vae.config.scaling_factor = 0.18215
    vae.config.shift_factor = 0
    unet, _ = UNet3DConditionModel.from_pretrained(OmegaConf.to_container(config.model), ckpt, device="cpu")
    pipeline = LipsyncPipeline(vae=vae, audio_encoder=audio_encoder, unet=unet.to(dtype=dtype),
                               scheduler=DDIMScheduler.from_pretrained("configs")).to("cuda")
    helper = DeepCacheSDHelper(pipe=pipeline)
    helper.set_params(cache_interval=3, cache_branch_id=0)
    helper.enable()
    set_seed(1247)
    print(f"model loaded in {time.time() - t0:.0f} s, engine {a.ver}, lines {len(jobs)}", flush=True)

    tmp = tempfile.mkdtemp(prefix="lipsync-batch-")
    speech = render = 0.0
    try:
        for i, j in enumerate(jobs, 1):
            wav = os.path.join(tmp, "voice.wav")
            sh(["ffmpeg", "-y", "-loglevel", "error", "-i", j["audio"], "-ac", "1", "-ar", "16000", wav])
            secs = audio_seconds(wav)
            src = os.path.join(tmp, "idle.mp4")
            build_source(face, idle, secs, a.size, src)
            os.makedirs(os.path.dirname(j["out"]) or ".", exist_ok=True)
            t = time.time()
            raw = os.path.join(tmp, "raw.mp4")
            pipeline(video_path=src, audio_path=wav, video_out_path=raw,
                     num_frames=config.data.num_frames, num_inference_steps=a.steps,
                     guidance_scale=a.guidance, weight_dtype=dtype,
                     width=config.data.resolution, height=config.data.resolution,
                     mask_image_path=config.data.mask_image_path, temp_dir=os.path.join(tmp, "engine"))
            w = a.out_width - (a.out_width % 2)
            sh(["ffmpeg", "-y", "-loglevel", "error", "-i", raw, "-vf", f"scale={w}:-2", "-c:v", "libx264",
                "-preset", "slow", "-crf", str(a.out_crf), "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "64k", j["out"]])
            os.remove(raw)
            dt = time.time() - t
            speech += secs
            render += dt
            print(f"  [{i}/{len(jobs)}] {os.path.basename(j['out'])}: speech {secs:.1f} s, "
                  f"render {dt:.0f} s, {os.path.getsize(j['out']) // 1024} KB", flush=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\ndone: speech {speech:.0f} s, render {render:.0f} s (x{render / max(speech, 0.01):.1f} real time)")


if __name__ == "__main__":
    main()
