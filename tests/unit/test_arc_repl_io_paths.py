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

    class Conn:
        def send(self, msg):
            return None

        def recv(self):
            return {"ok": True}

        def close(self):
            return None

    calls = {"n": 0}

    def fake_client(path, family=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("not ready")
        return Conn()

    sock.write_text("x")
    monkeypatch.setattr(arc_repl.multiprocessing.connection, "Client", fake_client)
    arc_repl._wait_for_daemon(tmp_path, "c1", timeout_s=0.2)


def test_wait_for_daemon_permission_error_raises(monkeypatch, tmp_path: Path) -> None:
    sock = tmp_path / "sock"
    sock.write_text("x")
    monkeypatch.setattr(arc_repl, "_socket_path", lambda cwd, cid: sock)
    monkeypatch.setattr(
        arc_repl.multiprocessing.connection,
        "Client",
        lambda *a, **k: (_ for _ in ()).throw(PermissionError(1, "Operation not permitted")),
    )
    with pytest.raises(PermissionError):
        arc_repl._wait_for_daemon(tmp_path, "c1", timeout_s=0.2)


def test_send_request_spawns_when_first_send_fails(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(arc_repl, "_default_game_id", lambda cwd: "ls20")
    monkeypatch.setattr(arc_repl, "_spawn_daemon", lambda *a, **k: None)
    monkeypatch.setattr(arc_repl, "_wait_for_daemon", lambda *a, **k: None)
    monkeypatch.setattr(arc_repl, "_socket_path", lambda cwd, cid: tmp_path / "sock")

    class Conn:
        def __init__(self):
            self.calls = 0

        def send(self, request):
            self.calls += 1

        def recv(self):
            return {"ok": True, "action": "status"}

        def close(self):
            return None

    state = {"n": 0}

    def fake_client(path, family=None):
        state["n"] += 1
        if state["n"] == 1:
            raise FileNotFoundError("no socket yet")
        return Conn()

    monkeypatch.setattr(arc_repl.multiprocessing.connection, "Client", fake_client)
    result, created = arc_repl._send_request(tmp_path, "c1", {"action": "status"})
    assert result["ok"] is True
    assert created is True


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
