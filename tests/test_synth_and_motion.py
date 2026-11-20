import json
import os

import numpy as np
import pytest

from avatar_metrics.motion import measure_motion
from avatar_metrics.synth import STYLES, draw_face, frame_envelope, shift_frames, speech_envelope
from avatar_metrics.video import parse_box, probe


def test_speech_envelope_has_pauses_and_syllables():
    env = speech_envelope(6.0, seed=1)
    assert env.min() == 0.0 and 0.4 < env.max() <= 1.0
    frames = frame_envelope(env, 25)
    assert len(frames) == 150
    assert (frames < 0.02).mean() > 0.1          # there is silence
    assert (frames > 0.3).mean() > 0.2           # and there is speech


def test_shift_frames_semantics():
    x = np.arange(1, 6, dtype=float)
    assert list(shift_frames(x, 2)) == [0, 0, 1, 2, 3]      # picture late
    assert list(shift_frames(x, -2)) == [3, 4, 5, 0, 0]     # picture early


def test_face_box_is_inside_the_frame():
    img = draw_face(STYLES["anya"], mouth_open=1.0)
    x, y, w, h = STYLES["anya"].face_box()
    assert img.shape == (400, 360, 3)
    assert 0 <= x and 0 <= y and x + w <= 360 and y + h <= 400


def test_open_mouth_changes_the_mouth_region_only():
    a = draw_face(STYLES["anya"], mouth_open=0.0).astype(int)
    b = draw_face(STYLES["anya"], mouth_open=1.0).astype(int)
    diff = np.abs(a - b).sum(axis=2)
    ys = np.nonzero(diff)[0]
    assert ys.min() > 186            # nothing above the nose changed


def test_manifest_and_video_properties(synth):
    folder = os.path.dirname(synth["coupled"].path)
    with open(os.path.join(folder, "manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    assert manifest["coupled-lag3"]["delay_frames"] == 3
    info = probe(synth["coupled"].path)
    assert (info.width, info.height) == (360, 400) and info.fps == pytest.approx(25.0)


def test_motion_orders_still_patch_and_whole_face(synth):
    still = measure_motion(synth["still"].path).motion
    patch = measure_motion(synth["static-patch"].path).motion
    whole = measure_motion(synth["coupled"].path).motion
    assert still < 0.05 < patch < whole


def test_parse_box():
    assert parse_box("1,2,3,4") == (1, 2, 3, 4)
    assert parse_box(None) is None
    with pytest.raises(ValueError):
        parse_box("1,2,3")
    with pytest.raises(ValueError):
        parse_box("1,2,0,4")
