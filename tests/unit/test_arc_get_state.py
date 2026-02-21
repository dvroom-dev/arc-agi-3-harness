from __future__ import annotations

import json
from pathlib import Path

import numpy as np

import arc_get_state


def _run_main(monkeypatch, argv):
    monkeypatch.setattr(arc_get_state.sys, "argv", argv)
    return arc_get_state.main()


def test_missing_state_dir(monkeypatch, capsys) -> None:
    monkeypatch.delenv("ARC_STATE_DIR", raising=False)
    rc = _run_main(monkeypatch, ["arc_get_state"])
    assert rc == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["error"]["type"] == "missing_state_dir"


def test_missing_state_file(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setenv("ARC_STATE_DIR", str(tmp_path))
    rc = _run_main(monkeypatch, ["arc_get_state"])
    assert rc == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["type"] == "missing_state"


def test_invalid_state_json(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setenv("ARC_STATE_DIR", str(tmp_path))
    (tmp_path / "state.json").write_text("{")
    rc = _run_main(monkeypatch, ["arc_get_state"])
    assert rc == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["type"] == "invalid_state_json"


def test_missing_grid(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setenv("ARC_STATE_DIR", str(tmp_path))
    (tmp_path / "state.json").write_text(json.dumps({"state": "NOT_FINISHED"}))
    rc = _run_main(monkeypatch, ["arc_get_state"])
    assert rc == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["type"] == "missing_grid"


def test_invalid_grid_file(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setenv("ARC_STATE_DIR", str(tmp_path))
    (tmp_path / "state.json").write_text(json.dumps({"state": "NOT_FINISHED"}))
    (tmp_path / "current_grid.npy").write_text("not npy")
    rc = _run_main(monkeypatch, ["arc_get_state"])
    assert rc == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["type"] == "invalid_grid_file"


def test_no_grid_option(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setenv("ARC_STATE_DIR", str(tmp_path))
    (tmp_path / "state.json").write_text(json.dumps({"state": "NOT_FINISHED"}))
    np.save(tmp_path / "current_grid.npy", np.zeros((2, 2), dtype=np.int8))
    rc = _run_main(monkeypatch, ["arc_get_state", "--no-grid"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert "grid_hex_rows" not in payload

