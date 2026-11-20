#!/usr/bin/env bash
# Stitch frames that ComfyUI finished writing after the API client had already given up
# (a long render outlived the client's timeout), with the same A/V shift as the runner.
#
#   bash local/stitch_frames.sh <frames_dir> <audio.wav> <out.mp4> [shift_seconds=0.08]
#
# Waits until the first sampler window (81 frames) is on disk, then muxes.
set -euo pipefail
FRAMES=$1; AUDIO=$2; OUT=$3; SHIFT=${4:-0.08}
until [ "$(ls "$FRAMES"/*/frame_*.png 2>/dev/null | wc -l)" -ge 81 ]; do sleep 15; done
sleep 10
SUB=$(ls -d "$FRAMES"/*_output | tail -1)
ffmpeg -y -v error -framerate 25 -i "$SUB/frame_%05d.png" -ss "$SHIFT" -i "$AUDIO" -af apad \
  -c:v libx264 -crf 17 -preset slow -pix_fmt yuv420p -c:a aac -b:a 192k -shortest "$OUT"
echo "stitched $OUT"
