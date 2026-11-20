"""Lip-sync offset: a known delay between picture and sound must be recovered."""
import numpy as np
import pytest

from avatar_metrics.offset import best_lag, lag_table, measure_offset, peak_margin, verdict


def off(synth, name):
    c = synth[name]
    return measure_offset(c.path, face_box=c.face_box)


def test_in_sync_clip_reads_zero(synth):
    r = off(synth, "coupled")
    assert abs(r.lag_frames) <= 1
    assert r.r_best > 0.5
    assert "in sync" in r.verdict


@pytest.mark.parametrize("name,expected", [("coupled-lag3", +3), ("coupled-lead2", -2)])
def test_known_delay_is_recovered(synth, name, expected):
    base = off(synth, "coupled").lag_frames
    r = off(synth, name)
    assert r.lag_frames - base == expected
    assert abs(r.lag_frames - expected) <= 1
    assert r.lag_ms == pytest.approx(r.lag_frames * 40.0)
    assert ("LAGS" if expected > 0 else "LEADS") in r.verdict


def test_still_mouth_is_not_synchronised_by_chance(synth):
    r = off(synth, "still")
    assert r.verdict.startswith("mouth does not move")
    assert r.r_best == 0.0


def test_lag_table_on_plain_arrays():
    rng = np.random.default_rng(0)
    env = np.convolve(rng.random(400), np.ones(3) / 3, mode="same")
    mouth = np.zeros_like(env)
    mouth[5:] = env[:-5]                     # picture 5 frames late
    lag, r = best_lag(lag_table(mouth, env, max_lag=20))
    assert lag == 5 and r > 0.9


def test_flat_correlation_curve_is_flagged():
    table = [(lag, 0.20 + 0.001 * lag) for lag in range(-10, 11)]
    lag, r = best_lag(table)
    m = peak_margin(table, lag)
    assert m < 0.03
    assert verdict(lag, r, 25.0, mouth_spread=3.0, margin=m).startswith("no clear peak")


def test_weak_link_verdict():
    assert verdict(0, 0.05, 25.0).startswith("no link")
