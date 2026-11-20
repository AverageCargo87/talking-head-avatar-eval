#!/usr/bin/env python3
"""LIP-SYNC WRAPPER: portrait + line of speech -> talking-teacher clip (LatentSync).

Why it exists: LatentSync is a VIDEO-to-VIDEO engine. It re-draws the lips of an existing
clip and does not accept a photo. Our input is a portrait, so the wrapper builds an "idle"
clip of the right length from a single frame (or loops a ready idle clip), hands it to the
engine together with the audio, and puts the result where the prerender asked.

Plugs into prerender/make-teacher-clips.mjs with one line:
  LIPSYNC_CMD="python prerender/lipsync_run.py --face {face} --audio {audio} --out {out}"

Requirements: a LatentSync checkout with its checkpoints (point LATENTSYNC_DIR or --engine
at it) and a Python environment with CUDA torch, run with that environment's interpreter.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

# VERSION AND RESOLUTION ARE ONE DECISION; separately they are meaningless.
# The 256 and 512 configs differ in exactly one line (resolution), so a mismatched config
# LOADS WITHOUT AN ERROR and silently produces garbage: rectangular patches on the cheeks
# and smearing (caught on 2026-08-04: v1.6 weights through the 256 config). The only
# protection is to take the pair as a whole.
#
# Requirements from the LatentSync README, on a 12 GB RTX 3060:
#   1.5 -> 256, inference needs  8 GB -> fits;
#   1.6 -> 512, inference needs 18 GB -> does NOT fit, the card chokes.
# Measured 2026-08-04 (3.84 s of speech, 96 frames): 1.6/512 took 875 s, 1.5/256 about 75 s.
# Never use the stage2_efficient config with these weights: it has a different motion
# module architecture (motion_module_decoder_only) and does not match the checkpoints.
VERSIONS = {
    "1.5": ("latentsync_unet_15.pt", "stage2.yaml"),
    "1.6": ("latentsync_unet.pt", "stage2_512.yaml"),
}


def engine_dir(cli_value):
    path = cli_value or os.environ.get("LATENTSYNC_DIR")
    if not path:
        raise SystemExit("set LATENTSYNC_DIR (or --engine) to your LatentSync checkout")
    return os.path.abspath(path)


def run(cmd, **kw):
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", **kw)
    if p.returncode != 0:
        sys.stderr.write((p.stderr or p.stdout or "")[-2500:] + "\n")
        raise SystemExit(f"failed: {' '.join(str(c) for c in cmd[:3])}... (exit {p.returncode})")
    return p


def audio_seconds(path):
    p = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", path])
    return float(json.loads(p.stdout)["format"]["duration"])


def build_idle(face, idle, seconds, width, dest):
    """Idle clip of the right length: a looped live idle clip or a still frame."""
    w = width - (width % 2)
    # Even width and height are mandatory for yuv420p, libx264 refuses otherwise.
    vf = f"scale={w}:-2,pad=ceil(iw/2)*2:ceil(ih/2)*2"
    src = ["-stream_loop", "-1", "-i", idle] if idle else ["-loop", "1", "-i", face]
    # ALWAYS scale to --size: the engine processes the face at its own resolution and pastes
    # it back. If the face in the frame is much larger than that, the result is stretched: a
    # rectangular patch shows on the cheek and everything blurs (caught on a 768 frame with
    # res 256). A 512 frame with res 256 maps cleanly.
    run(["ffmpeg", "-y", "-loglevel", "error", *src, "-t", f"{seconds:.3f}", "-r", "25", "-an",
         "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", dest])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--face", required=True, help="teacher portrait (png/jpg)")
    ap.add_argument("--audio", required=True, help="line of speech (mp3/wav)")
    ap.add_argument("--out", required=True, help="where to put the finished mp4")
    ap.add_argument("--engine", help="LatentSync checkout (default: $LATENTSYNC_DIR)")
    ap.add_argument("--idle", help="ready idle clip instead of a still frame")
    ap.add_argument("--steps", type=int, default=20)
    ap.add_argument("--guidance", type=float, default=1.5)
    ap.add_argument("--size", type=int, default=512, help="frame width of the idle clip")
    ap.add_argument("--ver", choices=sorted(VERSIONS), default="1.5",
                    help="engine version; it also fixes the resolution (see the header)")
    # The mask decides WHICH part of the face the engine redraws to the audio. The stock
    # mask takes the mouth only: jaw and cheeks stay from the base clip and keep moving to
    # ITS rhythm. Measured 2026-08-05: own lip motion from lip-sync 1.10, residual mouth
    # motion from the base 4.32, i.e. the base drowns the lip-sync fourfold, which reads as
    # "the lips miss the voice". mask4 covers the face from the nose down, fixes the sync,
    # and lays a grey band across the eyes.
    ap.add_argument("--mask", default=None, help="mask name in latentsync/utils (mask|mask2|mask3|mask4)")
    a = ap.parse_args()

    engine = engine_dir(a.engine)
    ckpt_name, config_name = VERSIONS[a.ver]
    ckpt = os.path.join(engine, "checkpoints", ckpt_name)
    config = os.path.join(engine, "configs", "unet", config_name)
    for path, what in ((engine, "engine"), (ckpt, f"weights {ckpt_name}"), (config, "config")):
        if not os.path.exists(path):
            raise SystemExit(f"missing {what}: {path}")

    tmp = tempfile.mkdtemp(prefix="lipsync-")
    try:
        if a.mask:
            # patch a COPY of the config in our temp folder; the engine checkout stays untouched
            src_cfg = open(config, encoding="utf-8").read()
            config = os.path.join(tmp, f"{a.mask}_{config_name}")
            with open(config, "w", encoding="utf-8") as f:
                f.write(re.sub(r"mask_image_path:.*", f"mask_image_path: latentsync/utils/{a.mask}.png", src_cfg))
        # Whisper inside the engine expects 16 kHz mono; convert ourselves instead of relying
        # on whatever the synthesizer returned.
        wav = os.path.join(tmp, "voice.wav")
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", a.audio, "-ac", "1", "-ar", "16000", wav])
        dur = audio_seconds(wav)
        src = os.path.join(tmp, "idle.mp4")
        build_idle(a.face, a.idle, dur, a.size, src)

        # The engine checks the Hugging Face cache for its VAE on EVERY run, and a dropped
        # connection kills the whole render (caught on 2026-08-04). Everything is downloaded
        # on the first run, so run offline: no network dependency, no network latency.
        env = dict(os.environ, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
        made = os.path.join(tmp, "talking.mp4")
        run([sys.executable, "-m", "scripts.inference",
             "--unet_config_path", config, "--inference_ckpt_path", ckpt,
             "--inference_steps", str(a.steps), "--guidance_scale", str(a.guidance), "--enable_deepcache",
             "--video_path", src, "--audio_path", wav,
             "--temp_dir", os.path.join(tmp, "engine"), "--video_out_path", made],
            cwd=engine, env=env)
        os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
        shutil.move(made, a.out)
        print(f"done: {a.out}, {dur:.1f} s, {os.path.getsize(a.out) // 1024} KB, engine {a.ver}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
