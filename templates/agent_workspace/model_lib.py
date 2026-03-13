"""Agent-owned model mechanics helper stubs.

Goal: keep model.py thin. Put reusable mechanics and completion logic here.
Component definitions live in `components.py`.
"""

from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass

import numpy as np

import artifact_helpers
from components import COMPONENT_REGISTRY, ComponentBox, iter_components, make_component

@dataclass(frozen=True)
class LevelConfig:
    level_num: int
    turn_budget: int = 100


LEVEL_REGISTRY = {
    1: LevelConfig(level_num=1, turn_budget=100),
}


def get_level_config(level: int) -> LevelConfig | None:
    return LEVEL_REGISTRY.get(int(level))


def init_level(env, level: int, *, cfg: LevelConfig | None = None) -> None:
    """Optional level init hook called by the harness-owned model entrypoint.

    Use this to initialize per-level derived state. `model.py` already loads the
    canonical initial grid from disk and passes control here.
    """
    _ = env, level, cfg


def action_name(action) -> str:
    """Normalize an action-like value to a stable ACTION* name.

    Use this helper instead of `int(action)` so model logic works with enum
    members, action-like objects that expose `.name`, and plain strings.
    """
    if hasattr(action, "name"):
        name = str(getattr(action, "name") or "").strip()
        if name:
            return name.upper()
    text = str(action or "").strip()
    if not text:
        return ""
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return text.upper()


def apply_action(env, action, *, data: dict | None = None, reasoning: str | None = None) -> None:
    """Generic mechanics entrypoint called by the harness-owned model entrypoint.

    Implement this function for most games. If you prefer, you can instead
    define `apply_level_<n>(...)` helpers below and dispatch from here.
    """
    level_handler = globals().get(f"apply_level_{int(env.current_level)}")
    if callable(level_handler):
        level_handler(env, action, data=data, reasoning=reasoning)
        return
    _ = env, action, data, reasoning


# ---------------------------------------------------------------------------
# Feature definitions template (fill with evidence-backed entries).
#
# FEATURE_DEFINITIONS = [
#   {
#     "name": "feature_x",
#     "shape": "describe visual shape/extent",
#     "mechanics": [
#       {"confidence": "low|medium|high", "claim": "...", "evidence": ["..."]},
#     ],
#   },
# ]
# ---------------------------------------------------------------------------


def get_feature_positions(grid):
    """Return discovered feature positions from current grid.

    Start simple and deterministic. Suggested return shape:
      {
        "feature_x": [(row, col), ...],
        "feature_y": [(row, col), ...],
        "composite_feature_z": {"anchor": (row, col), "cells": [(row, col), ...]},
      }

    Important:
    - Prefer evidence-backed neutral names until a role is proven.
    - Return all detected copies of a feature unless evidence proves uniqueness.
    """
    _ = grid
    return {}


def load_initial_grid(game_dir: str | Path, level: int) -> np.ndarray | None:
    """Load an initial grid using run-local artifact helpers.

    Accepts either `str` or `Path` so quick one-off debugging snippets do not
    fail on path-type friction.
    """
    rows = artifact_helpers.load_level_hex_rows(game_dir, level, kind="initial")
    if not rows:
        return None
    return np.array([[int(ch, 16) for ch in row] for row in rows], dtype=np.int8)


# ---------------------------------------------------------------------------
# Example helpers/mechanics (commented out by default):
#
# def init_level(env, level, *, cfg=None):
#     _ = cfg
#     if level == 1:
#         env.some_cached_cells = []
#
# def apply_action(env, action, *, data=None, reasoning=None):
#     if env.current_level == 1:
#         apply_level_1(env, action, data=data, reasoning=reasoning)
#
# def apply_level_1(env, action, *, data=None, reasoning=None):
#     _ = data, reasoning
#     feature_positions = get_feature_positions(env.grid)
#     apply_example_mechanic(env, feature_positions, action)
#
# def find_all_feature_x(grid):
#     \"\"\"Return every observed copy of feature_x, not just the first one.\"\"\"
#     matches = []
#     _ = grid, matches
#     return matches
#
# def trigger_feature_x_at(env, row, col):
#     \"\"\"Apply an evidence-backed interaction at one feature location.\"\"\"
#     _ = env, row, col
#
# def apply_example_mechanic(env, feature_positions, action):
#     \"\"\"Example state transform skeleton using neutral feature names.\"\"\"
#     feature_x_positions = feature_positions.get("feature_x", [])
#     if action_name(action) == "ACTION1":
#         for row, col in feature_x_positions:
#             trigger_feature_x_at(env, row, col)
# ---------------------------------------------------------------------------


def is_level_complete(env) -> bool:
    """Stub completion check.

    Replace with level-aware completion criteria derived from evidence.
    """
    _ = env
    return False
