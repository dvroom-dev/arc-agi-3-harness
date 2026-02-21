from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import harness


def test_parse_args_defaults(monkeypatch) -> None:
    monkeypatch.setattr(
        harness.sys,
        "argv",
        ["harness.py"],
    )
    args = harness.parse_args()
    assert args.game_id == "ls20"
    assert args.operation_mode == "NORMAL"


def test_load_history_events_and_errors(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    path.write_text(json.dumps({"events": [{"kind": "step"}]}))
    assert harness.load_history_events(path) == [{"kind": "step"}]
    path.write_text("not json")
    try:
        harness.load_history_events(path)
    except RuntimeError as exc:
        assert "Failed to parse history JSON" in str(exc)


def test_collect_active_run_ids(monkeypatch) -> None:
    out = "\n".join(
        [
            "python harness.py --session-name abc",
            "/tmp/x/runs/def/supervisor/arc",
            "node run-config.ts /runs/ghi/agent",
        ]
    )
    monkeypatch.setattr(
        harness.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout=out),
    )
    ids = harness._collect_active_run_ids(Path("."))
    assert {"abc", "ghi"} <= ids


def test_pid_helpers(monkeypatch, tmp_path: Path) -> None:
    calls = {"count": 0}

    def fake_kill(pid, sig):
        calls["count"] += 1
        if sig == 0 and calls["count"] > 1:
            raise OSError("gone")

    monkeypatch.setattr(harness.os, "kill", fake_kill)
    assert harness._pid_exists(1) is True
    assert harness._terminate_pid(1, timeout_s=0.01) is True

    def fake_read_bytes(self):
        if str(self) == "/proc/123/cmdline":
            return b"python\x00arc_repl.py\x00--daemon\x00"
        raise FileNotFoundError(str(self))

    monkeypatch.setattr(harness.Path, "read_bytes", fake_read_bytes, raising=False)
    assert "arc_repl.py" in harness._read_pid_cmdline(123)
