from __future__ import annotations

from typing import Any

import numpy as np
from arcengine.enums import FrameDataRaw


def _same_game_lineage(
    existing_game_id: str,
    requested_game_id: str,
    make_id_candidates,
) -> bool:
    a = str(existing_game_id).strip()
    b = str(requested_game_id).strip()
    if not a or not b:
        return True
    if a == b:
        return True
    a_candidates = set(make_id_candidates(a))
    b_candidates = set(make_id_candidates(b))
    return bool(a_candidates.intersection(b_candidates))


def _grid_from_hex_rows(rows: list[str]) -> np.ndarray:
    parsed: list[list[int]] = []
    for row in rows:
        if not isinstance(row, str):
            raise RuntimeError("hex rows must contain strings")
        parsed.append([int(ch, 16) for ch in row.strip()])
    arr = np.array(parsed, dtype=np.int16)
    if arr.ndim != 2:
        raise RuntimeError("hex rows must form a 2D grid")
    return arr


def _chunk_for_bbox(grid: np.ndarray, bbox: dict | None, *, pad: int = 0) -> dict:
    if bbox is None:
        return {"bbox": None, "rows_hex": []}
    rows, cols = grid.shape
    r0 = max(0, int(bbox["min_row"]) - pad)
    r1 = min(rows - 1, int(bbox["max_row"]) + pad)
    c0 = max(0, int(bbox["min_col"]) - pad)
    c1 = min(cols - 1, int(bbox["max_col"]) + pad)
    view = grid[r0 : r1 + 1, c0 : c1 + 1]
    hex_rows = ["".join(f"{int(v):X}" for v in row) for row in view]
    return {
        "bbox": {
            "min_row": r0,
            "max_row": r1,
            "min_col": c0,
            "max_col": c1,
        },
        "rows_hex": hex_rows,
    }


def _coerce_grid(state_like: Any, current_grid: np.ndarray | None = None) -> np.ndarray:
    if state_like is None:
        if current_grid is None:
            raise RuntimeError("no state provided and no current grid available")
        return np.array(current_grid, copy=True)

    if isinstance(state_like, np.ndarray):
        return np.array(state_like, copy=True)

    if isinstance(state_like, FrameDataRaw):
        return _frame_pixels_from_raw(state_like)

    if isinstance(state_like, list):
        if state_like and all(isinstance(x, str) for x in state_like):
            return _grid_from_hex_rows(state_like)
        return np.array(state_like)

    if isinstance(state_like, dict):
        if "grid_hex_rows" in state_like and isinstance(state_like["grid_hex_rows"], list):
            return _grid_from_hex_rows(state_like["grid_hex_rows"])
        if "frame" in state_like:
            frame = state_like["frame"]
            if isinstance(frame, list) and frame and isinstance(frame[0], list):
                return np.array(frame[0])

    if hasattr(state_like, "frame"):
        frame = getattr(state_like, "frame")
        if isinstance(frame, (list, tuple)) and frame and isinstance(frame[0], np.ndarray):
            return np.array(frame[0], copy=True)

    raise RuntimeError(f"unsupported state type for diff(): {type(state_like)!r}")


def _frame_pixels_from_raw(frame: FrameDataRaw) -> np.ndarray:
    data = getattr(frame, "frame", None)
    if isinstance(data, (list, tuple)) and data:
        pixels = data[-1]
        if isinstance(pixels, np.ndarray):
            return np.array(pixels, copy=True)
        return np.array(pixels)
    raise RuntimeError(
        "FrameDataRaw.frame is unavailable; cannot compute authoritative diff/state grid."
    )
