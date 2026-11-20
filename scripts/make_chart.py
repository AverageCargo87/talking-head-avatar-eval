"""Draw docs/metrics-chart.png from results/measured.json and results/historical.json.

Three small multiples on the same axes (x = upper/mouth motion ratio, y = coupling):
synthetic ground truth, the clips measured in this repo, and the historical vendor
numbers from the project notes (no vendor media is published, only their numbers).
"""

import json
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SURFACE = "#fcfcfb"
TEXT = "#0b0b0b"
TEXT_2 = "#52514e"
GRID = "#e6e5e0"
CLASS = {  # categorical slots 1-3 of the reference palette, validated all-pairs
    "whole-face": ("#2a78d6", "o", "whole face moves with speech"),
    "patch": ("#eb6834", "s", "mouth patch on a still or looped base"),
    "control": ("#1baf7a", "D", "control (no engine): still frame or zoom"),
}


def load():
    with open(os.path.join(ROOT, "results", "measured.json"), encoding="utf-8") as f:
        measured = json.load(f)
    with open(os.path.join(ROOT, "results", "historical.json"), encoding="utf-8") as f:
        hist = json.load(f)
    return measured, hist


def synth_class(r):
    k = r["truth"]["kind"]
    return {"coupled": "whole-face", "static_patch": "patch", "loop_patch": "patch"}.get(k, "control")


def style_axes(ax, title):
    ax.set_facecolor(SURFACE)
    ax.set_xlim(-0.08, 1.45)
    ax.set_ylim(-0.1, 1.1)
    ax.grid(True, color=GRID, linewidth=1)
    ax.set_axisbelow(True)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(colors=TEXT_2, labelsize=8, length=0)
    ax.set_xlabel("upper-face / mouth motion", color=TEXT_2, fontsize=8.5)
    ax.set_title(title, color=TEXT, fontsize=10, loc="left", pad=8, fontweight="bold")


def dot(ax, x, y, cls):
    color, marker, _ = CLASS[cls]
    ax.scatter([x], [y], s=64, c=color, marker=marker, edgecolors=SURFACE, linewidths=2,
               zorder=4 if cls == "control" else 3)


def label(ax, x, y, text, dx=0.04, dy=0.0, ha="left"):
    ax.annotate(text, (x, y), xytext=(x + dx, y + dy), fontsize=7.4, color=TEXT_2, ha=ha, va="center",
                arrowprops=dict(arrowstyle="-", color="#b9b8b2", lw=0.8) if (abs(dx) > 0.12 or abs(dy) > 0.08) else None)


def main():
    measured, hist = load()
    fig, axes = plt.subplots(1, 3, figsize=(11.5, 4.1), sharey=True, dpi=150)
    fig.patch.set_facecolor(SURFACE)

    # 1. synthetic
    ax = axes[0]
    style_axes(ax, "Synthetic ground truth")
    pos = {"Synthetic: still face + audio": (0.1, -0.075, "still face (control)"),
           "Synthetic: mouth patch on a static base": (0.14, 0.2, "patch, static base"),
           "Synthetic: mouth patch on a looped base": (0.2, 0.33, "patch, looped base"),
           "Synthetic: whole face driven by speech": (0.06, 0.0, "whole face")}
    for r in measured["synthetic"]:
        if r["label"] not in pos:
            continue
        x, y = r["liveness"]["ratio"], r["liveness"]["coupling"]
        dot(ax, x, y, synth_class(r))
        dx, dy, t = pos[r["label"]]
        label(ax, x, y, t, dx=dx, dy=dy, ha="left" if dx >= 0 else "right")
    ax.set_ylabel("coupling (upper vs mouth, Pearson r)", color=TEXT_2, fontsize=8.5)

    # 2. measured real clips
    ax = axes[1]
    style_axes(ax, f"Measured in this repo ({measured['measured_on']})")
    hosts = [r for r in measured["real"] if r["label"].startswith("InfiniteTalk")]
    for r in hosts:
        dot(ax, r["liveness"]["ratio"], r["liveness"]["coupling"], "whole-face")
    xs = [r["liveness"]["ratio"] for r in hosts]
    ys = [r["liveness"]["coupling"] for r in hosts]
    label(ax, max(xs), min(ys), f"InfiniteTalk hosts\n({len(hosts)} measurements, 5 clips)",
          dx=0.0, dy=-0.36, ha="right")
    for r in measured["real"]:
        if r["label"].startswith("Control: still portrait + audio"):
            dot(ax, r["liveness"]["ratio"], r["liveness"]["coupling"], "control")
            label(ax, r["liveness"]["ratio"], r["liveness"]["coupling"], "still portrait + audio", dx=0.06, dy=0.1)
        elif r["label"].startswith("Control: still portrait + breathing"):
            dot(ax, r["liveness"]["ratio"], r["liveness"]["coupling"], "control")
            label(ax, r["liveness"]["ratio"], r["liveness"]["coupling"],
                  "breathing zoom: passes liveness,\nfails lip-sync (no lip link)", dx=-0.86, dy=-0.17, ha="left")

    # 3. historical
    ax = axes[2]
    style_axes(ax, "Historical vendor clips (Aug 2026 notes)")
    hpos = {
        "Local lip-sync on a still photo (LatentSync 1.5)": (0.06, -0.15, "lip-sync on a still photo"),
        "bitHuman Essence 1, take 1": (-0.06, 0.12, "bitHuman, take 1"),
        "bitHuman Essence 1, take 2": (0.07, -0.08, "bitHuman, take 2"),
        "Anam, stock avatar, cara-4": (0.0, -0.22, "Anam (cara-4)"),
        "Wan 2.7 (cloud) on the project's own portrait": (-0.05, 0.1, "Wan 2.7 cloud"),
    }
    for r in hist["liveness"]["rows"]:
        dot(ax, r["ratio"], r["coupling"], r["class"])
        dx, dy, t = hpos[r["label"]]
        label(ax, r["ratio"], r["coupling"], t, dx=dx, dy=dy, ha="center" if dx == 0 else ("left" if dx > 0 else "right"))

    handles = [plt.Line2D([], [], marker=m, color="none", markerfacecolor=c, markeredgecolor=SURFACE,
                          markersize=8, label=t) for c, m, t in CLASS.values()]
    fig.legend(handles=handles, loc="upper left", ncol=3, frameon=False, fontsize=8.5,
               labelcolor=TEXT_2, bbox_to_anchor=(0.012, 0.995))
    fig.text(0.012, 0.035, "Face liveness: does the whole face move, and does it move with the speech? "
             "Top right = alive. Measured with avatar_metrics; historical points are numbers only.",
             fontsize=7.6, color=TEXT_2)
    fig.tight_layout(rect=(0, 0.06, 1, 0.92))
    out = os.path.join(ROOT, "docs", "metrics-chart.png")
    fig.savefig(out, facecolor=SURFACE, metadata={"Software": None})
    print("wrote", out)


if __name__ == "__main__":
    main()
