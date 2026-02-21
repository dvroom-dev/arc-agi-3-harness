from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import numpy as np

from harness_scorecard_timeout_hack import (
    KEEPALIVE_IDLE_SECONDS,
    KEEPALIVE_SOURCE,
    choose_keepalive_action,
    has_new_agent_steps,
    maybe_inject_scorecard_keepalive_hack,
)


# HACK TESTS:
# These tests intentionally cover temporary scorecard-timeout keepalive behavior.
# Remove this file when the timeout hack is replaced by a proper heartbeat mechanism.


def _step(action: str, *, data=None, source: str | None = None) -> dict:
    event = {"kind": "step", "action": action, "levels_completed": 0}
    if data is not None:
        event["data"] = data
    if source is not None:
        event["source"] = source
    return event


def test_timeout_hack_prefers_action5_when_recent_agent_history_has_no_action5() -> None:
    action_id, data = choose_keepalive_action(
        events=[_step("ACTION1"), _step("ACTION2"), _step("ACTION6", data={"x": 0, "y": 0})],
        grid_shape=(5, 5),
        min_event_index=0,
    )
    assert action_id == 5
    assert data is None


def test_timeout_hack_uses_unclicked_corner_for_action6_after_action5_seen() -> None:
    events = [
        _step("ACTION5"),
        _step("ACTION6", data={"x": 0, "y": 0}),
    ]
    action_id, data = choose_keepalive_action(
        events=events,
        grid_shape=(4, 4),
        min_event_index=0,
    )
    assert action_id == 6
    assert data == {"x": 3, "y": 0}


def test_timeout_hack_prefers_edge_when_all_corners_already_clicked() -> None:
    events = [_step("ACTION5")]
    for x, y in [(0, 0), (4, 0), (0, 4), (4, 4)]:
        events.append(_step("ACTION6", data={"x": x, "y": y}))
    action_id, data = choose_keepalive_action(
        events=events,
        grid_shape=(5, 5),
        min_event_index=0,
    )
    assert action_id == 6
    assert data == {"x": 1, "y": 0}


def test_timeout_hack_prefers_near_edge_interior_after_edges_exhausted() -> None:
    events = [_step("ACTION5")]
    for y in range(5):
        for x in range(5):
            if x in {0, 4} or y in {0, 4}:
                events.append(_step("ACTION6", data={"x": x, "y": y}))
    action_id, data = choose_keepalive_action(
        events=events,
        grid_shape=(5, 5),
        min_event_index=0,
    )
    assert action_id == 6
    assert data == {"x": 1, "y": 1}


def test_timeout_hack_falls_back_to_corner_if_all_cells_clicked() -> None:
    events = [_step("ACTION5")]
    for y in range(3):
        for x in range(3):
            events.append(_step("ACTION6", data={"x": x, "y": y}))
    action_id, data = choose_keepalive_action(
        events=events,
        grid_shape=(3, 3),
        min_event_index=0,
    )
    assert action_id == 6
    assert data == {"x": 0, "y": 0}


def test_timeout_hack_only_looks_back_100_agent_actions() -> None:
    events = [_step("ACTION5")]
    events.extend(_step("ACTION1") for _ in range(100))
    action_id, data = choose_keepalive_action(
        events=events,
        grid_shape=(6, 6),
        min_event_index=0,
    )
    assert action_id == 5
    assert data is None


def test_timeout_hack_ignores_harness_marked_events_and_pre_agent_floor() -> None:
    events = [
        _step("ACTION5"),  # before floor, should be ignored
        _step("ACTION1"),
        _step("ACTION5", source=KEEPALIVE_SOURCE),  # harness event, ignored
        _step("ACTION2"),
    ]
    action_id, data = choose_keepalive_action(
        events=events,
        grid_shape=(5, 5),
        min_event_index=2,
    )
    assert action_id == 5
    assert data is None


def test_timeout_hack_detects_new_agent_steps_but_not_harness_steps() -> None:
    events = [
        _step("ACTION1", source=KEEPALIVE_SOURCE),
        _step("ACTION2", source=KEEPALIVE_SOURCE),
        _step("ACTION3"),
    ]
    assert has_new_agent_steps(events=events, since_event_index=0, agent_history_floor=0) is True
    assert has_new_agent_steps(events=events, since_event_index=0, agent_history_floor=3) is False


class _FakeDeps:
    @staticmethod
    def load_history_events(path: Path):
        payload = json.loads(path.read_text())
        return payload.get("events", [])


class _FakeRuntime:
    def __init__(self, history_json: Path) -> None:
        self.history_json = history_json
        self.active_scorecard_id = "sc-1"
        self.args = Namespace(game_id="ls20")
        self.deps = _FakeDeps()
        self._pixels = np.zeros((4, 4), dtype=np.int8)
        self.logs: list[str] = []

    def load_current_pixels(self):
        return self._pixels

    def log(self, msg: str) -> None:
        self.logs.append(msg)

    def run_arc_repl(self, payload: dict):
        script = str(payload.get("script", ""))
        history = json.loads(self.history_json.read_text())
        events = list(history.get("events", []))
        if "env.step(5)" in script:
            events.append(_step("ACTION5"))
        elif "env.step(6" in script:
            # script format is fixed in maybe_inject_scorecard_keepalive_hack
            x_part = script.split("'x':", 1)[1].split(",", 1)[0].strip()
            y_part = script.split("'y':", 1)[1].split("}", 1)[0].strip()
            events.append(_step("ACTION6", data={"x": int(x_part), "y": int(y_part)}))
        else:
            return None, "invalid script", 1
        history["events"] = events
        self.history_json.write_text(json.dumps(history, indent=2) + "\n")
        return None, "", 0


def test_timeout_hack_injects_and_tags_keepalive_event_when_idle(tmp_path: Path) -> None:
    history_json = tmp_path / "tool-engine-history.json"
    history_json.write_text(json.dumps({"events": [_step("ACTION1")]}, indent=2) + "\n")
    rt = _FakeRuntime(history_json)
    ts, injected = maybe_inject_scorecard_keepalive_hack(
        rt,
        last_action_at_monotonic=0.0,
        agent_history_floor=0,
        now_monotonic=KEEPALIVE_IDLE_SECONDS + 1.0,
    )
    assert injected is True
    assert ts == KEEPALIVE_IDLE_SECONDS + 1.0
    payload = json.loads(history_json.read_text())
    assert payload["events"][-1]["action"] == "ACTION5"
    assert payload["events"][-1]["source"] == KEEPALIVE_SOURCE
    assert any("HACK(scorecard-timeout-keepalive) injected" in msg for msg in rt.logs)


def test_timeout_hack_does_not_inject_when_not_idle(tmp_path: Path) -> None:
    history_json = tmp_path / "tool-engine-history.json"
    history_json.write_text(json.dumps({"events": [_step("ACTION1")]}, indent=2) + "\n")
    rt = _FakeRuntime(history_json)
    ts, injected = maybe_inject_scorecard_keepalive_hack(
        rt,
        last_action_at_monotonic=100.0,
        agent_history_floor=0,
        now_monotonic=100.0 + KEEPALIVE_IDLE_SECONDS - 1.0,
    )
    assert injected is False
    assert ts == 100.0
    payload = json.loads(history_json.read_text())
    assert len(payload["events"]) == 1
