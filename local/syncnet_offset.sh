#!/usr/bin/env bash
# SyncNet lip-sync score, as in the LatentSync paper: confidence (higher is better) and the
# audio offset in frames (0 is ideal). Uses the evaluation module of a LatentSync checkout
# with its auxiliary SyncNet weights downloaded.
#
#   LATENTSYNC_DIR=/path/to/LatentSync LATENTSYNC_PYTHON=/path/to/venv/bin/python \
#     bash local/syncnet_offset.sh clip1.mp4 [clip2.mp4 ...]
#
# On InfiniteTalk output it reported -2 frames for both 30 s hosts (audio 80 ms behind the
# lips); local/comfy_infinitetalk.py therefore muxes the audio 0.08 s earlier by default.
# Treat it as an aid, not a judge: a second LatentSync pass raised the confidence to
# 7.3-7.5, yet the result was rejected on sight ("uncanny valley, the lips miss").
set -euo pipefail
: "${LATENTSYNC_DIR:?set LATENTSYNC_DIR to your LatentSync checkout}"
: "${LATENTSYNC_PYTHON:?set LATENTSYNC_PYTHON to the interpreter of its environment}"
files=()
for f in "$@"; do files+=("$(realpath "$f")"); done
cd "$LATENTSYNC_DIR"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONIOENCODING=utf-8
for f in "${files[@]}"; do
  r=$("$LATENTSYNC_PYTHON" -m eval.eval_sync_conf --video_path "$f" 2>&1 | grep -E "confidence|offset" | tr '\n' ' ')
  echo "$(basename "$f"): $r"
done
