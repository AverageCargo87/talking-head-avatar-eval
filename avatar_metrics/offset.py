"""Lip-sync A/V offset: is the picture ahead of or behind the sound, in milliseconds?

How it works: find the face, cut out the mouth region and measure its "openness" on every
frame (the grey-level spread inside the region: an open mouth puts a dark cavity next to
light lips and teeth, so the spread jumps). Separately take the loudness envelope of the
audio at the same frame step. Then slide one curve against the other and keep the shift
with the highest correlation.

    lag 0        lips move together with the sound
    lag +N       the picture LAGS the sound by N / fps seconds
    lag -N       the picture LEADS the sound

A low correlation at EVERY shift means something else: the lips do not follow the speech
at all, and moving the audio track will not fix it.

The threshold is not absolute. The metric is coarse: on a clip that is known to be in sync
(lip-sync over a still portrait) the best correlation was only about +0.24. Treat 0.2 as a
good link, not as the absence of one.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import asdict, dataclass
from typing import List, Optional, Tuple

import cv2
import numpy as np

from .video import Box, probe, require_ffmpeg, resolve_face

SAMPLE_RATE = 16000
NO_LINK = 0.10
# Below this spread of mouth openness (grey levels) the mouth does not move at all; codec
# noise alone would otherwise be z-scored up to unit variance and correlate by chance.
STILL_MOUTH = 0.25
# The best lag must beat every lag at least PEAK_DISTANCE frames away by this much,
# otherwise the curve is a plateau and the "best" lag is noise (seen on a bearded host,
# where grey-level spread is a poor proxy for mouth opening).
PEAK_MARGIN = 0.03
PEAK_DISTANCE = 3


@dataclass
class OffsetResult:
    file: str
    frames: int
    fps: float
    face_box: Box
    face_source: str
    mouth_spread: float
    r_at_zero: float
    lag_frames: int
    lag_ms: float
    r_best: float
    peak_margin: float
    verdict: str

    def as_dict(self) -> dict:
        d = asdict(self)
        d["face_box"] = list(self.face_box)
        return d


def read_audio(path: str, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Decode the audio track to mono float32 samples with ffmpeg (piped, no temp files)."""
    cmd = [require_ffmpeg(), "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", str(sample_rate),
           "-f", "s16le", "-"]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0 or not proc.stdout:
        raise ValueError(f"no decodable audio track in {path}: {proc.stderr.decode(errors='replace')[-300:]}")
    return np.frombuffer(proc.stdout, dtype="<i2").astype(np.float32)


def audio_envelope(path: str, fps: float, frames: int) -> np.ndarray:
    """Loudness envelope resampled to one value per video frame."""
    a = read_audio(path)
    step = SAMPLE_RATE / fps
    env = np.zeros(frames, dtype=np.float64)
    for i in range(frames):
        lo, hi = int(i * step), int((i + 1) * step)
        if lo < len(a):
            env[i] = float(np.abs(a[lo:hi]).mean())
    return env


def mouth_roi(box: Box, width: int, height: int) -> Tuple[int, int, int, int]:
    """Mouth = lower part of the face (55-100 % of height), middle 60 % of width.

    Generous on purpose: the head moves a little inside the frame.
    """
    x, y, w, h = box
    mx1, mx2 = max(0, x + w // 5), min(width, x + w - w // 5)
    my1, my2 = max(0, y + int(h * 0.55)), min(height, y + h)
    return mx1, my1, mx2, my2


def mouth_openness(path: str, box: Box) -> Tuple[np.ndarray, float]:
    info = probe(path)
    mx1, my1, mx2, my2 = mouth_roi(box, info.width, info.height)
    cap = cv2.VideoCapture(path)
    values = []
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            roi = cv2.cvtColor(frame[my1:my2, mx1:mx2], cv2.COLOR_BGR2GRAY).astype(np.float32)
            values.append(float(roi.std()))
    finally:
        cap.release()
    return np.array(values), info.fps


def zscore(x: np.ndarray) -> np.ndarray:
    x = x - x.mean()
    s = x.std()
    return x / s if s > 1e-9 else x


def lag_table(mouth: np.ndarray, env: np.ndarray, max_lag: int = 20, min_overlap: int = 20) -> List[Tuple[int, float]]:
    """Correlation of mouth[t + lag] with env[t] for every lag in [-max_lag, max_lag]."""
    m, e = zscore(mouth), zscore(env)
    table = []
    for lag in range(-max_lag, max_lag + 1):
        if lag >= 0:
            a, b = m[lag:], e[:len(e) - lag] if lag else e
        else:
            a, b = m[:len(m) + lag], e[-lag:]
        n = min(len(a), len(b))
        if n < min_overlap:
            continue
        table.append((lag, float((a[:n] * b[:n]).mean())))
    return table


def best_lag(table: List[Tuple[int, float]]) -> Tuple[int, float]:
    if not table:
        return 0, float("nan")
    lag, r = max(table, key=lambda t: t[1])
    return lag, r


def peak_margin(table: List[Tuple[int, float]], lag: int, distance: int = PEAK_DISTANCE) -> float:
    """How much the best lag beats the best lag at least ``distance`` frames away."""
    far = [r for l, r in table if abs(l - lag) >= distance]
    best = dict(table).get(lag, float("nan"))
    return float(best - max(far)) if far else float("nan")


def verdict(lag: int, r: float, fps: float, mouth_spread: float = 1.0, margin: float = 1.0) -> str:
    ms = lag / fps * 1000
    if mouth_spread < STILL_MOUTH:
        return "mouth does not move: nothing to synchronise"
    if not np.isfinite(r) or r < NO_LINK:
        return "no link: lips do not follow the speech; shifting the track will not fix it"
    if np.isfinite(margin) and margin < PEAK_MARGIN:
        return "no clear peak: the correlation curve is flat, offset unreliable (cross-check with SyncNet)"
    if abs(lag) <= 1:
        return "in sync (within one frame)"
    side = "LAGS" if lag > 0 else "LEADS"
    return f"picture {side} the sound by {abs(ms):.0f} ms; fix by shifting the audio track"


def measure_offset(path: str, face_box: Optional[Box] = None, max_lag: int = 20) -> OffsetResult:
    box, source = resolve_face(path, face_box)
    mouth, fps = mouth_openness(path, box)
    env = audio_envelope(path, fps, len(mouth))
    spread = float(mouth.std()) if len(mouth) else 0.0
    table = lag_table(mouth, env, max_lag=max_lag)
    lag, r = best_lag(table)
    r0 = dict(table).get(0, float("nan"))
    margin = peak_margin(table, lag)
    if spread < STILL_MOUTH:
        lag, r, r0, margin = 0, 0.0, 0.0, 0.0
    return OffsetResult(
        file=os.path.basename(path),
        frames=len(mouth),
        fps=float(fps),
        face_box=tuple(int(v) for v in box),
        face_source=source,
        mouth_spread=spread,
        r_at_zero=float(r0),
        lag_frames=int(lag),
        lag_ms=float(lag / fps * 1000),
        r_best=float(r),
        peak_margin=float(margin),
        verdict=verdict(lag, r, fps, spread, margin),
    )
