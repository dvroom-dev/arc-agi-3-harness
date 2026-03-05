from __future__ import annotations

import re
from pathlib import Path

import numpy as np
from arcengine import GameAction

_LEVEL_DIR_RE = re.compile(r"^level_(\d+)$")


def sanitize_game_id(game_id: str) -> str:
    text = str(game_id or "game")
    sanitized = re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("._")
    return sanitized or "game"


def session_state_path(game_dir: Path, game_id: str) -> Path:
    return game_dir / f".model_session_{sanitize_game_id(game_id)}.json"


def grid_from_hex_rows(rows: list[str]) -> np.ndarray:
    if not rows:
        return np.zeros((0, 0), dtype=np.int8)
    return np.array([[int(ch, 16) for ch in row.strip()] for row in rows], dtype=np.int8)


def grid_hex_rows(grid: np.ndarray) -> list[str]:
    return ["".join(f"{int(v):X}" for v in row) for row in np.asarray(grid, dtype=np.int8)]


def read_hex_grid(path: Path) -> np.ndarray:
    rows = [line.strip().upper() for line in path.read_text().splitlines() if line.strip()]
    return grid_from_hex_rows(rows)


def _iter_level_directories(game_dir: Path) -> list[Path]:
    dirs: dict[int, Path] = {}
    roots = [game_dir, game_dir / "levels"]
    for root in roots:
        if not root.exists() or not root.is_dir():
            continue
        for child in root.iterdir():
            if not child.is_dir():
                continue
            match = _LEVEL_DIR_RE.match(child.name)
            if not match:
                continue
            lvl = int(match.group(1))
            dirs.setdefault(lvl, child)
    return [dirs[k] for k in sorted(dirs)]


def discover_level_initial_states(game_dir: Path) -> dict[int, np.ndarray]:
    out: dict[int, np.ndarray] = {}
    for level_dir in _iter_level_directories(game_dir):
        match = _LEVEL_DIR_RE.match(level_dir.name)
        if not match:
            continue
        level = int(match.group(1))
        init_file = level_dir / "initial_state.hex"
        if not init_file.exists():
            continue
        out[level] = read_hex_grid(init_file)
    return out


def resolve_level_dir(game_dir: Path, level: int) -> Path | None:
    target_name = f"level_{int(level)}"
    candidates = [game_dir / target_name, game_dir / "levels" / target_name]
    for candidate in candidates:
        if candidate.exists() and candidate.is_dir():
            return candidate
    return None


def diff_payload(before: np.ndarray, after: np.ndarray) -> dict:
    if before.shape != after.shape:
        return {
            "shape_mismatch": True,
            "before_shape": [int(v) for v in before.shape],
            "after_shape": [int(v) for v in after.shape],
            "changed_pixels": None,
            "before_rows_hex": grid_hex_rows(before),
            "after_rows_hex": grid_hex_rows(after),
        }
    changed = np.argwhere(before != after)
    return {
        "shape_mismatch": False,
        "changed_pixels": int(len(changed)),
        "changes": [
            {
                "row": int(r),
                "col": int(c),
                "before": f"{int(before[r, c]):X}",
                "after": f"{int(after[r, c]):X}",
            }
            for r, c in changed
        ],
    }


def to_jsonable(value):
    if isinstance(value, np.ndarray):
        return {"__type__": "ndarray", "dtype": str(value.dtype), "data": value.tolist()}
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, GameAction):
        return {"__type__": "game_action", "value": int(value.value)}
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return {"__type__": "tuple", "items": [to_jsonable(v) for v in value]}
    if isinstance(value, set):
        return {"__type__": "set", "items": [to_jsonable(v) for v in sorted(value, key=repr)]}
    if isinstance(value, list):
        return [to_jsonable(v) for v in value]
    return value


def from_jsonable(value):
    if isinstance(value, list):
        return [from_jsonable(v) for v in value]
    if isinstance(value, dict):
        kind = value.get("__type__")
        if kind == "ndarray":
            return np.array(value.get("data", []), dtype=np.int8)
        if kind == "game_action":
            return GameAction(int(value.get("value", 0)))
        if kind == "tuple":
            return tuple(from_jsonable(v) for v in value.get("items", []))
        if kind == "set":
            return set(from_jsonable(v) for v in value.get("items", []))
        return {k: from_jsonable(v) for k, v in value.items()}
    return value


def action_from_name(name: str) -> GameAction:
    action_name = str(name or "").strip().upper()
    try:
        return getattr(GameAction, action_name)
    except Exception as exc:
        raise RuntimeError(f"unknown action name in sequence: {action_name!r}") from exc

