"""Build the negative controls from a host clip, with ffmpeg only.

    python scripts/make_controls.py samples/infinitetalk/lena-9s.mp4 samples/controls

Writes two clips next to each other, both carrying the ORIGINAL audio of the host clip:

``<name>-still.mp4``   the clip's first frame held still + the audio. Nothing moves, so
                        liveness must read ~0 and the offset metric must refuse to find a
                        lip link. This is the "still portrait + audio" control.
``<name>-zoom.mp4``    the same frame with the slow "breathing" zoom that the prerender stub
                        uses (``prerender/make-teacher-clips.mjs``). The whole picture moves,
                        but not with the speech: a trap for any metric that only counts motion.
"""

import os
import subprocess
import sys
import tempfile


def run(cmd):
    subprocess.run(cmd, check=True)


def main(src: str, out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    name = os.path.splitext(os.path.basename(src))[0]
    with tempfile.TemporaryDirectory() as td:
        frame = os.path.join(td, "first.png")
        run(["ffmpeg", "-v", "error", "-y", "-i", src, "-frames:v", "1", frame])
        common = ["-map", "0:v", "-map", "1:a", "-c:a", "copy", "-shortest", "-r", "25",
                  "-c:v", "libx264", "-preset", "slow", "-crf", "23", "-pix_fmt", "yuv420p",
                  "-map_metadata", "-1", "-fflags", "+bitexact"]
        run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-i", frame, "-i", src, *common,
             os.path.join(out_dir, f"{name}-still.mp4")])
        size = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                               "stream=width,height", "-of", "csv=s=x:p=0", src],
                              capture_output=True, text=True, check=True).stdout.strip()
        zoom =f"scale={size.replace('x', ':')},zoompan=z='min(1.06,1+0.0006*on)':d=1:s={size}:fps=25"
        run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-i", frame, "-i", src, "-vf", zoom, *common,
             os.path.join(out_dir, f"{name}-zoom.mp4")])
    print("controls written to", out_dir)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
