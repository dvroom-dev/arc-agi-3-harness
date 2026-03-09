"""Reusable helpers for play.py.

This file is auto-loaded into arc_repl/model.py exec globals as `play_lib` helpers.
Keep this focused on game-play abstractions (feature detection, planning, action builders),
not model internals.
"""


def plan_level_actions(state: dict, *, level: int | None = None) -> list[int]:
    """Return a candidate action list for the current level.

    Replace this placeholder with reusable, evidence-backed logic.
    Prefer generic helpers that can reason over multiple detected copies of a
    feature rather than assuming a single distinguished instance.
    """
    _ = state, level
    return []


def describe_level_context(state: dict) -> dict:
    """Small helper for consistent logging from play.py scripts."""
    return {
        "state": state.get("state"),
        "current_level": state.get("current_level"),
        "levels_completed": state.get("levels_completed"),
        "available_actions": state.get("available_actions", []),
    }
