"""Small video helpers shared by all metrics: probing, face finding, box parsing."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from typing import Iterator, List, Optional, Tuple

import cv2
import numpy as np

Box = Tuple[int, int, int, int]  # x, y, w, h

# OpenCV 5 dropped CascadeClassifier from the main wheel; we pin opencv < 5.
CASCADE = os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")


@dataclass
class VideoInfo:
    path: str
    width: int
    height: int
    fps: float
    frames: int


def require_ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("ffmpeg is not on PATH; it is needed to read audio tracks")
    return exe


def probe(path: str) -> VideoInfo:
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise FileNotFoundError(f"cannot open video: {path}")
    info = VideoInfo(
        path=path,
        width=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        height=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        fps=float(cap.get(cv2.CAP_PROP_FPS) or 25.0),
        frames=int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0),
    )
    cap.release()
    return info


def parse_box(text: Optional[str]) -> Optional[Box]:
    """Parse ``"x,y,w,h"`` into a box tuple; ``None`` passes through."""
    if text is None:
        return None
    parts = [int(round(float(p))) for p in str(text).split(",")]
    if len(parts) != 4 or parts[2] <= 0 or parts[3] <= 0:
        raise ValueError(f"face box must be 'x,y,w,h' with positive w,h, got {text!r}")
    return parts[0], parts[1], parts[2], parts[3]


def detect_faces_in_frame(gray: np.ndarray, min_size: int = 60) -> List[Box]:
    detector = cv2.CascadeClassifier(CASCADE)
    faces = detector.detectMultiScale(gray, 1.1, 5, minSize=(min_size, min_size))
    boxes = [tuple(int(v) for v in f) for f in faces]
    return sorted(boxes, key=lambda b: b[2] * b[3], reverse=True)


def find_faces(path: str, max_probe: int = 40) -> List[Box]:
    """All faces on the first frame (within ``max_probe`` frames) that has any face.

    Sorted by area, largest first. Empty list when nothing is found.
    """
    cap = cv2.VideoCapture(path)
    try:
        for _ in range(max_probe):
            ok, frame = cap.read()
            if not ok:
                break
            boxes = detect_faces_in_frame(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
            if boxes:
                return boxes
    finally:
        cap.release()
    return []


def center_box(width: int, height: int, share: float = 0.7) -> Box:
    """Fallback when no face is found: a centred square, better than nothing."""
    side = int(min(width, height) * share)
    return (width - side) // 2, (height - side) // 2, side, side


def resolve_face(path: str, face_box: Optional[Box]) -> Tuple[Box, str]:
    """Return ``(box, source)`` where source is ``given``, ``detected`` or ``center``."""
    if face_box is not None:
        return face_box, "given"
    found = find_faces(path)
    if found:
        return found[0], "detected"
    info = probe(path)
    return center_box(info.width, info.height), "center"


def clamp_rows(lo: int, hi: int, limit: int) -> Tuple[int, int]:
    lo, hi = max(0, lo), min(limit, hi)
    return lo, max(lo + 1, hi)


def iter_gray(path: str, max_frames: Optional[int] = None) -> Iterator[np.ndarray]:
    cap = cv2.VideoCapture(path)
    n = 0
    try:
        while max_frames is None or n < max_frames:
            ok, frame = cap.read()
            if not ok:
                break
            yield cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
            n += 1
    finally:
        cap.release()
