from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np

import arc_repl_exec


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
        return self.step(arc_repl_exec.GameAction.RESET)


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
    ) = arc_repl_exec._execute_script(
        script,
        env,
        script_label="<test_script>",
        initial_frame=_initial_frame(),
        play_lib_source="def helper():\n    return 1\n",
        get_pixels=lambda env, frame=None: frame.frame[-1] if frame is not None else np.zeros((64, 64), dtype=np.int8),
    )

    assert last_frame is not None
    assert last_frame.state.value == "WIN"
    assert "done" not in output  # execution stops at terminal step
    assert error == ""
    assert len(transition_log) == 2
    assert len(step_snapshots) == 2
    assert len(executed_events) == 2
    assert step_results[-1]["is_terminal"] is True
    assert step_results[0]["frame_count"] == 1
