from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

import arc_action


def _frame(state: str = "NOT_FINISHED", levels_completed: int = 0):
    action_id = SimpleNamespace(name="ACTION1", value=1)
    action_input = SimpleNamespace(id=action_id, data={}, reasoning=None)
    return SimpleNamespace(
        game_id="ls20-cb3b57cc",
        guid="g1",
        state=SimpleNamespace(value=state),
        levels_completed=levels_completed,
        win_levels=7,
        available_actions=[0, 1, 2, 3, 4],
        full_reset=False,
        action_input=action_input,
        frame=[np.zeros((64, 64), dtype=np.int8)],
    )


def test_arc_action_main_status_mocked(tmp_path: Path, monkeypatch) -> None:
    arc_dir = tmp_path / "arc"
    arc_dir.mkdir()
    monkeypatch.setenv("ARC_STATE_DIR", str(arc_dir))

    monkeypatch.setattr(arc_action, "_read_args", lambda: {"action": "status", "game_id": "ls20"})
    monkeypatch.setattr(arc_action, "_ensure_play_lib_file", lambda cwd: cwd / "play_lib.py")
    monkeypatch.setattr(arc_action, "_load_history", lambda cwd, gid: {"game_id": gid, "events": [], "turn": 0})
    monkeypatch.setattr(arc_action, "_make_env", lambda gid: object())
    monkeypatch.setattr(arc_action, "_replay_history", lambda env, events: _frame())
    monkeypatch.setattr(arc_action, "_get_pixels", lambda env, frame=None: np.zeros((64, 64), dtype=np.int8))
    monkeypatch.setattr(arc_action, "_save_history", lambda cwd, history: None)
    monkeypatch.setattr(arc_action, "write_game_state", lambda *a, **k: None)
    monkeypatch.setattr(arc_action, "write_machine_state", lambda *a, **k: None)
    monkeypatch.setattr(arc_action, "_write_turn_trace", lambda **k: arc_dir / "trace.md")

    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    rc = arc_action.main()
    assert rc == 0
    payload = json.loads(out.getvalue())
    assert payload["ok"] is True
    assert payload["action"] == "status"


def test_arc_action_main_missing_action(monkeypatch) -> None:
    monkeypatch.setattr(arc_action, "_read_args", lambda: {})
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    rc = arc_action.main()
    assert rc == 1
    payload = json.loads(out.getvalue())
    assert payload["error"]["type"] == "missing_action"

