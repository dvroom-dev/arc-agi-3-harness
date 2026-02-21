from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np

import arc_action


class FakeConn:
    def __init__(self):
        self.sent = []
        self.closed = False

    def send(self, msg):
        self.sent.append(msg)

    def recv(self):
        last = self.sent[-1]
        op = last.get("op")
        if op == "step":
            return {
                "ok": True,
                "frame": {
                    "state": "NOT_FINISHED",
                    "levels_completed": 0,
                    "win_levels": 7,
                    "current_level": 1,
                    "full_reset": False,
                    "available_actions": [0, 1, 2, 3, 4],
                    "action_input_id": 1,
                    "action_input_name": "ACTION1",
                },
            }
        if op == "get_state":
            return {"ok": True, "state": {"state": "NOT_FINISHED"}}
        return {"ok": False, "error": "unsupported"}

    def close(self):
        self.closed = True


def test_script_worker_main_happy_path() -> None:
    conn = FakeConn()
    script = "env.step(GameAction.ACTION1)\nprint(env.state().get('state'))\n"
    arc_action._script_worker_main(conn, script, "", "<script>")
    assert conn.closed is True
    assert any(msg.get("op") == "done" for msg in conn.sent)


def test_script_worker_main_handles_script_error() -> None:
    conn = FakeConn()
    script = "raise Exception('boom')\n"
    arc_action._script_worker_main(conn, script, "", "<script>")
    done = [m for m in conn.sent if m.get("op") == "done"][-1]
    assert "Traceback" in done.get("error", "")


def test_write_turn_trace_includes_diff_and_note(tmp_path: Path) -> None:
    arc_dir = tmp_path / "arc"
    pre = np.zeros((2, 2), dtype=np.int8)
    s1 = np.array([[1, 0], [0, 0]], dtype=np.int8)
    s2 = np.array([[1, 2], [0, 0]], dtype=np.int8)
    path = arc_action._write_turn_trace(
        arc_dir=arc_dir,
        turn=1,
        action_name="run_script",
        pre_pixels=pre,
        step_snapshots=[("a1", s1), ("a2", s2)],
        step_results=[{"levels_gained_in_step": 0}, {"levels_gained_in_step": 1}],
        final_pixels=s2,
        script_output="out",
        error="",
    )
    text = path.read_text()
    assert "Per-Step Diffs" in text
    assert "suppressed" in text


def test_write_game_state_with_step_diffs(tmp_path: Path) -> None:
    frame = SimpleNamespace(
        game_id="ls20",
        guid="g",
        state=SimpleNamespace(value="NOT_FINISHED"),
        levels_completed=0,
        win_levels=7,
        available_actions=[1, 2, 3, 4],
        full_reset=False,
        action_input=SimpleNamespace(id=SimpleNamespace(name="ACTION1", value=1), data={}, reasoning=None),
    )
    pre = np.zeros((2, 2), dtype=np.int8)
    post = np.array([[1, 0], [0, 0]], dtype=np.int8)
    out = tmp_path / "game-state.md"
    arc_action.write_game_state(
        out,
        frame,
        post,
        game_id="ls20",
        last_action="run_script",
        script_output="hello",
        error="",
        step_snapshots=[("a1", post)],
        pre_turn_pixels=pre,
        step_results=[{"levels_gained_in_step": 0}],
    )
    text = out.read_text()
    assert "Step Diffs" in text
    assert "Aggregate Diff" in text

