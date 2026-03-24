from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np

import arc_repl


class _FakeEnv:
    def __init__(self) -> None:
        self.steps = 0

    def reset(self):
        action_id = SimpleNamespace(name="RESET", value=0)
        action_input = SimpleNamespace(id=action_id, data={}, reasoning=None)
        return SimpleNamespace(
            game_id="ls20-cb3b57cc",
            guid="g",
            state=SimpleNamespace(value="NOT_FINISHED"),
            levels_completed=0,
            win_levels=7,
            available_actions=[0, 1, 2, 3, 4],
            full_reset=False,
            action_input=action_input,
            frame=[np.zeros((64, 64), dtype=np.int8)],
        )

    def step(self, action, data=None, reasoning=None):
        self.steps += 1
        action_id = SimpleNamespace(name=getattr(action, "name", str(action)), value=int(action.value))
        action_input = SimpleNamespace(id=action_id, data=data or {}, reasoning=reasoning)
        frame = np.full((64, 64), self.steps % 16, dtype=np.int8)
        return SimpleNamespace(
            game_id="ls20-cb3b57cc",
            guid="g",
            state=SimpleNamespace(value="NOT_FINISHED"),
            levels_completed=0,
            win_levels=7,
            available_actions=[0, 1, 2, 3, 4],
            full_reset=False,
            action_input=action_input,
            frame=[frame],
        )


def test_repl_session_restore_keeps_bootstrap_initial_state(monkeypatch, tmp_path: Path) -> None:
    arc_dir = tmp_path / "arc"
    arc_dir.mkdir()
    monkeypatch.setenv("ARC_ACTIVE_GAME_ID", "ls20")
    monkeypatch.setenv("ARC_STATE_DIR", str(arc_dir))
    play_lib = tmp_path / "play_lib.py"
    play_lib.write_text("def helper():\n    return 1\n", encoding="utf-8")
    completions = arc_dir / "level_completions.md"
    completions.write_text("# Level Completions\n", encoding="utf-8")
    history_payload = {
        "game_id": "ls20-cb3b57cc",
        "events": [{"kind": "step", "action": "ACTION1", "data": None, "levels_completed": 0}],
        "turn": 1,
    }

    monkeypatch.setattr(arc_repl, "_arc_dir", lambda cwd: arc_dir)
    monkeypatch.setattr(arc_repl, "_ensure_play_lib_file", lambda cwd: play_lib)
    monkeypatch.setattr(arc_repl, "_ensure_level_completions_file", lambda cwd: completions)
    monkeypatch.setattr(arc_repl, "_load_history", lambda cwd, gid: dict(history_payload))
    monkeypatch.setattr(arc_repl, "_save_history", lambda cwd, h: history_payload.update(h))
    monkeypatch.setattr(arc_repl, "_make_env", lambda gid: _FakeEnv())
    monkeypatch.setattr(arc_repl, "_reset_env_with_retry", lambda env, **kwargs: env.reset())
    monkeypatch.setattr(arc_repl, "_get_pixels", lambda env, frame=None: frame.frame[-1])
    monkeypatch.setattr(arc_repl, "write_game_state", lambda *a, **k: None)
    monkeypatch.setattr(arc_repl, "write_machine_state", lambda *a, **k: None)
    monkeypatch.setattr(arc_repl, "_write_turn_trace", lambda **k: arc_dir / "trace.md")
    monkeypatch.setattr(arc_repl, "_append_level_completion", lambda **k: None)

    level_dir = arc_dir / "game_artifacts" / "game_ls20-cb3b57cc" / "level_1"
    level_dir.mkdir(parents=True, exist_ok=True)
    (level_dir / "initial_state.hex").write_text(("\n".join(["0" * 64] * 64)) + "\n", encoding="utf-8")

    session = arc_repl.ReplSession(cwd=tmp_path, conversation_id="conv-1", requested_game_id="ls20")

    assert (level_dir / "initial_state.hex").read_text(encoding="utf-8").splitlines() == ["0" * 64] * 64
    assert session.env.steps == 1
