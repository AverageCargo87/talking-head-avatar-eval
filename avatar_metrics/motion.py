"""Frame motion: how much does the whole picture "twitch"?

Mean absolute difference of consecutive frames after shrinking them to 64x64 grey. At that
size the head and the mouth produce almost all of the motion, so the number tracks how calm
or jumpy a talking head looks. It was used to compare prompt variants of the same host
("calm presenter" vs "lively expressions") without arguing about taste.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import asdict, dataclass

import numpy as np

from .video import require_ffmpeg

SIDE = 64


@dataclass
class MotionResult:
    file: str
    frames: int
    seconds: float
    motion: float
    p95: float

    def as_dict(self) -> dict:
        return asdict(self)


def measure_motion(path: str, seconds: float = 9.0) -> MotionResult:
    cmd = [require_ffmpeg(), "-v", "error", "-i", path, "-t", str(seconds),
           "-vf", f"scale={SIDE}:{SIDE},format=gray", "-f", "rawvideo", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    frames = np.frombuffer(raw, np.uint8).reshape(-1, SIDE, SIDE).astype(np.float32)
    if len(frames) < 2:
        raise ValueError(f"too few frames in {path}")
    d = np.abs(np.diff(frames, axis=0)).mean(axis=(1, 2))
    return MotionResult(
        file=os.path.basename(path),
        frames=int(len(frames)),
        seconds=float(seconds),
        motion=float(d.mean()),
        p95=float(np.percentile(d, 95)),
    )
