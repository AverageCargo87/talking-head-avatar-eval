"""Identity seam arithmetic, with the toy pixel embedding on synthetic faces.

The pixel backend has no idea of identity beyond pixels; these tests check the seam logic
(mean embeddings, pairwise cosine, reference similarity), not face recognition.
"""
import cv2
import numpy as np
import pytest

from avatar_metrics.identity import PixelEmbedder, identity_report, make_embedder, seam, unit
from avatar_metrics.synth import STYLES, draw_face

BOX = (98, 89, 163, 193)   # covers the default and the slightly larger "redrawn" head


def report(synth, names, reference=None):
    emb = PixelEmbedder(face_box=BOX)
    return identity_report(emb, [synth[n].path for n in names], reference=reference)


def pair(rep, a, b):
    for p in rep["pairs"]:
        if {p["a"], p["b"]} == {a, b}:
            return p["seam"]
    raise KeyError((a, b))


def test_same_face_two_engines_has_no_seam(synth):
    rep = report(synth, ["coupled", "loop-patch"])
    assert pair(rep, "coupled.mp4", "loop-patch.mp4") > 0.95


def test_redrawn_face_sits_between_same_and_different(synth):
    rep = report(synth, ["coupled", "coupled-redrawn", "coupled-oleg"])
    same_vs_redrawn = pair(rep, "coupled.mp4", "coupled-redrawn.mp4")
    same_vs_other = pair(rep, "coupled.mp4", "coupled-oleg.mp4")
    assert same_vs_other < same_vs_redrawn < 0.99


def test_reference_similarity_and_spread(synth, tmp_path):
    ref = tmp_path / "ref.png"
    cv2.imwrite(str(ref), draw_face(STYLES["anya"]))
    rep = report(synth, ["coupled", "coupled-oleg"], reference=str(ref))
    clips = {c["file"]: c for c in rep["clips"]}
    assert clips["coupled.mp4"]["to_reference"] > clips["coupled-oleg.mp4"]["to_reference"]
    assert clips["coupled.mp4"]["spread"] < 0.1
    assert clips["coupled.mp4"]["frames_with_face"] == 12


def test_seam_is_cosine_of_mean_embeddings_not_difference_of_similarities():
    # two different faces that are EQUALLY far from a reference still have a seam
    ref = unit(np.array([1.0, 0.0, 0.0]))
    a = unit(np.array([0.8, 0.6, 0.0]))
    b = unit(np.array([0.8, -0.6, 0.0]))
    assert float(ref @ a) == pytest.approx(float(ref @ b))
    assert seam([a], [b]) < 0.3


def test_unknown_backend_is_rejected():
    with pytest.raises(ValueError):
        make_embedder("nope")
