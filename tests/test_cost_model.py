"""The cost model must reproduce the estimates quoted in docs/COST_MODEL.md."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from cost_model import model  # noqa: E402


def test_quoted_estimates():
    m = model(90.0)
    assert m["live_lesson_rub"] == pytest.approx((432, 538), abs=0.5)
    assert m["prerender_once_rub"][1] == pytest.approx(203, abs=0.5)      # "~200 RUB once"
    assert 25 <= m["live_answers_rub"][0] and m["live_answers_rub"][1] <= 35   # "~30 RUB per student"
