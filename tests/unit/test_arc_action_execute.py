from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np

import arc_action


class FakeEnv:
    def __init__(self):
        self.counter = 0

    def step(self, action, data=None, reasoning=None):
        self.counter += 1
        state = "WIN" if self.counter >= 2 else "NOT_FINISHED"
        action_id = SimpleNamespace(name=getattr(action, "name", str(action)), value=int(action.value))
        action_input = SimpleNamespace(id=action_id, data=data or {}, reasoning=reasoning)
        frame = np.full((64, 64), self.counter, dtype=np.int8)
        return SimpleNamespace(
            game_id="ls20-cb3b57cc",
            guid="g",
            state=SimpleNamespace(value=state),
            levels_completed=0,
            win_levels=7,
            available_actions=[0, 1, 2, 3, 4],
            full_reset=False,
            action_input=action_input,
            frame=[frame],
        )

    def reset(self):
        return self.step(arc_action.GameAction.RESET)


def _initial_frame():
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


def test_execute_script_runs_steps_and_stops_on_terminal() -> None:
    env = FakeEnv()
    script = "env.step(GameAction.ACTION1)\nenv.step(GameAction.ACTION2)\nprint('done')\n"
    (
        last_frame,
        output,
        error,
        transition_log,
        step_snapshots,
        executed_events,
        step_results,
    ) = arc_action._execute_script(
        script,
        env,
        script_label="<test_script>",
        initial_frame=_initial_frame(),
        play_lib_source="def helper():\n    return 1\n",
    )

    assert last_frame is not None
    assert last_frame.state.value == "WIN"
    assert "done" not in output  # execution stops at terminal step
    assert error == ""
    assert len(transition_log) == 2
    assert len(step_snapshots) == 2
    assert len(executed_events) == 2
    assert step_results[-1]["is_terminal"] is True


def test_arc_action_main_run_script_branch(tmp_path: Path, monkeypatch) -> None:
    arc_dir = tmp_path / "arc"
    arc_dir.mkdir()
    monkeypatch.setenv("ARC_STATE_DIR", str(arc_dir))
    cwd = tmp_path / "wd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)

    frame0 = _initial_frame()
    frame1 = _initial_frame()
    frame1.levels_completed = 1
    frame1.frame = [np.ones((64, 64), dtype=np.int8)]

    monkeypatch.setattr(
        arc_action,
        "_read_args",
        lambda: {"action": "run_script", "game_id": "ls20", "script": "print('x')"},
    )
    play_lib = cwd / "play_lib.py"
    play_lib.write_text("def helper():\n    return 1\n")
    monkeypatch.setattr(arc_action, "_ensure_play_lib_file", lambda cwd_: play_lib)
    monkeypatch.setattr(arc_action, "_load_history", lambda cwd_, gid: {"game_id": gid, "events": [], "turn": 0})
    monkeypatch.setattr(arc_action, "_make_env", lambda gid: SimpleNamespace(reset=lambda: frame0))
    monkeypatch.setattr(arc_action, "_reset_env_with_retry", lambda env, **kwargs: frame0)
    monkeypatch.setattr(
        arc_action,
        "_execute_script",
        lambda *a, **k: (
            frame1,
            "stdout\n",
            "",
            ["ACTION1 -> state=NOT_FINISHED levels=0/7"],
            [("ACTION1", np.ones((64, 64), dtype=np.int8))],
            [{"kind": "step", "action": "ACTION1", "levels_completed": 1}],
            [{"step": 1, "action": "ACTION1", "changed_pixels": 1, "levels_gained_in_step": 1}],
        ),
    )
    monkeypatch.setattr(arc_action, "_get_pixels", lambda env, frame=None: frame.frame[-1] if frame else np.zeros((64, 64), dtype=np.int8))
    monkeypatch.setattr(arc_action, "_save_history", lambda cwd_, history: None)
    monkeypatch.setattr(arc_action, "write_game_state", lambda *a, **k: None)
    monkeypatch.setattr(arc_action, "write_machine_state", lambda *a, **k: None)
    monkeypatch.setattr(arc_action, "_write_turn_trace", lambda **k: arc_dir / "trace.md")

    out = []
    monkeypatch.setattr(
        arc_action,
        "_emit_json",
        lambda payload: out.append(payload),
    )
    rc = arc_action.main()
    assert rc == 0
    payload = out[-1]
    assert payload["action"] == "run_script"
    assert payload["ok"] is True
    assert payload["levels_completed"] == 1
    assert payload["steps_executed"] == 1
