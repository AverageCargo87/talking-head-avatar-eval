"""Offline checks for the local GPU tooling: graph building, dumped workflows, dialogue split."""
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "local"))

import comfy_infinitetalk as ct  # noqa: E402
from split_dialogue import split  # noqa: E402


def links(graph):
    for nid, node in graph.items():
        for v in node["inputs"].values():
            if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str):
                yield nid, v[0]


def test_single_host_graph_is_closed_and_uses_the_single_model():
    a = ct.parse_args(["--img", "a.png", "--audio", "a.wav", "--name", "x"])
    g = ct.build_graph(a, "out/x")
    assert all(src in g for _, src in links(g))
    assert g["1"]["inputs"]["model"] == ct.SINGLE
    assert g["14"]["inputs"]["cfg"] == 1.0 and g["14"]["inputs"]["steps"] == 6
    assert "audio_2" not in g["11"]["inputs"]


def test_two_hosts_graph_wires_second_voice_and_masks():
    a = ct.parse_args(["--img", "b.png", "--audio", "l.wav", "--audio2", "r.wav", "--name", "y",
                       "--masks", "m1.png,m2.png,bg.png"])
    g = ct.build_graph(a, "out/y")
    assert g["1"]["inputs"]["model"] == ct.MULTI
    assert g["11"]["inputs"]["audio_2"] == ["17", 0]
    assert g["11"]["inputs"]["ref_target_masks"] == ["30", 0]
    assert set(g["30"]["inputs"]) == {"masks.mask0", "masks.mask1", "masks.mask2"}
    assert all(src in g for _, src in links(g))


def test_committed_workflows_match_the_builder():
    cases = {
        "infinitetalk_single.api.json": ["--img", "host-640.png", "--audio", "host-voice.wav", "--w", "640",
                                         "--h", "640", "--name", "host", "--out-dir", "out"],
        "infinitetalk_two_hosts.api.json": ["--img", "two-hosts-832x480.png", "--audio", "speaker1-track.wav",
                                            "--audio2", "speaker2-track.wav", "--mix", "dialogue.wav", "--masks",
                                            "mask-speaker1.png,mask-speaker2.png,mask-background.png", "--w", "832",
                                            "--h", "480", "--audio-scale", "0.75", "--name", "two-hosts", "--out-dir", "out"],
    }
    for fname, argv in cases.items():
        a = ct.parse_args(argv)
        built = ct.build_graph(a, os.path.join(a.out_dir, a.name))
        with open(os.path.join(ROOT, "local", "workflows", fname), encoding="utf-8") as f:
            assert json.load(f) == built, fname


def test_split_dialogue_silences_the_other_speaker():
    rate = 1000
    x = np.ones(3000, dtype=np.float32) * 1000
    turns = [{"speaker": "a", "start": 0.0, "end": 1.0}, {"speaker": "b", "start": 1.0, "end": 3.0}]
    tr = split(x, rate, turns)
    assert set(tr) == {"a", "b"}
    assert len(tr["a"]) == len(x)
    assert np.all(tr["a"][1100:] == 0) and np.all(tr["b"][:990] == 0)
    assert tr["a"][500] == 1000 and tr["b"][2000] == 1000
    assert tr["a"][0] == 0                     # faded in
