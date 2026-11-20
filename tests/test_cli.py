import json

from avatar_metrics.cli import main


def test_liveness_json(synth, capsys):
    c = synth["coupled"]
    main(["liveness", "--json", "--face-box", ",".join(map(str, c.face_box)), c.path])
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]["file"] == "coupled.mp4" and rows[0]["coupling"] > 0.7


def test_offset_text_report(synth, capsys):
    c = synth["coupled-lag3"]
    main(["offset", "--face-box", ",".join(map(str, c.face_box)), c.path])
    out = capsys.readouterr().out
    assert "best shift" in out and "LAGS" in out


def test_errors_are_reported_per_clip(tmp_path, capsys):
    missing = tmp_path / "missing.mp4"
    main(["liveness", "--json", str(missing)])
    rows = json.loads(capsys.readouterr().out)
    assert "error" in rows[0]


def test_identity_pixels_backend(synth, capsys):
    main(["identity", "--backend", "pixels", "--face-box", "98,89,163,193", "--json",
          synth["coupled"].path, synth["coupled-oleg"].path])
    rep = json.loads(capsys.readouterr().out)
    assert rep["backend"] == "pixels" and len(rep["pairs"]) == 1
