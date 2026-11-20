"""Face liveness on synthetic clips whose ground truth we chose."""
import pytest

from avatar_metrics.liveness import STILL, measure_liveness, pearson


def live(synth, name):
    c = synth[name]
    return measure_liveness(c.path, face_box=c.face_box)


def test_static_patch_has_a_dead_upper_face(synth):
    r = live(synth, "static-patch")
    assert r.mouth > 1.0                 # the mouth clearly moves
    assert r.upper < 0.05                # nothing above it does
    assert r.ratio < 0.05
    assert abs(r.coupling) < 0.3


def test_looped_base_moves_but_is_not_coupled_to_speech(synth):
    r = live(synth, "loop-patch")
    assert r.upper > 0.2                 # blinks, brows and sway from the idle loop
    assert abs(r.coupling) < 0.3         # ... but unrelated to what the mouth does


def test_whole_face_driven_by_speech_is_coupled(synth):
    r = live(synth, "coupled")
    assert r.coupling > 0.7
    assert r.ratio > 0.3


def test_coupling_is_the_discriminator(synth):
    coupled = live(synth, "coupled").coupling
    looped = live(synth, "loop-patch").coupling
    static = live(synth, "static-patch").coupling
    assert coupled - max(looped, static) > 0.5


def test_still_face_reports_zero_instead_of_noise(synth):
    r = live(synth, "still")
    assert r.mouth < STILL and r.upper < STILL
    assert r.ratio == 0.0 and r.coupling == 0.0


def test_a_delay_does_not_change_liveness(synth):
    a, b = live(synth, "coupled"), live(synth, "coupled-lag3")
    assert abs(a.ratio - b.ratio) < 0.05
    assert abs(a.coupling - b.coupling) < 0.1


def test_given_box_is_reported_as_given(synth):
    r = live(synth, "coupled")
    assert r.face_source == "given"
    assert r.face_box == synth["coupled"].face_box


def test_pearson_guards_flat_series():
    import numpy as np
    assert pearson(np.zeros(20), np.arange(20.0)) == 0.0
    assert pearson(np.arange(20.0), np.arange(20.0)) == pytest.approx(1.0)
