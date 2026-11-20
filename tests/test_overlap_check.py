import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

from overlap_check import check, normalise  # noqa: E402


def test_normalise_folds_yo_case_and_punctuation():
    assert normalise("Ёж, ЁЛКА!  ещё") == ["еж", "елка", "еще"]


def test_eight_word_run_fails_seven_passes(tmp_path):
    src = "один два три четыре пять шесть семь восемь девять десять"
    corpus = tmp_path / "book.txt"
    corpus.write_text(src, encoding="utf-8")
    lines = [
        "Вот: Один, два, три, четыре, пять, шесть, семь, восемь!",   # 8 shared words
        "один два три четыре пять шесть семь и всё",                  # only 7
    ]
    _, _, rep = check(lines, [str(corpus)], n=8)
    assert [r["pass"] for r in rep] == [False, True]
    assert rep[0]["overlaps"] == ["один два три четыре пять шесть семь восемь"]


def test_json_field_limits_the_corpus(tmp_path):
    doc = {"scenes": [{"show": "раз два три четыре пять шесть семь восемь", "note": "a b c d e f g h"}]}
    p = tmp_path / "scene.json"
    p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    _, _, rep = check(["a b c d e f g h"], [str(p)], n=8, json_field="show")
    assert rep[0]["pass"]
    _, _, rep = check(["раз два три четыре пять шесть семь восемь"], [str(p)], n=8, json_field="show")
    assert not rep[0]["pass"]
