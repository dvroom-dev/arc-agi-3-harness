"""Reusable helpers for model.py internals.

This module is the single source of truth for model mechanics and level data.
Keep model.py thin and move almost all game-specific logic here.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class LevelConfig:
    level_num: int
    name: str
    turn_budget: int


# Keep all per-level constants in model_lib.py, not in model.py.
LEVEL_REGISTRY = {
    1: LevelConfig(level_num=1, name="level_1", turn_budget=100),
}


def get_level_config(level: int) -> LevelConfig | None:
    return LEVEL_REGISTRY.get(int(level))


# Optional per-level anchor registry for deterministic model mechanics.
# Fill this with evidence-backed coordinates/regions as levels are solved.
FEATURE_ANCHORS_BY_LEVEL: dict[int, dict[str, tuple[int, int] | tuple[int, int, int, int]]] = {
    1: {},
}


def get_anchor(level: int, name: str, default=None):
    return FEATURE_ANCHORS_BY_LEVEL.get(int(level), {}).get(str(name), default)


def get_level_anchors(level: int) -> dict[str, tuple[int, int] | tuple[int, int, int, int]]:
    return dict(FEATURE_ANCHORS_BY_LEVEL.get(int(level), {}))


def ensure_np_grid(grid):
    """Return an int8 numpy grid for either ndarray or grid_hex_rows/list input."""
    if isinstance(grid, np.ndarray):
        return np.array(grid, dtype=np.int8, copy=True)
    if isinstance(grid, dict):
        rows = grid.get("grid_hex_rows")
        if isinstance(rows, list):
            grid = rows
    if isinstance(grid, list):
        if grid and all(isinstance(row, str) for row in grid):
            return np.array([[int(ch, 16) for ch in row] for row in grid], dtype=np.int8)
        return np.array(grid, dtype=np.int8)
    raise RuntimeError(f"unsupported grid type: {type(grid)}")


def grid_to_hex_rows(grid):
    arr = ensure_np_grid(grid)
    return ["".join(f"{int(v):X}" for v in row) for row in arr]


def find_color_positions(grid, color):
    arr = ensure_np_grid(grid)
    target = int(color)
    pts = np.argwhere(arr == target)
    return [(int(r), int(c)) for r, c in pts]


# Deterministic route helper for known geometry only.
# Use this after mechanics are known; do not use as broad unknown-state search.
ACTION_DELTAS = {
    1: (-5, 0),
    2: (5, 0),
    3: (0, -5),
    4: (0, 5),
}


def shortest_path_actions_known_geometry(
    walkable_mask: np.ndarray,
    start: tuple[int, int],
    goal: tuple[int, int],
    *,
    player_size: int = 5,
) -> list[int]:
    """Return deterministic shortest action list on fixed, known geometry.

    `start` and `goal` are player top-left positions in grid coordinates.
    """
    start = (int(start[0]), int(start[1]))
    goal = (int(goal[0]), int(goal[1]))
    if start == goal:
        return []
    rows, cols = walkable_mask.shape

    def can_move(pos: tuple[int, int], action_id: int) -> tuple[int, int] | None:
        dr, dc = ACTION_DELTAS[action_id]
        nr, nc = pos[0] + dr, pos[1] + dc
        if nr < 0 or nc < 0 or nr + player_size > rows or nc + player_size > cols:
            return None
        if not bool(walkable_mask[nr : nr + player_size, nc : nc + player_size].all()):
            return None
        return (nr, nc)

    q = deque([start])
    prev: dict[tuple[int, int], tuple[tuple[int, int], int] | None] = {start: None}
    while q:
        cur = q.popleft()
        for action_id in (1, 2, 3, 4):
            nxt = can_move(cur, action_id)
            if nxt is None or nxt in prev:
                continue
            prev[nxt] = (cur, action_id)
            if nxt == goal:
                q.clear()
                break
            q.append(nxt)

    if goal not in prev:
        return []
    out: list[int] = []
    cur = goal
    while cur != start:
        parent, action_id = prev[cur]  # type: ignore[misc]
        out.append(action_id)
        cur = parent
    out.reverse()
    return out


def apply_shared_model_mechanics(env, action, *, data=None, reasoning=None) -> None:
    """Shared model-side mechanics hook used by model.py.

    Add reusable, evidence-backed mechanics here and call them from model.py.
    """
    _ = env, action, data, reasoning
