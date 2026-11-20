"""Face liveness: is the WHOLE face alive, or is a mouth patch pasted onto a static base?

This metric settled a month-long argument about one avatar vendor. Method:

1. Find the face and split it into an upper zone (brows, eyes: 15-50 % of the face
   height) and a lower zone (mouth, jaw: 60-100 %).
2. For every pair of consecutive frames take the mean absolute grey-level difference in
   each zone. That gives two time series: upper motion and mouth motion.
3. Report three numbers:

   ``mouth``     mean motion energy of the lower zone. Anything that talks has it.
   ``upper``     mean motion energy of the upper zone. About 0 for a mouth patch on a
                 still photo.
   ``coupling``  Pearson correlation between the two series, frame by frame. This is the
                 discriminator: in a generative engine the brows and eyes move in the
                 rhythm of speech (high coupling); in a "mouth patch on a looped base" the
                 upper face comes from an unrelated idle loop (coupling near zero).

``ratio = upper / mouth`` is printed too: a face whose upper half barely moves reads as
a mask even when the mouth is perfect.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Optional

import numpy as np

from .video import Box, clamp_rows, iter_gray, probe, resolve_face

UPPER_ZONE = (0.15, 0.50)
LOWER_ZONE = (0.60, 1.00)
# Below this mean motion the mouth zone is effectively still (codec noise only), and an
# upper/mouth ratio would be a ratio of two noise floors. Reported as 0 instead.
STILL = 0.05


@dataclass
class LivenessResult:
    file: str
    frames: int
    size: str
    face_box: Box
    face_source: str
    mouth: float
    upper: float
    ratio: float
    coupling: float

    def as_dict(self) -> dict:
        d = asdict(self)
        d["face_box"] = list(self.face_box)
        return d


def zone_series(path: str, box: Box, max_frames: int = 500):
    """Per-frame motion energy of the upper and lower face zones."""
    info = probe(path)
    x, y, w, h = box
    x0, x1 = max(0, x), min(info.width, x + w)
    up = clamp_rows(y + int(UPPER_ZONE[0] * h), y + int(UPPER_ZONE[1] * h), info.height)
    lo = clamp_rows(y + int(LOWER_ZONE[0] * h), y + int(LOWER_ZONE[1] * h), info.height)
    upper, lower = [], []
    prev = None
    count = 0
    for gray in iter_gray(path, max_frames):
        if prev is not None:
            delta = np.abs(gray - prev)
            upper.append(float(delta[up[0]:up[1], x0:x1].mean()))
            lower.append(float(delta[lo[0]:lo[1], x0:x1].mean()))
        prev = gray
        count += 1
    return np.array(upper), np.array(lower), count, info


def pearson(a: np.ndarray, b: np.ndarray) -> float:
    if len(a) < 2 or a.std() < 1e-6 or b.std() < 1e-6:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def measure_liveness(path: str, face_box: Optional[Box] = None, max_frames: int = 500) -> LivenessResult:
    box, source = resolve_face(path, face_box)
    upper, lower, count, info = zone_series(path, box, max_frames)
    if len(lower) < 10:
        raise ValueError(f"too few frames in {path} ({len(lower)} frame differences)")
    mouth = float(lower.mean())
    up = float(upper.mean())
    # Both zones still: whatever correlation is left comes from codec noise (key-frame
    # pulses hit both zones at once), so it is reported as 0 rather than as "coupling".
    coupling = pearson(upper, lower) if max(mouth, up) > STILL else 0.0
    return LivenessResult(
        file=os.path.basename(path),
        frames=count,
        size=f"{info.width}x{info.height}",
        face_box=tuple(int(v) for v in box),
        face_source=source,
        mouth=mouth,
        upper=up,
        ratio=up / mouth if mouth > STILL else 0.0,
        coupling=coupling,
    )
