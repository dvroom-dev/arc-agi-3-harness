from __future__ import annotations

from harness_runner_regression import _classify_level_drop, _find_step_level_regression


def test_find_step_level_regression_detects_drop() -> None:
    events = [
        {"kind": "step", "action": "ACTION4", "levels_completed": 2},
        {"kind": "step", "action": "ACTION1", "levels_completed": 1},
    ]
    out = _find_step_level_regression(levels_before_resume=2, new_events=events)
    assert out is not None
    assert out["action"] == "ACTION1"
    assert out["from_levels_completed"] == 2
    assert out["to_levels_completed"] == 1


def test_classify_level_drop_allows_game_over_drop() -> None:
    prev_state = {"levels_completed": 3, "state": "NOT_FINISHED"}
    post_state = {"levels_completed": 0, "state": "GAME_OVER"}
    out = _classify_level_drop(prev_state=prev_state, post_state=post_state, new_events=[])
    assert out is not None
    assert out["kind"] == "drop_after_game_over"


def test_classify_level_drop_flags_confirmed_step_regression() -> None:
    prev_state = {"levels_completed": 2, "state": "NOT_FINISHED"}
    post_state = {"levels_completed": 1, "state": "NOT_FINISHED"}
    events = [
        {"kind": "step", "action": "ACTION3", "levels_completed": 2},
        {"kind": "step", "action": "ACTION1", "levels_completed": 1},
    ]
    out = _classify_level_drop(prev_state=prev_state, post_state=post_state, new_events=events)
    assert out is not None
    assert out["kind"] == "confirmed_step_regression_without_game_over"
    assert out["action"] == "ACTION1"


def test_classify_level_drop_returns_none_when_no_drop() -> None:
    prev_state = {"levels_completed": 1, "state": "NOT_FINISHED"}
    post_state = {"levels_completed": 1, "state": "NOT_FINISHED"}
    out = _classify_level_drop(prev_state=prev_state, post_state=post_state, new_events=[])
    assert out is None
