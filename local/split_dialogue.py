#!/usr/bin/env python3
"""Split a dialogue recording into one track per speaker for multi-speaker InfiniteTalk.

    python local/split_dialogue.py dialogue.wav turns.json out_dir

``turns.json``: [{"speaker": "lena", "start": 0.0, "end": 1.68}, ...] (seconds). Most TTS
dialogue APIs return such segments with the audio; any aligner works too.

Writes ``<out_dir>/<speaker>.wav`` for every speaker: the same length as the dialogue, the
speaker's own turns in place and SILENCE everywhere else, with 15 ms fades at the cuts. That
is what the multi-speaker model needs: audio_1 drives speaker 1's mouth and only speaker 1's,
so the listener keeps a closed mouth while the other one talks. The final clip is muxed
with the original dialogue, not with these tracks.
"""
import json
import os
import sys
import wave

import numpy as np

FADE_S = 0.015


def read_wav(path):
    with wave.open(path) as w:
        if w.getsampwidth() != 2:
            raise SystemExit("expected 16-bit PCM wav")
        rate, ch = w.getframerate(), w.getnchannels()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32)
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    return x, rate


def write_wav(path, x, rate):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(np.clip(x, -32768, 32767).astype("<i2").tobytes())


def split(x: np.ndarray, rate: int, turns: list) -> dict:
    tracks = {}
    fade = int(rate * FADE_S)
    for t in turns:
        tr = tracks.setdefault(t["speaker"], np.zeros_like(x))
        a, b = int(t["start"] * rate), min(int(t["end"] * rate), len(x))
        if b <= a:
            continue
        seg = x[a:b].copy()
        if len(seg) > 2 * fade:
            seg[:fade] *= np.linspace(0, 1, fade)
            seg[-fade:] *= np.linspace(1, 0, fade)
        tr[a:b] = seg
    return tracks


def main():
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    src, turns_path, out = sys.argv[1:]
    x, rate = read_wav(src)
    with open(turns_path, encoding="utf-8") as f:
        turns = json.load(f)
    os.makedirs(out, exist_ok=True)
    for speaker, tr in split(x, rate, turns).items():
        p = os.path.join(out, f"{speaker}.wav")
        write_wav(p, tr, rate)
        talk = float((np.abs(tr) > 0).mean())
        print(f"{p}: {len(tr) / rate:.2f} s, speaking {talk:.0%} of the time")


if __name__ == "__main__":
    main()
