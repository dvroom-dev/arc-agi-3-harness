from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import arc_repl


def test_main_invalid_args_and_missing_action(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["arc_repl"])
    monkeypatch.setattr(arc_repl, "_read_args", lambda: {"_error": "bad"})
    rc = arc_repl.main()
    assert rc == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["type"] == "invalid_args"

    monkeypatch.setattr(sys, "argv", ["arc_repl"])
    monkeypatch.setattr(arc_repl, "_read_args", lambda: {})
    rc = arc_repl.main()
    assert rc == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["type"] == "missing_action"


def test_main_internal_exception(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["arc_repl"])
    monkeypatch.setattr(arc_repl, "_read_args", lambda: {"action": "status", "game_id": "ls20"})
    monkeypatch.setattr(arc_repl, "_send_request", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    rc = arc_repl.main()
    assert rc == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["type"] == "internal_exception"


def test_main_exec_non_dict_result(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["arc_repl"])
    monkeypatch.setattr(
        arc_repl,
        "_read_args",
        lambda: {"action": "exec", "game_id": "ls20", "script": "print(1)"},
    )
    monkeypatch.setattr(arc_repl, "_send_request", lambda *a, **k: ("raw-output", False))
    rc = arc_repl.main()
    assert rc == 1
    assert "raw-output" in capsys.readouterr().out


def test_daemon_main_dispatch(monkeypatch, tmp_path: Path) -> None:
    session_calls = []

    class FakeSession:
        def __init__(self, **kwargs):
            self.game_id = "ls20-cb3b57cc"

        def do_status(self, requested_game_id, session_created=False):
            session_calls.append(("status", requested_game_id))
            return {"ok": True, "action": "status"}

        def do_reset_level(self, requested_game_id, session_created=False):
            session_calls.append(("reset_level", requested_game_id))
            return {"ok": True, "action": "reset_level"}

        def do_exec(self, requested_game_id, script, session_created=False):
            session_calls.append(("exec", requested_game_id, script))
            return {"ok": True, "action": "exec", "script_stdout": "x"}

    requests = [
        {"action": "ping"},
        {"action": "status", "game_id": "ls20"},
        {"action": "reset_level", "game_id": "ls20"},
        {"action": "exec", "game_id": "ls20", "script": "print(1)"},
        {"action": "shutdown"},
    ]

    class FakeConn:
        def __init__(self, req):
            self.req = req
            self.sent = None

        def recv(self):
            return self.req

        def send(self, payload):
            self.sent = payload

        def close(self):
            return None

    class FakeListener:
        def __init__(self, *_a, **_k):
            self.i = 0

        def accept(self):
            req = requests[self.i]
            self.i += 1
            return FakeConn(req)

        def close(self):
            return None

    monkeypatch.setattr(arc_repl, "ReplSession", FakeSession)
    monkeypatch.setattr(arc_repl.multiprocessing.connection, "Listener", FakeListener)
    monkeypatch.setattr(arc_repl, "_arc_dir", lambda cwd: tmp_path / "arc")
    monkeypatch.setattr(arc_repl, "_session_dir", lambda cwd, cid: tmp_path / "arc" / "repl-sessions" / cid)
    monkeypatch.setattr(arc_repl, "_socket_path", lambda cwd, cid: tmp_path / "arc" / "sock")
    monkeypatch.setattr(arc_repl, "_meta_path", lambda cwd, cid: tmp_path / "arc" / "meta.json")
    rc = arc_repl._daemon_main(tmp_path, "conv-1", "ls20")
    assert rc == 0
    assert ("status", "ls20") in session_calls
    assert ("reset_level", "ls20") in session_calls
