from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

import arc_action


def _frame(state="NOT_FINISHED", levels_completed=0):
    return SimpleNamespace(
        state=SimpleNamespace(value=state),
        levels_completed=levels_completed,
        win_levels=7,
        frame=[np.zeros((2, 2), dtype=np.int8)],
    )


def test_resolve_operation_mode(monkeypatch) -> None:
    monkeypatch.setenv("ARC_OPERATION_MODE", "ONLINE")
    assert arc_action._resolve_operation_mode().name == "ONLINE"
    monkeypatch.setenv("ARC_OPERATION_MODE", "BAD")
    with pytest.raises(RuntimeError):
        arc_action._resolve_operation_mode()


def test_resolve_environments_dir(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ARC_ENVIRONMENTS_DIR", str(tmp_path))
    assert arc_action._resolve_environments_dir() == tmp_path
    monkeypatch.setenv("ARC_ENVIRONMENTS_DIR", str(tmp_path / "missing"))
    with pytest.raises(RuntimeError):
        arc_action._resolve_environments_dir()


def test_make_env_uses_candidates(monkeypatch) -> None:
    made = []

    class FakeArcade:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def make(self, gid, render_mode=None, scorecard_id=None):
            made.append(gid)
            if gid == "ls20":
                return object()
            return None

    monkeypatch.setenv("ARC_OPERATION_MODE", "NORMAL")
    monkeypatch.setattr(arc_action.arc_agi, "Arcade", FakeArcade)
    env = arc_action._make_env("ls20-cb3b57cc")
    assert env is not None
    assert made == ["ls20-cb3b57cc", "ls20"]


def test_replay_history_reset_and_terminal_handling() -> None:
    class Env:
        def __init__(self):
            self.i = 0

        def reset(self):
            self.i += 1
            return _frame()

        def step(self, action, data=None):
            if self.i >= 2:
                return None
            return _frame("GAME_OVER" if self.i == 1 else "NOT_FINISHED")

    env = Env()
    events = [
        {"kind": "step", "action": "ACTION1", "levels_completed": 0},
        {"kind": "reset"},
        {"kind": "step", "action": "ACTION1", "levels_completed": 0},
    ]
    frame = arc_action._replay_history(env, events)
    assert frame is not None


def test_get_pixels_uses_frame_data() -> None:
    frame = _frame()
    pixels = arc_action._get_pixels(None, frame)
    assert pixels.shape == (2, 2)

