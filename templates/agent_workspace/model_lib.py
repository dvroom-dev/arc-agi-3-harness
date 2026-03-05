"""Agent-owned model helper stubs.

Goal: keep model.py thin. Put feature detection and reusable mechanics here.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LevelConfig:
    level_num: int
    turn_budget: int = 100


LEVEL_REGISTRY = {
    1: LevelConfig(level_num=1, turn_budget=100),
}


def get_level_config(level: int) -> LevelConfig | None:
    return LEVEL_REGISTRY.get(int(level))


# ---------------------------------------------------------------------------
# Feature definitions template (fill with evidence-backed entries).
#
# FEATURE_DEFINITIONS = [
#   {
#     "name": "feature-name",
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
        "player": (row, col),
        "exit": [(row, col), ...],
        "triggers": {"cross": [(row, col), ...]},
      }
    """
    _ = grid
    return {}


# ---------------------------------------------------------------------------
# Example mechanic (commented out by default):
#
# def apply_example_mechanic(env, feature_positions, action):
#     \"\"\"Example state transform skeleton.\"\"\"
#     if action.name == "ACTION1" and "player" in feature_positions:
#         row, col = feature_positions["player"]
#         # mutate env.grid here based on verified rules
#         env.grid[row][col] = env.grid[row][col]
# ---------------------------------------------------------------------------


def is_level_complete(env) -> bool:
    """Stub completion check.

    Replace with level-aware completion criteria derived from evidence.
    """
    _ = env
    return False

