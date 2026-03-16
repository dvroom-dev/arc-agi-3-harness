from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import arc_repl


def test_spawn_daemon_writes_pid(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(arc_repl, "_session_dir", lambda cwd, cid: tmp_path / "s")
    monkeypatch.setattr(arc_repl, "_socket_path", lambda cwd, cid: tmp_path / "sock")
    monkeypatch.setattr(arc_repl, "_daemon_log_path", lambda cwd, cid: tmp_path / "s" / "daemon.log")
    monkeypatch.setattr(arc_repl, "_pid_path", lambda cwd, cid: tmp_path / "s" / "daemon.pid")
    monkeypatch.setattr(arc_repl, "_lifecycle_path", lambda cwd, cid: tmp_path / "s" / "daemon.lifecycle.jsonl")
    seen: dict[str, object] = {}

    def _fake_popen(*a, **k):
        seen.update(k)
        seen["argv"] = list(a[0]) if a else []
        return SimpleNamespace(pid=1234)

    monkeypatch.setattr(
        arc_repl.subprocess,
        "Popen",
        _fake_popen,
    )
    monkeypatch.setenv("ARC_REPL_PARENT_PID", "555")
    monkeypatch.setenv("ARC_REPL_PARENT_START_TICKS", "777")
    arc_repl._spawn_daemon(tmp_path, "c1", "ls20")
    assert (tmp_path / "s" / "daemon.pid").read_text().strip() == "1234"
    lifecycle = (tmp_path / "s" / "daemon.lifecycle.jsonl").read_text()
    assert '"event": "spawned"' in lifecycle
    assert seen.get("start_new_session") is True
    cmd = seen.get("argv", [])
    assert "--parent-pid" in cmd
    assert "555" in cmd
    assert "--parent-start-ticks" in cmd
    assert "777" in cmd


def test_wait_for_daemon_timeout(monkeypatch, tmp_path: Path) -> None:
    sock = tmp_path / "sock"
    monkeypatch.setattr(arc_repl, "_socket_path", lambda cwd, cid: sock)
    monkeypatch.setattr(arc_repl.time, "sleep", lambda _t: None)
    times = {"t": 0.0}

    def fake_time():
        times["t"] += 0.2
        return times["t"]

    monkeypatch.setattr(arc_repl.time, "time", fake_time)
    with pytest.raises(RuntimeError):
        arc_repl._wait_for_daemon(tmp_path, "c1", timeout_s=0.3)


def test_send_request_missing_game_id_errors(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(arc_repl, "_socket_path", lambda cwd, cid: tmp_path / "missing.sock")
    monkeypatch.setattr(arc_repl, "_default_game_id", lambda cwd: "")
    monkeypatch.setattr(arc_repl, "_spawn_daemon", lambda *a, **k: None)
    monkeypatch.setattr(arc_repl, "_wait_for_daemon", lambda *a, **k: None)
    with pytest.raises(RuntimeError):
        arc_repl._send_request(tmp_path, "c1", {"action": "status"})


def test_send_request_respawns_when_prior_session_socket_is_missing(monkeypatch, tmp_path: Path) -> None:
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    pid_file = session_dir / "daemon.pid"
    pid_file.write_text("123\n")
    meta_file = session_dir / "meta.json"
    meta_file.write_text("{}\n")
    lifecycle_file = session_dir / "daemon.lifecycle.jsonl"
    lifecycle_file.write_text("{}\n")
    log_file = session_dir / "daemon.log"
    log_file.write_text("boot\n")
    socket_file = session_dir / "daemon.ready"
    calls: list[str] = []

    monkeypatch.setattr(arc_repl, "_socket_path", lambda cwd, cid: socket_file)
    monkeypatch.setattr(arc_repl, "_session_dir", lambda cwd, cid: session_dir)
    monkeypatch.setattr(arc_repl, "_pid_path", lambda cwd, cid: pid_file)
    monkeypatch.setattr(arc_repl, "_meta_path", lambda cwd, cid: meta_file)
    monkeypatch.setattr(arc_repl, "_lifecycle_path", lambda cwd, cid: lifecycle_file)
    monkeypatch.setattr(arc_repl, "_daemon_log_path", lambda cwd, cid: log_file)
    monkeypatch.setattr(arc_repl, "_default_game_id", lambda cwd: "ls20")
    monkeypatch.setattr(arc_repl, "_append_lifecycle_event", lambda *a, **k: None)
    monkeypatch.setattr(arc_repl, "_spawn_daemon", lambda *a, **k: calls.append("spawn"))
    monkeypatch.setattr(
        arc_repl,
        "_wait_for_daemon",
        lambda *a, **k: socket_file.write_text("ready\n"),
    )
    monkeypatch.setattr(
        arc_repl,
        "_send_ipc_request",
        lambda cwd, conversation_id, request, timeout_s: {"ok": True, "action": request["action"]},
    )

    result, session_created = arc_repl._send_request(tmp_path, "c1", {"action": "status", "game_id": "ls20"})

    assert calls == ["spawn"]
    assert session_created is True
    assert result["ok"] is True


def test_daemon_main_handles_unknown_and_non_object_request(monkeypatch, tmp_path: Path) -> None:
    class FakeSession:
        def __init__(self, **kwargs):
            self.game_id = "ls20"

    called = {"ok": False}
    def fake_run_daemon(**kwargs):
        called["ok"] = True
        session = kwargs["make_session"]()
        assert session.game_id == "ls20"
        return 0
    monkeypatch.setattr(arc_repl, "ReplSession", FakeSession)
    monkeypatch.setattr(arc_repl, "run_daemon", fake_run_daemon)
    monkeypatch.setattr(arc_repl, "_arc_dir", lambda cwd: tmp_path / "arc")
    monkeypatch.setattr(arc_repl, "_session_dir", lambda cwd, cid: tmp_path / "arc" / "repl-sessions" / cid)
    monkeypatch.setattr(arc_repl, "_socket_path", lambda cwd, cid: tmp_path / "arc" / "sock")
    monkeypatch.setattr(arc_repl, "_meta_path", lambda cwd, cid: tmp_path / "arc" / "meta.json")
    rc = arc_repl._daemon_main(tmp_path, "c1", "ls20")
    assert rc == 0
    assert called["ok"] is True


def test_main_daemon_mode_exception(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["arc_repl", "--daemon", "--cwd", ".", "--conversation-id", "c1", "--game-id", "ls20"])
    monkeypatch.setattr(arc_repl, "_daemon_main", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    rc = arc_repl.main()
    assert rc == 1
    assert "RuntimeError: boom" in capsys.readouterr().err
