"""Command line: ``python -m avatar_metrics <command> ...`` (or the ``avatar-metrics`` script).

Commands:
  liveness  VIDEO...            upper vs mouth motion and their coupling
  offset    VIDEO...            lip-sync A/V offset from mouth openness vs audio envelope
  motion    VIDEO...            overall frame motion (how jumpy the picture is)
  identity  VIDEO... [--ref P]  face identity seam between clips (insightface or pixels)
  faces     VIDEO               list detected face boxes (for two-host shots)
  synth     OUTDIR              render the synthetic ground-truth set
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import List

from .identity import identity_report, make_embedder
from .liveness import measure_liveness
from .motion import measure_motion
from .offset import measure_offset
from .video import find_faces, parse_box


def _out(rows: List[dict], as_json: bool, printer) -> None:
    if as_json:
        print(json.dumps(rows, indent=1, ensure_ascii=False))
    else:
        printer(rows)


def _print_liveness(rows):
    print(f"{'clip':<34}{'frames':>7}{'mouth':>8}{'upper':>8}{'up/mouth':>10}{'COUPLING':>10}")
    print("-" * 77)
    for r in rows:
        if "error" in r:
            print(f"{r['file']:<34} ERROR: {r['error']}")
            continue
        note = "" if r["face_source"] != "center" else "  (no face found, centre of frame)"
        print(f"{r['file'][:33]:<34}{r['frames']:>7}{r['mouth']:>8.2f}{r['upper']:>8.2f}"
              f"{r['ratio']:>10.2f}{r['coupling']:>10.2f}{note}")


def _print_offset(rows):
    for r in rows:
        print(f"\n=== {r['file']} ===")
        if "error" in r:
            print(f"  ERROR: {r['error']}")
            continue
        print(f"  frames {r['frames']} at {r['fps']:.2f} fps, face {r['face_source']} {r['face_box']}")
        print(f"  correlation at zero shift : {r['r_at_zero']:+.3f}")
        print(f"  best shift                : {r['lag_frames']:+d} frames ({r['lag_ms']:+.0f} ms), "
              f"correlation {r['r_best']:+.3f} (peak margin {r['peak_margin']:+.3f})")
        print(f"  verdict: {r['verdict']}")


def _print_motion(rows):
    print(f"{'clip':<40}{'frames':>7}{'motion':>9}{'p95':>8}")
    for r in rows:
        print(f"{r['file'][:39]:<40}{r['frames']:>7}{r['motion']:>9.2f}{r['p95']:>8.2f}")


def _print_identity(report):
    print(f"backend: {report['backend']}" + (f", reference: {report['reference']}" if report["reference"] else ""))
    for c in report["clips"]:
        if c["to_reference"] is None:
            print(f"  {c['file']}: {c['frames_with_face']} frames with a face")
        else:
            print(f"  {c['file']}: to reference {c['to_reference']:.3f} "
                  f"(spread +/-{c['spread']:.3f}, worst frame {c['worst']:.3f})")
    if report["pairs"]:
        print("\n  SEAM between clips (0.90+ invisible switch, below 0.85 a visible cut):")
        for p in report["pairs"]:
            print(f"     {p['a']} <-> {p['b']}: {p['seam']:.3f}")


def _safe(fn, path, **kw):
    try:
        return fn(path, **kw).as_dict()
    except Exception as exc:  # report and continue with the next clip
        import os
        return {"file": os.path.basename(path), "error": str(exc)}


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(prog="avatar-metrics", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p, box=True):
        p.add_argument("videos", nargs="+")
        p.add_argument("--json", action="store_true", help="machine-readable output")
        if box:
            p.add_argument("--face-box", help="x,y,w,h instead of Haar face detection")

    p = sub.add_parser("liveness", help="upper vs mouth motion and their coupling")
    common(p)
    p.add_argument("--max-frames", type=int, default=500)
    p = sub.add_parser("offset", help="lip-sync A/V offset")
    common(p)
    p.add_argument("--max-lag", type=int, default=20, help="search range in frames (default 20 = 0.8 s)")
    p = sub.add_parser("motion", help="overall frame motion")
    common(p, box=False)
    p.add_argument("--seconds", type=float, default=9.0)
    p = sub.add_parser("identity", help="face identity seam between clips")
    common(p)
    p.add_argument("--ref", help="reference portrait (png/jpg)")
    p.add_argument("--backend", default="insightface", choices=["insightface", "pixels"])
    p.add_argument("--samples", type=int, default=12)
    p = sub.add_parser("faces", help="list detected face boxes")
    p.add_argument("video")
    p = sub.add_parser("synth", help="render the synthetic ground-truth set")
    p.add_argument("out_dir")
    p.add_argument("--seconds", type=float, default=8.0)
    p.add_argument("--seed", type=int, default=3)

    a = ap.parse_args(argv)
    if a.cmd == "liveness":
        box = parse_box(a.face_box)
        _out([_safe(measure_liveness, v, face_box=box, max_frames=a.max_frames) for v in a.videos],
             a.json, _print_liveness)
    elif a.cmd == "offset":
        box = parse_box(a.face_box)
        _out([_safe(measure_offset, v, face_box=box, max_lag=a.max_lag) for v in a.videos], a.json, _print_offset)
    elif a.cmd == "motion":
        _out([_safe(measure_motion, v, seconds=a.seconds) for v in a.videos], a.json, _print_motion)
    elif a.cmd == "identity":
        emb = make_embedder(a.backend, parse_box(a.face_box))
        report = identity_report(emb, a.videos, reference=a.ref, samples=a.samples)
        if a.json:
            print(json.dumps(report, indent=1))
        else:
            _print_identity(report)
    elif a.cmd == "faces":
        for b in find_faces(a.video):
            print(",".join(str(v) for v in b))
    elif a.cmd == "synth":
        from .synth import make_set
        clips = make_set(a.out_dir, seconds=a.seconds, seed=a.seed)
        for name, c in clips.items():
            print(f"{name:<18} kind={c.kind:<13} delay={c.delay_frames:+d}  face_box={','.join(map(str, c.face_box))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
