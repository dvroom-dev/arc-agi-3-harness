"""Agent-owned model mechanics helper stubs.

Goal: keep model.py thin. Put reusable mechanics and completion logic here.
Component definitions live in `components.py`.
If a visible entity already has a detector in `components.py`, use that detector
or the query helpers there (`find_components`, `find_one_component`,
`component_cells`, `component_bbox`) instead of re-deriving the entity from raw
pixel-value scans in this file.

Inheritance contract:
- `model.py` is harness-owned and applies level hooks cumulatively.
- `init_level_1`, `init_level_2`, ... run in ascending order up to the current level.
- `apply_level_1`, `apply_level_2`, ... run in ascending order on every action.
- Later level hooks may override earlier effects by mutating state afterward.
- Completion inherits by default from the latest defined `is_level_complete_level_<N>` hook at or below the current level.
- Game-over detection inherits by default from the latest defined `is_game_over_level_<N>` hook at or below the current level.

Write new levels as diffs:
- add or override the current level's hook(s)
- do not copy prior mechanics into later hooks unless you are intentionally changing them
- if a feature appears in level 3 and disappears in level 4, level 5 will still inherit the level-3 hook unless you override it
"""

from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass

import numpy as np

import artifact_helpers
from components import (
    COMPONENT_REGISTRY,
    ComponentBox,
    component_bbox,
    component_cells,
    find_components,
    find_one_component,
    iter_components,
    make_component,
)

@dataclass(frozen=True)
class LevelConfig:
    level_num: int
    turn_budget: int = 100


LEVEL_REGISTRY = {
    1: LevelConfig(level_num=1, turn_budget=100),
}


def get_level_config(level: int) -> LevelConfig | None:
    level_num = int(level)
    if level_num in LEVEL_REGISTRY:
        return LEVEL_REGISTRY[level_num]
    prior_levels = [lvl for lvl in LEVEL_REGISTRY if int(lvl) <= level_num]
    if not prior_levels:
        return None
    return LEVEL_REGISTRY[max(prior_levels)]


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


def resolve_sequence_action_path(action_dir: str | Path, relative_path: str | Path) -> Path:
    """Resolve a sequence-relative artifact path from the matched action dir itself.

    Use this for `files.*` and `frame_sequence_hex` entries from synced sequence
    artifacts. Do not hardcode `level_N` prefixes when the matched action may
    come from `level_current` or another visible level surface.
    """
    return artifact_helpers.resolve_sequence_action_path(action_dir, relative_path)


# ---------------------------------------------------------------------------
# Example helpers/mechanics (commented out by default):
#
# def init_level_shared(env, level, *, cfg=None):
#     _ = level, cfg
#     env.shared_cache = {}
#
# def init_level_1(env, *, cfg=None):
#     _ = cfg
#     env.some_cached_cells = []
#
# def apply_level_1(env, action, *, data=None, reasoning=None):
#     _ = data, reasoning
#     feature_positions = get_feature_positions(env.grid)
#     apply_example_mechanic(env, feature_positions, action)
#
# def apply_level_2(env, action, *, data=None, reasoning=None):
#     _ = data, reasoning
#     # Add or override only the level-2 delta here.
#     if action_name(action) == "ACTION2":
#         env.shared_cache["feature_x_enabled"] = True
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
    """Fallback completion check.

    Prefer `is_level_complete_level_<N>` hooks for inherited level-specific
    completion rules. This fallback is only used when no per-level completion
    hook is defined.
    """
    _ = env
    return False


def is_game_over(env) -> bool:
    """Fallback game-over check.

    Prefer `is_game_over_level_<N>` hooks for inherited level-specific
    game-over rules. This fallback is only used when no per-level game-over
    hook is defined.
    """
    _ = env
    return False
