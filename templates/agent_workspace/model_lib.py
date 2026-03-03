"""Reusable helpers for model.py internals.

This file is imported by model.py at startup and its helpers are injected into
model.py exec globals. Keep this focused on modeling abstractions and mechanics.
"""

from __future__ import annotations

import numpy as np


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


def apply_shared_model_mechanics(env, action, *, data=None, reasoning=None) -> None:
    """Shared model-side mechanics hook used by model.py.

    Replace this placeholder with reusable, evidence-backed model logic.
    """
    _ = env, action, data, reasoning
