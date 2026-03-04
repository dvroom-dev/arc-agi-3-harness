from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import arc_repl


def test_wait_for_daemon_success(monkeypatch, tmp_path: Path) -> None:
    sock = tmp_path / "sock"
    monkeypatch.setattr(arc_repl, "_socket_path", lambda cwd, cid: sock)
    monkeypatch.setattr(arc_repl.time, "sleep", lambda _t: None)

    calls = {"n": 0}
    def fake_send(*_a, **_k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("not ready")
        return {"ok": True, "action": "ping"}

    sock.write_text("x")
    monkeypatch.setattr(arc_repl, "_send_ipc_request", fake_send)
    arc_repl._wait_for_daemon(tmp_path, "c1", timeout_s=0.2)


def test_wait_for_daemon_permission_error_times_out(monkeypatch, tmp_path: Path) -> None:
    sock = tmp_path / "sock"
    sock.write_text("x")
    monkeypatch.setattr(arc_repl, "_socket_path", lambda cwd, cid: sock)
    monkeypatch.setattr(
        arc_repl,
        "_send_ipc_request",
        lambda *a, **k: (_ for _ in ()).throw(PermissionError(1, "Operation not permitted")),
    )
    with pytest.raises(RuntimeError):
        arc_repl._wait_for_daemon(tmp_path, "c1", timeout_s=0.2)


def test_send_request_spawns_when_first_send_fails(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(arc_repl, "_default_game_id", lambda cwd: "ls20")
    monkeypatch.setattr(arc_repl, "_spawn_daemon", lambda *a, **k: None)
    monkeypatch.setattr(arc_repl, "_wait_for_daemon", lambda *a, **k: None)
    monkeypatch.setattr(arc_repl, "_socket_path", lambda cwd, cid: tmp_path / "sock")

    state = {"n": 0}
    def fake_send(*_a, **_k):
        state["n"] += 1
        if state["n"] == 1:
            raise FileNotFoundError("no socket yet")
        return {"ok": True, "action": "status"}

    monkeypatch.setattr(arc_repl, "_send_ipc_request", fake_send)
    result, created = arc_repl._send_request(tmp_path, "c1", {"action": "status"})
    assert result["ok"] is True
    assert created is True


def test_send_request_refuses_recovery_after_prior_session(monkeypatch, tmp_path: Path) -> None:
    arc_dir = tmp_path / "arc"
    arc_dir.mkdir()
    monkeypatch.setenv("ARC_STATE_DIR", str(arc_dir))
    session_dir = arc_repl._session_dir(tmp_path, "c1")
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "daemon.pid").write_text("12345\n")
    (session_dir / "session.json").write_text('{"status":"running","game_id":"ls20"}\n')
    (session_dir / "daemon.lifecycle.jsonl").write_text('{"event":"spawned"}\n')
    (session_dir / "daemon.log").write_text("trace line\n")

    monkeypatch.setattr(arc_repl, "_socket_path", lambda cwd, cid: tmp_path / "missing.sock")
    monkeypatch.setattr(arc_repl, "_spawn_daemon", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not spawn")))
    monkeypatch.setattr(arc_repl, "_default_game_id", lambda cwd: "ls20")

    with pytest.raises(RuntimeError, match=r"automatic replay/recovery is disabled"):
        arc_repl._send_request(tmp_path, "c1", {"action": "status", "game_id": "ls20"})


def test_send_request_bootstraps_for_non_status(monkeypatch, tmp_path: Path) -> None:
    arc_dir = tmp_path / "arc"
    arc_dir.mkdir()
    monkeypatch.setenv("ARC_STATE_DIR", str(arc_dir))
    monkeypatch.setattr(arc_repl, "_socket_path", lambda cwd, cid: tmp_path / "missing.sock")
    spawned = {"n": 0}
    monkeypatch.setattr(
        arc_repl,
        "_spawn_daemon",
        lambda *a, **k: spawned.__setitem__("n", spawned["n"] + 1),
    )
    monkeypatch.setattr(arc_repl, "_wait_for_daemon", lambda *a, **k: None)
    monkeypatch.setattr(arc_repl, "_default_game_id", lambda cwd: "ls20")
    monkeypatch.setattr(
        arc_repl,
        "_send_ipc_request",
        lambda *a, **k: {"ok": True, "action": "reset_level"},
    )

    result, created = arc_repl._send_request(
        tmp_path, "c1", {"action": "reset_level", "game_id": "ls20"}
    )
    assert result["ok"] is True
    assert created is True
    assert spawned["n"] == 1


def test_main_exec_prints_script_stdout(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["arc_repl"])
    monkeypatch.setattr(
        arc_repl,
        "_read_args",
        lambda: {"action": "exec", "game_id": "ls20", "script": "print('x')"},
    )
    monkeypatch.setattr(
        arc_repl,
        "_send_request",
        lambda cwd, conversation_id, request: (
            {"ok": True, "action": "exec", "script_stdout": "hello\n"},
            False,
        ),
    )
    rc = arc_repl.main()
    assert rc == 0
    assert "hello" in capsys.readouterr().out


def test_main_exec_error_prints_stderr(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["arc_repl"])
    monkeypatch.setattr(
        arc_repl,
        "_read_args",
        lambda: {"action": "exec", "game_id": "ls20", "script": "print('x')"},
    )
    monkeypatch.setattr(
        arc_repl,
        "_send_request",
        lambda cwd, conversation_id, request: (
            {"ok": False, "action": "exec", "script_stdout": "", "script_error": "boom"},
            False,
        ),
    )
    rc = arc_repl.main()
    assert rc == 1
    assert "boom" in capsys.readouterr().err
