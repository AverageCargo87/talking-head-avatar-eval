"""Render docs/hero.gif from the two-host InfiniteTalk clip (ffmpeg two-pass palette).

    python scripts/make_hero_gif.py [--start 0.4] [--seconds 4.4] [--width 560] [--fps 12]

The generated microphone carries lettering that looks like a real maker's logo (an
AI artefact). It stays still in this shot, so ffmpeg's delogo paints it out before scaling;
``--no-delogo`` keeps the raw frames.
"""

import argparse
import os
import subprocess
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=os.path.join(ROOT, "samples", "infinitetalk", "two-hosts-17s.mp4"))
    ap.add_argument("--out", default=os.path.join(ROOT, "docs", "hero.gif"))
    ap.add_argument("--start", type=float, default=0.4)
    ap.add_argument("--seconds", type=float, default=4.4)
    ap.add_argument("--width", type=int, default=560)
    ap.add_argument("--fps", type=int, default=12)
    ap.add_argument("--no-delogo", action="store_true", help="keep the lettering on the mic end cap")
    a = ap.parse_args()
    # end-cap lettering of the two-host clip, in source pixels (832x480)
    delogo = "" if a.no_delogo else "delogo=x=31:y=253:w=20:h=21,"
    vf = f"{delogo}fps={a.fps},scale={a.width}:-2:flags=lanczos"
    with tempfile.TemporaryDirectory() as td:
        pal = os.path.join(td, "palette.png")
        cut = ["-ss", str(a.start), "-t", str(a.seconds), "-i", a.src]
        subprocess.run(["ffmpeg", "-v", "error", "-y", *cut, "-vf", f"{vf},palettegen=max_colors=160:stats_mode=diff",
                        pal], check=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", *cut, "-i", pal, "-lavfi",
                        f"{vf}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle",
                        "-loop", "0", a.out], check=True)
    print("wrote", a.out, os.path.getsize(a.out) // 1024, "KB")


if __name__ == "__main__":
    main()
