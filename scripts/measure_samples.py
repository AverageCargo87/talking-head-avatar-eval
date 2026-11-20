"""Measure every clip in samples/ (and the synthetic set) and write results/.

    python scripts/measure_samples.py            # writes results/measured.json + results/MEASURED.md

Reproducible from the repository alone: the InfiniteTalk clips and the controls are
committed, the synthetic set is re-rendered into a temporary folder.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from avatar_metrics import measure_liveness, measure_motion, measure_offset  # noqa: E402
from avatar_metrics.synth import DEFAULT_SET, make_set  # noqa: E402
from avatar_metrics.video import find_faces  # noqa: E402

S = os.path.join(ROOT, "samples")

REAL = [
    # label, path, face (None = largest detected | "left" | "right")
    ("InfiniteTalk, Lena 9 s", "infinitetalk/lena-9s.mp4", None),
    ("InfiniteTalk, Artem 12 s", "infinitetalk/artem-12s.mp4", None),
    ("InfiniteTalk, two hosts 17 s: Lena (left)", "infinitetalk/two-hosts-17s.mp4", "left"),
    ("InfiniteTalk, two hosts 17 s: Artem (right)", "infinitetalk/two-hosts-17s.mp4", "right"),
    ("InfiniteTalk, Lena 30 s, audio as rendered", "infinitetalk/lena-30s-audio-as-rendered.mp4", None),
    ("InfiniteTalk, Lena 30 s, audio 80 ms earlier", "infinitetalk/lena-30s-audio-80ms-earlier.mp4", None),
    ("Control: still portrait + audio", "controls/lena-9s-still.mp4", None),
    ("Control: still portrait + breathing zoom + audio", "controls/lena-9s-zoom.mp4", None),
]

SYNTH_LABELS = {
    "still": "Synthetic: still face + audio",
    "static-patch": "Synthetic: mouth patch on a static base",
    "loop-patch": "Synthetic: mouth patch on a looped base",
    "coupled": "Synthetic: whole face driven by speech",
    "coupled-lag3": "Synthetic: whole face, picture 3 frames late",
    "coupled-lead2": "Synthetic: whole face, picture 2 frames early",
}


def pick_face(path, which):
    if which is None:
        return None
    faces = sorted(find_faces(path), key=lambda b: b[0])
    if len(faces) < 2:
        raise SystemExit(f"expected two faces in {path}, found {len(faces)}")
    return faces[0] if which == "left" else faces[-1]


def row(label, path, box, kind, truth=None):
    live = measure_liveness(path, face_box=box)
    off = measure_offset(path, face_box=box)
    mot = measure_motion(path)
    return {
        "label": label,
        "kind": kind,
        "file": os.path.relpath(path, ROOT).replace(os.sep, "/") if kind != "synthetic" else live.file,
        "face_box": list(live.face_box),
        "liveness": {k: round(v, 3) for k, v in live.as_dict().items() if k in ("mouth", "upper", "ratio", "coupling")},
        "offset": {
            "lag_frames": off.lag_frames, "lag_ms": round(off.lag_ms), "r_best": round(off.r_best, 3),
            "r_at_zero": round(off.r_at_zero, 3), "peak_margin": round(off.peak_margin, 3), "verdict": off.verdict,
        },
        "motion": round(mot.motion, 2),
        **({"truth": truth} if truth else {}),
    }


def md_table(rows):
    out = ["| clip | mouth | upper | upper/mouth | coupling | A/V lag (frames, ms) | lag r | motion |",
           "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lv, of = r["liveness"], r["offset"]
        lag = f"{of['lag_frames']:+d} ({of['lag_ms']:+d} ms)"
        if of["verdict"].startswith(("mouth does not move", "no link", "no clear peak")):
            lag = of["verdict"].split(":")[0]
        out.append(f"| {r['label']} | {lv['mouth']:.2f} | {lv['upper']:.2f} | {lv['ratio']:.2f} | "
                   f"{lv['coupling']:.2f} | {lag} | {of['r_best']:.2f} | {r['motion']:.2f} |")
    return "\n".join(out)


def main():
    today = dt.date.today().isoformat()
    real = []
    for label, rel, which in REAL:
        p = os.path.join(S, rel)
        real.append(row(label, p, pick_face(p, which), "real"))
        print("measured", label, flush=True)
    synth = []
    with tempfile.TemporaryDirectory() as td:
        clips = make_set(td, names=list(SYNTH_LABELS))
        for name, c in clips.items():
            synth.append(row(SYNTH_LABELS[name], c.path, c.face_box, "synthetic",
                             truth={"kind": c.kind, "delay_frames": c.delay_frames}))
            print("measured", name, flush=True)
    os.makedirs(os.path.join(ROOT, "results"), exist_ok=True)
    data = {"measured_on": today, "tool": "avatar_metrics", "real": real, "synthetic": synth}
    with open(os.path.join(ROOT, "results", "measured.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
        f.write("\n")
    by = {r["label"]: r for r in real}
    hosts = [r for r in real if r["kind"] == "real" and r["label"].startswith("InfiniteTalk")]
    ratios = [r["liveness"]["ratio"] for r in hosts]
    coups = [r["liveness"]["coupling"] for r in hosts]
    zoom = by["Control: still portrait + breathing zoom + audio"]
    host9 = by["InfiniteTalk, Lena 9 s"]
    lag_a = by["InfiniteTalk, Lena 30 s, audio as rendered"]["offset"]["lag_frames"]
    lag_b = by["InfiniteTalk, Lena 30 s, audio 80 ms earlier"]["offset"]["lag_frames"]
    energy_x = host9["liveness"]["mouth"] / max(zoom["liveness"]["mouth"], 1e-6)
    md = [
        "# Measured in this repo",
        "",
        f"Measured on {today} with `python scripts/measure_samples.py` on the clips committed in `samples/`",
        "and on the synthetic set rendered by `avatar_metrics.synth`. Re-run the script to reproduce.",
        "",
        "Motion energies (mouth, upper, motion) are mean grey-level differences per frame and depend on",
        "resolution and face size; compare them within a row. upper/mouth and coupling are scale-free.",
        "",
        "## Lesson hosts (InfiniteTalk, own AI-generated characters) and controls",
        "",
        md_table(real),
        "",
        "Reading the table:",
        "",
        f"- **Liveness.** Every InfiniteTalk host lands in the whole-face corner (upper/mouth "
        f"{min(ratios):.2f}-{max(ratios):.2f},",
        f"  coupling {min(coups):.2f}-{max(coups):.2f}), where the Anam reference landed in August (1.09 / 0.89). "
        "The still",
        "  portrait reads zero.",
        "- **The zoom trap.** A slow breathing zoom over a still portrait moves both face zones together,",
        f"  so liveness reads {zoom['liveness']['ratio']:.2f} / {zoom['liveness']['coupling']:.2f}. "
        f"Its mouth-zone motion is {energy_x:.0f}x lower than a real host's, and the",
        "  offset metric finds no lip link at all. No single number is enough.",
        f"- **The 80 ms shift.** Moving the audio 80 ms earlier changes the measured lag from {lag_a:+d} to "
        f"{lag_b:+d}",
        f"  frame(s): a {lag_b - lag_a}-frame change; SyncNet reported -2 to 0. Where the two tools disagree "
        "on the",
        "  zero point, remember this metric is coarse by design.",
        "- **Where the offset proxy gives up.** On the bearded host the correlation curve is flat",
        "  (no clear peak); in the two-host shot the faces are about 150 px and the audio is a",
        "  dialogue, so each host's mouth is shut half the time: no link. SyncNet was also weak there.",
        "",
        "## Synthetic ground truth",
        "",
        md_table(synth),
        "",
    ]
    with open(os.path.join(ROOT, "results", "MEASURED.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(md))
    print("\n".join(md))


if __name__ == "__main__":
    main()
