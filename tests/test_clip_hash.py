"""The Python and JavaScript clip hashes must agree bit for bit: the lesson finds clips by them."""
import json
import os
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "prerender"))

from clipcache import hash_bytes, hash_text  # noqa: E402

SAMPLES = ["", "a", "Привет! Я Лена.", "Тема урока: древнейшие люди.", "emoji \U0001F600 and ё", "x" * 500]


def test_known_values():
    assert hash_text("") == "00001505"
    assert hash_bytes(b"") == "00001505"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not on PATH")
def test_python_matches_javascript(tmp_path):
    data = tmp_path / "samples.json"
    data.write_text(json.dumps(SAMPLES), encoding="utf-8")
    js = (
        "import { hashText } from './prerender/clip-cache.mjs';"
        "import fs from 'node:fs';"
        f"const s = JSON.parse(fs.readFileSync({json.dumps(str(data))}, 'utf8'));"
        "console.log(JSON.stringify(s.map(hashText)));"
    )
    out = subprocess.run(["node", "--input-type=module", "-e", js], cwd=ROOT, capture_output=True,
                         text=True, encoding="utf-8", check=True).stdout
    assert json.loads(out) == [hash_text(s) for s in SAMPLES]
