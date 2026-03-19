from __future__ import annotations

from pathlib import Path

import arc_repl_daemon as daemon


def test_parent_alive_none_is_true() -> None:
    assert daemon._parent_alive(None, None) is True


def test_daemon_stops_when_parent_exits(monkeypatch, tmp_path: Path) -> None:
    events: list[tuple[str, dict]] = []

    class FakeSession:
        game_id = "ls20"

        def do_status(self, *_args, **_kwargs):
            return {"ok": True, "action": "status"}

        def do_reset_level(self, *_args, **_kwargs):
            return {"ok": True, "action": "reset_level"}

        def do_exec(self, *_args, **_kwargs):
            return {"ok": True, "action": "exec"}

    monkeypatch.setattr(daemon, "_parent_alive", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(daemon.time, "sleep", lambda _t: None)

    def _append_event(_cwd, _conversation_id, event, **fields):
        events.append((str(event), dict(fields)))

    rc = daemon.run_daemon(
        cwd=tmp_path,
        conversation_id="c1",
        requested_game_id="ls20",
        socket_path=tmp_path / "daemon.ready",
        meta_path=tmp_path / "session.json",
        requests_dir=tmp_path / "ipc" / "requests",
        responses_dir=tmp_path / "ipc" / "responses",
        make_session=lambda: FakeSession(),
        append_lifecycle_event=_append_event,
        error_payload=lambda **kwargs: kwargs,
        schema_version="test.v1",
        parent_pid=1234,
        parent_start_ticks=5678,
    )

    assert rc == 0
    assert any(name == "daemon_parent_exit_detected" for name, _ in events)
    stop_events = [payload for name, payload in events if name == "daemon_stop"]
    assert stop_events
    assert stop_events[-1].get("reason") == "parent_exit"
