from __future__ import annotations

import json
from types import SimpleNamespace

import harness_repl_health as hrh


def test_repl_health_summary_missing_session_key(tmp_path) -> None:
    runtime = SimpleNamespace(
        arc_state_dir=tmp_path,
        active_repl_session_key="",
        last_repl_daemon_pid=None,
    )
    out = hrh.format_repl_health_summary(runtime)
    assert "session_key=missing" in out


def test_repl_health_summary_reads_pid_meta_and_lifecycle(tmp_path, monkeypatch) -> None:
    runtime = SimpleNamespace(
        arc_state_dir=tmp_path,
        active_repl_session_key="s1",
        last_repl_daemon_pid=1234,
    )
    session_dir = tmp_path / "repl-sessions" / "s1"
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "daemon.pid").write_text("1234\n")
    (session_dir / "session.json").write_text(
        json.dumps({"status": "running", "game_id": "ls20-cb3b57cc"}) + "\n"
    )
    (session_dir / "daemon.lifecycle.jsonl").write_text(
        json.dumps({"ts_unix": 50.0, "event": "daemon_ready"}) + "\n"
    )

    monkeypatch.setattr(hrh.os, "kill", lambda pid, sig: None)
    monkeypatch.setattr(hrh.time, "time", lambda: 55.0)

    out = hrh.format_repl_health_summary(runtime)
    assert "session_key=s1" in out
    assert "pid=1234" in out
    assert "alive=true" in out
    assert "matches_last_seen=yes" in out
    assert "meta_status=running" in out
    assert "meta_game=ls20-cb3b57cc" in out
    assert "last_event=daemon_ready" in out
    assert "last_event_age=5.0s" in out
