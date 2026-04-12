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


def test_send_request_recovers_after_prior_session_when_socket_is_missing(monkeypatch, tmp_path: Path) -> None:
    arc_dir = tmp_path / "arc"
    arc_dir.mkdir()
    monkeypatch.setenv("ARC_STATE_DIR", str(arc_dir))
    session_dir = arc_repl._session_dir(tmp_path, "c1")
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "daemon.pid").write_text("12345\n")
    (session_dir / "session.json").write_text('{"status":"running","game_id":"ls20"}\n')
    (session_dir / "daemon.lifecycle.jsonl").write_text('{"event":"spawned"}\n')
    (session_dir / "daemon.log").write_text("trace line\n")

    socket_path = tmp_path / "missing.sock"
    spawned = {"n": 0}
    monkeypatch.setattr(arc_repl, "_socket_path", lambda cwd, cid: socket_path)
    monkeypatch.setattr(
        arc_repl,
        "_spawn_daemon",
        lambda *a, **k: spawned.__setitem__("n", spawned["n"] + 1),
    )
    monkeypatch.setattr(arc_repl, "_wait_for_daemon", lambda *a, **k: socket_path.write_text("ready\n"))
    monkeypatch.setattr(arc_repl, "_default_game_id", lambda cwd: "ls20")
    monkeypatch.setattr(
        arc_repl,
        "_send_ipc_request",
        lambda *a, **k: {"ok": True, "action": "status"},
    )

    result, created = arc_repl._send_request(tmp_path, "c1", {"action": "status", "game_id": "ls20"})
    assert result["ok"] is True
    assert created is True
    assert spawned["n"] == 1


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
            {
                "ok": True,
                "action": "exec",
                "script_stdout": "hello\n",
                "state": "NOT_FINISHED",
                "current_level": 1,
                "levels_completed": 0,
                "steps_executed": 1,
                "trace_file": "trace.md",
                "artifacts": {
                    "after_state_hex": "ABCD",
                },
            },
            False,
        ),
    )
    rc = arc_repl.main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "hello" in out
    assert "<arc_repl_result>" in out
    assert "\"after_state_hex\": \"ABCD\"" in out


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


def test_main_exec_redacts_frontier_level_while_analysis_pin_is_active(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".analysis_level_pin.json").write_text(
        json.dumps({"level": 1, "phase": "pending_theory"}, indent=2)
    )
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
            {
                "ok": True,
                "action": "exec",
                "script_stdout": "",
                "state": "NOT_FINISHED",
                "current_level": 2,
                "levels_completed": 1,
                "steps_executed": 1,
                "trace_file": "trace.md",
                "artifacts": {
                    "level": 1,
                    "tool_turn": 21,
                    "changed_pixels": 7,
                    "after_state_hex": "2222",
                },
            },
            False,
        ),
    )
    rc = arc_repl.main()
    assert rc == 0
    out = capsys.readouterr().out
    assert '"current_level": 1' in out
    assert '"levels_completed": 0' in out
    assert '"analysis_level_boundary_redacted": true' in out
    assert '"after_state_hex"' not in out


def test_main_blocks_real_game_actions_until_required_solver_handoff_exists(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".flux_solver_handoff_requirement.json").write_text(
        json.dumps(
            {
                "schema_version": "flux.solver_handoff_requirement.v1",
                "required_theory_level": 1,
                "frontier_level": 2,
                "required_file": "solver_handoff/untrusted_theories.md",
                "requested_at": "2026-04-12T12:00:00Z",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sys, "argv", ["arc_repl"])
    monkeypatch.setattr(
        arc_repl,
        "_read_args",
        lambda: {"action": "exec", "game_id": "ls20", "script": "print('x')"},
    )
    rc = arc_repl.main()
    assert rc == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["type"] == "critical_instruction_required"
    assert payload["required_file"] == "solver_handoff/untrusted_theories.md"
    assert "critical_instruction" in payload
