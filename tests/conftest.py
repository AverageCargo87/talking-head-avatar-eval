import os
import shutil
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

requires_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not on PATH")


@pytest.fixture(scope="session")
def synth(tmp_path_factory):
    """The default synthetic set, rendered once per test session (about 3 s)."""
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not on PATH")
    from avatar_metrics.synth import make_set
    out = tmp_path_factory.mktemp("synth")
    return make_set(str(out), seconds=8.0, seed=3)
