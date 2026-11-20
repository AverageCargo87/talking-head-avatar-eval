"""Face identity seam: is it still the same person after the lesson switches engines?

Why it matters: a lesson can be assembled from two circuits, prerendered clips for the
fixed text and a live service for answers. If the prerecorded face and the live face differ,
every switch shows a SEAM, and it lands in the worst possible moment: the child has just
asked a question and is looking straight at the face. Comparing that by eye is useless, so
it is measured.

How: embed the face on a reference portrait and on frames of every clip, then take cosine
similarities.

    >= 0.90      the same person, a switch is not noticeable
    0.70 - 0.90  a related face, the seam shows at the cut
    < 0.70       different people

Also reported: the spread of the similarity across frames of ONE clip. A large spread means
the face drifts inside the clip itself, which is visible too.

The seam between two clips is the cosine between their MEAN embeddings, not the difference
of their similarities to the reference. The latter means nothing: two different faces can be
equally far from a third one.

Backends:

* ``insightface`` (default): ``buffalo_l`` ArcFace embeddings, the backend behind the
  historical numbers. Optional dependency; its pretrained weights are licensed for
  non-commercial research only and are downloaded by insightface on first use.
* ``pixels``: a deterministic toy embedding (normalised 32x32 grey face crop). It has no
  notion of identity beyond pixels and exists so that the seam arithmetic can be tested
  offline on synthetic faces. Do not use it on real people.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Protocol

import cv2
import numpy as np

from .video import Box, detect_faces_in_frame


class Embedder(Protocol):
    name: str

    def embed(self, bgr: np.ndarray) -> Optional[np.ndarray]:
        """Return an L2-normalised embedding of the main face, or None."""


class InsightFaceEmbedder:
    name = "insightface"

    def __init__(self, model: str = "buffalo_l", det_size: int = 512):
        try:
            from insightface.app import FaceAnalysis  # type: ignore
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("pip install insightface onnxruntime  (or use --backend pixels for tests)") from exc
        self.app = FaceAnalysis(name=model, providers=["CPUExecutionProvider"])
        self.app.prepare(ctx_id=-1, det_size=(det_size, det_size))

    def embed(self, bgr: np.ndarray) -> Optional[np.ndarray]:  # pragma: no cover - needs weights
        faces = self.app.get(bgr)
        if not faces:
            return None
        face = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
        return np.asarray(face.normed_embedding, dtype=np.float32)


class PixelEmbedder:
    """Toy embedding for offline tests: zero-mean, unit-norm 32x32 grey crop of the face."""

    name = "pixels"

    def __init__(self, face_box: Optional[Box] = None, side: int = 32):
        self.face_box = face_box
        self.side = side

    def embed(self, bgr: np.ndarray) -> Optional[np.ndarray]:
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        box = self.face_box
        if box is None:
            found = detect_faces_in_frame(gray)
            if not found:
                return None
            box = found[0]
        x, y, w, h = box
        crop = gray[max(0, y):y + h, max(0, x):x + w].astype(np.float32)
        if crop.size == 0:
            return None
        v = cv2.resize(crop, (self.side, self.side), interpolation=cv2.INTER_AREA).ravel()
        v = v - v.mean()
        n = np.linalg.norm(v)
        return v / n if n > 1e-9 else None


def make_embedder(backend: str, face_box: Optional[Box] = None) -> Embedder:
    if backend == "insightface":
        return InsightFaceEmbedder()
    if backend == "pixels":
        return PixelEmbedder(face_box=face_box)
    raise ValueError(f"unknown backend {backend!r} (insightface | pixels)")


def embed_image(embedder: Embedder, path: str) -> np.ndarray:
    img = cv2.imread(path)
    if img is None:
        raise FileNotFoundError(f"cannot read image: {path}")
    e = embedder.embed(img)
    if e is None:
        raise ValueError(f"no face found in {path}")
    return e


def embed_video(embedder: Embedder, path: str, samples: int = 12) -> List[np.ndarray]:
    cap = cv2.VideoCapture(path)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
    out = []
    try:
        for i in np.linspace(0, max(total - 1, 0), samples).astype(int):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
            ok, frame = cap.read()
            if not ok:
                continue
            e = embedder.embed(frame)
            if e is not None:
                out.append(e)
    finally:
        cap.release()
    return out


def unit(v: np.ndarray) -> np.ndarray:
    return v / (np.linalg.norm(v) + 1e-9)


def seam(a: List[np.ndarray], b: List[np.ndarray]) -> float:
    """Cosine between the mean embeddings of two clips."""
    return float(np.dot(unit(np.mean(a, axis=0)), unit(np.mean(b, axis=0))))


@dataclass
class ClipIdentity:
    file: str
    frames_with_face: int
    to_reference: Optional[float]
    spread: Optional[float]
    worst: Optional[float]


def identity_report(embedder: Embedder, videos: List[str], reference: Optional[str] = None,
                    samples: int = 12) -> Dict:
    ref = embed_image(embedder, reference) if reference else None
    clips: List[ClipIdentity] = []
    embs: Dict[str, List[np.ndarray]] = {}
    for v in videos:
        es = embed_video(embedder, v, samples)
        name = os.path.basename(v)
        embs[name] = es
        if not es or ref is None:
            clips.append(ClipIdentity(name, len(es), None, None, None))
            continue
        sims = np.array([float(np.dot(ref, e)) for e in es])
        clips.append(ClipIdentity(name, len(es), float(sims.mean()), float(sims.std()), float(sims.min())))
    pairs = []
    names = [n for n in embs if embs[n]]
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            pairs.append({"a": names[i], "b": names[j], "seam": seam(embs[names[i]], embs[names[j]])})
    return {
        "backend": embedder.name,
        "reference": os.path.basename(reference) if reference else None,
        "clips": [c.__dict__ for c in clips],
        "pairs": pairs,
    }
