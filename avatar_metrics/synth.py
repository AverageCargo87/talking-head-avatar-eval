"""Synthetic talking faces with KNOWN ground truth, so every metric can be verified offline.

No real face is involved: a flat cartoon head is drawn with OpenCV, driven by a synthetic
"speech" envelope, and muxed with a matching synthetic audio track by ffmpeg. Because we
choose how each part of the face is driven, we know what every metric must report:

``still``         nothing moves; audio plays (the "still portrait + audio" control)
``static_patch``  only the mouth moves, on a frozen base (a lip-sync patch on a photo)
``loop_patch``    the mouth follows speech, while brows, blinks and a slight head sway come
                  from an idle loop that ignores the speech (a "mouth patch on a looped base")
``coupled``       the whole face is driven by speech: mouth, brows, eyes and a small nod
                  (what a generative engine does)

``delay_frames`` shifts the mouth relative to the audio: ``+N`` means the picture lags the
sound by N frames, ``-N`` means it leads.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import wave
from dataclasses import asdict, dataclass, field
from typing import Dict, Optional, Tuple

import cv2
import numpy as np

from .video import require_ffmpeg

WIDTH, HEIGHT = 360, 400
SAMPLE_RATE = 16000
SHIFT = 4                      # cv2 drawing sub-pixel precision: coordinates in 1/16 px
SCALE = 1 << SHIFT
KINDS = ("still", "static_patch", "loop_patch", "coupled")


@dataclass
class FaceStyle:
    skin: Tuple[int, int, int] = (153, 190, 232)       # BGR
    hair: Tuple[int, int, int] = (42, 58, 91)
    cloth: Tuple[int, int, int] = (124, 104, 70)
    background: Tuple[int, int, int] = (48, 36, 27)
    hair_style: str = "bob"                             # bob | short | long
    glasses: bool = False
    head_scale: float = 1.0                             # 1.0 = default head size
    eye_gap: float = 27.0                               # half distance between the eyes

    def face_box(self) -> Tuple[int, int, int, int]:
        rx, ry = 78 * self.head_scale, 92 * self.head_scale
        return int(180 - rx), int(186 - ry), int(2 * rx), int(2 * ry)


STYLES: Dict[str, FaceStyle] = {
    "anya": FaceStyle(),
    # the same person redrawn by another engine: slightly different proportions
    "anya_redrawn": FaceStyle(head_scale=1.05, eye_gap=30.0, skin=(146, 184, 226)),
    "oleg": FaceStyle(skin=(164, 192, 227), hair=(190, 196, 200), cloth=(51, 82, 107),
                      background=(24, 34, 38), hair_style="short", glasses=True),
    "zarina": FaceStyle(skin=(88, 128, 185), hair=(32, 26, 31), cloth=(74, 59, 122),
                        background=(38, 30, 36), hair_style="long"),
}


@dataclass
class Clip:
    path: str
    kind: str
    style: str
    seconds: float
    fps: int
    delay_frames: int
    seed: int
    face_box: Tuple[int, int, int, int]
    extra: Dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        d = asdict(self)
        d["face_box"] = list(self.face_box)
        return d


# ---------------------------------------------------------------- speech signal


def speech_envelope(seconds: float, seed: int = 0, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Syllable-like loudness envelope in [0, 1] at audio rate.

    Words of 2-5 syllables (raised-cosine bumps of 110-240 ms with random loudness),
    separated by 150-450 ms pauses. Starts and ends with silence.
    """
    rng = np.random.default_rng(seed)
    n = int(seconds * sample_rate)
    env = np.zeros(n, dtype=np.float64)
    t = 0.35
    while t < seconds - 0.6:
        for _ in range(int(rng.integers(2, 6))):
            dur = float(rng.uniform(0.11, 0.24))
            amp = float(rng.uniform(0.45, 1.0))
            a, b = int(t * sample_rate), int(min(seconds, t + dur) * sample_rate)
            if b <= a:
                break
            bump = 0.5 - 0.5 * np.cos(np.linspace(0, 2 * np.pi, b - a))
            env[a:b] = np.maximum(env[a:b], amp * bump)
            t += dur * float(rng.uniform(0.85, 1.05))
        t += float(rng.uniform(0.15, 0.45))
    return env


def frame_envelope(env: np.ndarray, fps: int, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    step = sample_rate / fps
    frames = int(len(env) / step)
    out = np.array([env[int(i * step):int((i + 1) * step)].mean() for i in range(frames)])
    peak = out.max()
    return out / peak if peak > 0 else out


def speech_audio(env: np.ndarray, seed: int = 0, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """A buzzy voiced carrier (f0 about 140 Hz with vibrato) amplitude-modulated by ``env``."""
    rng = np.random.default_rng(seed + 1000)
    t = np.arange(len(env)) / sample_rate
    f0 = 140 + 12 * np.sin(2 * np.pi * 0.7 * t)
    phase = 2 * np.pi * np.cumsum(f0) / sample_rate
    carrier = sum(np.sin(k * phase) / k for k in range(1, 9))
    carrier = carrier / np.abs(carrier).max()
    noise = rng.normal(0, 0.08, len(env))
    sig = env * (0.9 * carrier + noise)
    return np.clip(sig * 0.6 * 32767, -32768, 32767).astype("<i2")


def shift_frames(x: np.ndarray, delay: int) -> np.ndarray:
    """``out[t] = x[t - delay]`` with zero padding (mouth closed outside the signal)."""
    if delay == 0:
        return x.copy()
    out = np.zeros_like(x)
    if delay > 0:
        out[delay:] = x[:-delay]
    else:
        out[:delay] = x[-delay:]
    return out


def smooth(x: np.ndarray, k: int = 3) -> np.ndarray:
    if k <= 1:
        return x
    kernel = np.ones(k) / k
    return np.convolve(x, kernel, mode="same")


# ---------------------------------------------------------------- drawing


def _p(x: float, y: float) -> Tuple[int, int]:
    return int(round(x * SCALE)), int(round(y * SCALE))


def _ellipse(img, cx, cy, rx, ry, color, thickness=-1):
    cv2.ellipse(img, _p(cx, cy), _p(max(rx, 0.1), max(ry, 0.1)), 0, 0, 360, color, thickness,
                cv2.LINE_AA, SHIFT)


def _line(img, x1, y1, x2, y2, color, thickness):
    cv2.line(img, _p(x1, y1), _p(x2, y2), color, thickness, cv2.LINE_AA, SHIFT)


def _darker(c, k):
    return tuple(int(v * k) for v in c)


def draw_face(style: FaceStyle, mouth_open: float = 0.0, brow_raise: float = 0.0,
              eye_open: float = 1.0, head_dx: float = 0.0, head_dy: float = 0.0) -> np.ndarray:
    """One BGR frame. All arguments are continuous, so motion is sub-pixel smooth."""
    img = np.zeros((HEIGHT, WIDTH, 3), np.uint8)
    img[:] = style.background
    s = style.head_scale
    cx, cy = 180 + head_dx, 186 + head_dy
    if style.hair_style == "long":
        _ellipse(img, cx, cy + 24 * s, 104 * s, 150 * s, _darker(style.hair, 0.92))
    _ellipse(img, 180 + head_dx * 0.5, 470, 140, 165, style.cloth)                 # shoulders
    _ellipse(img, cx, cy + 86 * s, 22 * s, 34 * s, _darker(style.skin, 0.88))         # neck
    _ellipse(img, cx, cy, 78 * s, 92 * s, style.skin)                                 # head
    _ellipse(img, cx - 76 * s, cy + 6 * s, 12 * s, 16 * s, style.skin)                # ears
    _ellipse(img, cx + 76 * s, cy + 6 * s, 12 * s, 16 * s, style.skin)
    # hair
    top = cy - 36 * s
    if style.hair_style == "short":
        cv2.ellipse(img, _p(cx, top + 6 * s), _p(80 * s, 64 * s), 0, 180, 360, style.hair, -1, cv2.LINE_AA, SHIFT)
    else:
        cv2.ellipse(img, _p(cx, top), _p(82 * s, 74 * s), 0, 180, 360, style.hair, -1, cv2.LINE_AA, SHIFT)
        for side in (-1, 1):
            x0 = cx + side * 70 * s
            _ellipse(img, x0, cy - 4 * s, 13 * s, 46 * s if style.hair_style == "bob" else 64 * s, style.hair)
    # brows: raised by up to 9 px
    by = cy - 36 * s - 9 * brow_raise
    g = style.eye_gap * s
    _line(img, cx - g - 17 * s, by + 2, cx - g + 17 * s, by - 2, _darker(style.hair, 0.8), 6)
    _line(img, cx + g - 17 * s, by - 2, cx + g + 17 * s, by + 2, _darker(style.hair, 0.8), 6)
    # eyes
    ey = cy - 10 * s
    for ex in (cx - g, cx + g):
        if eye_open < 0.25:
            _line(img, ex - 15 * s, ey, ex + 15 * s, ey, (40, 46, 58), 4)
        else:
            _ellipse(img, ex, ey, 15 * s, 12 * s * eye_open, (255, 255, 255))
            _ellipse(img, ex + 2, ey, 6.5 * s, 6.5 * s * min(1.0, eye_open + 0.2), (61, 49, 38))
    if style.glasses:
        for ex in (cx - g, cx + g):
            _ellipse(img, ex, ey, 26 * s, 21 * s, (49, 43, 43), 3)
        _line(img, cx - g + 26 * s, ey - 2, cx + g - 26 * s, ey - 2, (49, 43, 43), 3)
    # nose
    _line(img, cx + 1, cy - 4 * s, cx - 5 * s, cy + 22 * s, _darker(style.skin, 0.78), 4)
    # mouth: from closed lips to a wide-open "a"
    k = float(np.clip(mouth_open, 0, 1))
    mw, mh = (44 + 12 * k) * s, (5 + 30 * k) * s
    my = cy + 46 * s + mh * 0.18
    _ellipse(img, cx, my, mw / 2, mh / 2, (48, 38, 122))
    if k > 0.25:
        _ellipse(img, cx, my - mh * 0.28, mw / 2 - 5, min(7.0, mh * 0.18), (230, 237, 244))
    if k > 0.55:
        _ellipse(img, cx, my + mh * 0.30, mw / 2 - 9, mh * 0.20, (83, 70, 184))
    return img


# ---------------------------------------------------------------- driving signals


def blinks(n: int, fps: int, seed: int, period_s: float = 3.2) -> np.ndarray:
    """Eye openness with a 3-frame blink every ``period_s`` seconds (random phase)."""
    rng = np.random.default_rng(seed + 7)
    eye = np.ones(n)
    period = int(period_s * fps)
    for b0 in range(int(rng.integers(0, period)), n, period):
        eye[b0:b0 + 3] = 0.0
    return eye


def drive(kind: str, env_frames: np.ndarray, fps: int, delay_frames: int, seed: int) -> Dict[str, np.ndarray]:
    n = len(env_frames)
    t = np.arange(n) / fps
    mouth = shift_frames(env_frames, delay_frames)
    zeros = np.zeros(n)
    ones = np.ones(n)
    if kind == "still":
        return dict(mouth=zeros, brow=zeros, eye=ones, dx=zeros, dy=zeros)
    if kind == "static_patch":
        return dict(mouth=mouth, brow=zeros, eye=ones, dx=zeros, dy=zeros)
    if kind == "loop_patch":
        rng = np.random.default_rng(seed + 7)
        brow = 0.35 + 0.35 * np.sin(2 * np.pi * t / 2.7 + rng.uniform(0, 6))
        eye = blinks(n, fps, seed)
        dx = 1.2 * np.sin(2 * np.pi * t / 4.1)
        return dict(mouth=mouth, brow=brow, eye=eye, dx=dx, dy=zeros)
    if kind == "coupled":
        # brows lift, eyes narrow and the head dips slightly on every stressed syllable;
        # blinks stay independent of speech, as they are in a real face
        brow = 0.9 * mouth
        eye = np.minimum(1.0 - 0.35 * mouth, blinks(n, fps, seed))
        dy = 2.5 * mouth
        return dict(mouth=mouth, brow=brow, eye=eye, dx=zeros, dy=dy)
    raise ValueError(f"unknown kind {kind!r}; expected one of {KINDS}")


# ---------------------------------------------------------------- writing


def write_wav(path: str, samples: np.ndarray, sample_rate: int = SAMPLE_RATE) -> None:
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(samples.tobytes())


def make_clip(path: str, kind: str = "coupled", style: str = "anya", seconds: float = 8.0,
              fps: int = 25, delay_frames: int = 0, seed: int = 0, crf: int = 18,
              with_audio: bool = True) -> Clip:
    """Render one synthetic clip to ``path`` (H.264 + AAC) and return its ground truth."""
    st = STYLES[style]
    env = speech_envelope(seconds, seed)
    env_frames = frame_envelope(env, fps)
    sig = drive(kind, env_frames, fps, delay_frames, seed)
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        wav = os.path.join(td, "voice.wav")
        write_wav(wav, speech_audio(env, seed))
        cmd = [require_ffmpeg(), "-y", "-v", "error",
               "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{WIDTH}x{HEIGHT}", "-r", str(fps), "-i", "pipe:0"]
        if with_audio:
            cmd += ["-i", wav, "-c:a", "aac", "-b:a", "96k", "-shortest"]
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), "-pix_fmt", "yuv420p",
                "-map_metadata", "-1", path]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        for i in range(len(env_frames)):
            frame = draw_face(st, mouth_open=sig["mouth"][i], brow_raise=sig["brow"][i],
                              eye_open=sig["eye"][i], head_dx=sig["dx"][i], head_dy=sig["dy"][i])
            proc.stdin.write(frame.tobytes())
        proc.stdin.close()
        err = proc.stderr.read().decode(errors="replace")
        if proc.wait() != 0:
            raise RuntimeError(f"ffmpeg failed: {err[-500:]}")
    return Clip(path=path, kind=kind, style=style, seconds=seconds, fps=fps,
                delay_frames=delay_frames, seed=seed, face_box=st.face_box())


DEFAULT_SET = [
    # name, kind, style, delay_frames
    ("still", "still", "anya", 0),
    ("static-patch", "static_patch", "anya", 0),
    ("loop-patch", "loop_patch", "anya", 0),
    ("coupled", "coupled", "anya", 0),
    ("coupled-lag3", "coupled", "anya", 3),
    ("coupled-lead2", "coupled", "anya", -2),
    ("coupled-redrawn", "coupled", "anya_redrawn", 0),
    ("coupled-oleg", "coupled", "oleg", 0),
]


def make_set(out_dir: str, seconds: float = 8.0, seed: int = 3, names: Optional[list] = None) -> Dict[str, Clip]:
    """Render the default synthetic set and write ``manifest.json`` next to it."""
    os.makedirs(out_dir, exist_ok=True)
    clips = {}
    for name, kind, style, delay in DEFAULT_SET:
        if names and name not in names:
            continue
        clips[name] = make_clip(os.path.join(out_dir, f"{name}.mp4"), kind=kind, style=style,
                                seconds=seconds, delay_frames=delay, seed=seed)
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({k: {**v.as_dict(), "path": os.path.basename(v.path)} for k, v in clips.items()}, f, indent=1)
    return clips
