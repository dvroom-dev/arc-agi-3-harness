"""Reusable helpers for play.py.

This file is auto-loaded into arc_repl/model.py exec globals as `play_lib` helpers.
Keep this focused on game-play abstractions (feature detection, planning, action builders),
not model internals.
"""


def plan_level_actions(state: dict, *, level: int | None = None) -> list[int]:
    """Return a candidate action list for the current level.

    `play.py` is a static harness-owned dispatcher. Put level-specific replay
    branches in `plan_level_<N>` functions here, and let this dispatcher pick
    the active one.

    Prefer reusable, evidence-backed helpers that can reason over multiple
    detected copies of a feature rather than assuming a single distinguished
    instance.
    """
    lvl = level or int(state.get("current_level", 1))
    planner = globals().get(f"plan_level_{lvl}")
    if callable(planner):
        return list(planner(state))
    return []


def plan_level_1(state: dict) -> list[int]:
    """Level 1 replay branch placeholder."""
    _ = state
    return []


def describe_level_context(state: dict) -> dict:
    """Small helper for consistent logging from play.py scripts."""
    return {
        "state": state.get("state"),
        "current_level": state.get("current_level"),
        "levels_completed": state.get("levels_completed"),
        "available_actions": state.get("available_actions", []),
    }
