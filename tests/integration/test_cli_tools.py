from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import arc_action_cli
import arc_get_state
import arc_repl_cli
import harness


class _FakeStdin(io.StringIO):
    def __init__(self, text: str, *, is_tty: bool = False):
        super().__init__(text)
        self._is_tty = is_tty

    def isatty(self) -> bool:  # pragma: no cover - simple passthrough
        return self._is_tty


def test_arc_action_cli_main_builds_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def fake_run(payload):
        captured["payload"] = payload
        return 0

    monkeypatch.setattr(arc_action_cli, "_run", fake_run)
    monkeypatch.setattr(arc_action_cli.sys, "argv", ["arc_action", "status", "--game-id", "ls20"])
    rc = arc_action_cli.main()
    assert rc == 0
    assert captured["payload"] == {"action": "status", "game_id": "ls20"}


def test_arc_action_cli_run_writes_stdout_stderr(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(
        arc_action_cli.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="o", stderr="e"),
    )
    rc = arc_action_cli._run({"action": "status"})
    assert rc == 0
    captured = capsys.readouterr()
    assert "o" in captured.out
    assert "e" in captured.err


def test_arc_action_cli_run_script_requires_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(arc_action_cli.sys, "argv", ["arc_action", "run_script"])
    monkeypatch.setattr(arc_action_cli.sys, "stdin", _FakeStdin("", is_tty=True))
    rc = arc_action_cli.main()
    assert rc == 2


def test_arc_repl_cli_exec_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def fake_run(payload):
        captured["payload"] = payload
        return 0

    monkeypatch.setattr(arc_repl_cli, "_run", fake_run)
    monkeypatch.setattr(arc_repl_cli.sys, "argv", ["arc_repl", "exec", "--game-id", "ls20"])
    monkeypatch.setattr(arc_repl_cli.sys, "stdin", _FakeStdin("print('ok')\n", is_tty=False))
    rc = arc_repl_cli.main()
    assert rc == 0
    assert captured["payload"]["action"] == "exec"
    assert captured["payload"]["game_id"] == "ls20"
    assert "print('ok')" in captured["payload"]["script"]


def test_arc_repl_cli_enable_history_functions_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def fake_run(payload):
        captured["payload"] = payload
        return 0

    monkeypatch.setattr(arc_repl_cli, "_run", fake_run)
    monkeypatch.setattr(
        arc_repl_cli.sys,
        "argv",
        ["arc_repl", "--enable-history-functions", "status", "--game-id", "ls20"],
    )
    rc = arc_repl_cli.main()
    assert rc == 0
    assert captured["payload"]["action"] == "status"
    assert captured["payload"]["game_id"] == "ls20"
    assert captured["payload"]["enable_history_functions"] is True


def test_arc_repl_cli_exec_file_payload(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured = {}
    script_path = tmp_path / "script.py"
    script_path.write_text("print('from file')\n")

    def fake_run(payload):
        captured["payload"] = payload
        return 0

    monkeypatch.setattr(arc_repl_cli, "_run", fake_run)
    monkeypatch.setattr(
        arc_repl_cli.sys,
        "argv",
        ["arc_repl", "exec_file", "--game-id", "ls20", str(script_path)],
    )
    rc = arc_repl_cli.main()
    assert rc == 0
    assert captured["payload"]["action"] == "exec"
    assert captured["payload"]["game_id"] == "ls20"
    assert "from file" in captured["payload"]["script"]


def test_arc_repl_cli_exec_file_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        arc_repl_cli.sys,
        "argv",
        ["arc_repl", "exec_file", "missing_script.py"],
    )
    rc = arc_repl_cli.main()
    assert rc == 2


def test_arc_repl_cli_run_writes_stdout_stderr(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(
        arc_repl_cli.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="o", stderr="e"),
    )
    rc = arc_repl_cli._run({"action": "status"})
    assert rc == 0
    captured = capsys.readouterr()
    assert "o" in captured.out
    assert "e" in captured.err


def test_arc_get_state_main_reads_state_and_grid(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    arc_dir = tmp_path / "arc"
    arc_dir.mkdir()
    (arc_dir / "state.json").write_text(json.dumps({"game_id": "ls20", "state": "NOT_FINISHED"}))
    np.save(arc_dir / "current_grid.npy", np.array([[0, 1], [10, 15]], dtype=np.int8))

    monkeypatch.setenv("ARC_STATE_DIR", str(arc_dir))
    monkeypatch.setattr(arc_get_state.sys, "argv", ["arc_get_state"])
    rc = arc_get_state.main()
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert out["grid_hex_rows"] == ["01", "AF"]


def test_run_super_strips_output_in_stream_mode(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    captured = {}

    def fake_stream(cmd, output_path, *, cwd="", env=None):
        captured["cmd"] = cmd
        captured["out"] = output_path
        return "assistant"

    monkeypatch.setattr(harness, "_run_super_streaming", fake_stream)
    result = harness.run_super(
        ["resume", "x", "--output", str(tmp_path / "s.md")],
        stream=True,
        cwd=tmp_path,
    )
    assert result == "assistant"
    assert "--output" not in captured["cmd"]
    assert captured["out"] == tmp_path / "s.md"


def test_cleanup_orphan_repl_daemons_kills_stale(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runs = tmp_path / "runs" / "r1" / "supervisor" / "arc" / "repl-sessions" / "c1"
    runs.mkdir(parents=True)
    (runs / "daemon.pid").write_text("12345\n")

    monkeypatch.setattr(harness, "_collect_active_run_ids", lambda _p: set())
    monkeypatch.setattr(harness, "_read_pid_cmdline", lambda _pid: "python arc_repl.py --daemon")
    monkeypatch.setattr(harness, "_terminate_pid", lambda _pid, timeout_s=1.5: True)

    stats = harness.cleanup_orphan_repl_daemons(tmp_path)
    assert stats["killed"] == 1
