from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
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


def model_status_path(game_dir: Path) -> Path:
    return game_dir / "model_status.json"


def analysis_level_pin_path(game_dir: Path) -> Path:
    return game_dir / ".analysis_level_pin.json"


def load_analysis_level_pin(game_dir: Path) -> dict | None:
    path = analysis_level_pin_path(game_dir)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def write_analysis_level_pin(game_dir: Path, *, level: int, phase: str, reason: str) -> None:
    payload = {
        "schema_version": "arc.analysis_level_pin.v1",
        "level": int(level),
        "phase": str(phase),
        "reason": str(reason),
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    path = analysis_level_pin_path(game_dir)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n")
    tmp.replace(path)


def update_analysis_level_pin(game_dir: Path, updates: dict) -> dict | None:
    current = load_analysis_level_pin(game_dir)
    if not isinstance(current, dict):
        return None
    current.update(dict(updates))
    current["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
    path = analysis_level_pin_path(game_dir)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(current, indent=2) + "\n")
    tmp.replace(path)
    return current


def clear_analysis_level_pin(game_dir: Path) -> None:
    analysis_level_pin_path(game_dir).unlink(missing_ok=True)


def arc_state_json_path() -> Path | None:
    state_dir = str(os.getenv("ARC_STATE_DIR", "") or "").strip()
    if not state_dir:
        return None
    return Path(state_dir).expanduser() / "state.json"


def load_frontier_level_from_arc_state() -> int | None:
    state_path = arc_state_json_path()
    if state_path is None or not state_path.exists():
        return None
    try:
        payload = json.loads(state_path.read_text())
    except Exception:
        return None
    try:
        return int(payload.get("current_level"))
    except Exception:
        return None


def grid_from_hex_rows(rows: list[str]) -> np.ndarray:
    if not rows:
        return np.zeros((0, 0), dtype=np.int8)
    return np.array([[int(ch, 16) for ch in row.strip()] for row in rows], dtype=np.int8)


def grid_hex_rows(grid: np.ndarray) -> list[str]:
    return ["".join(f"{int(v):X}" for v in row) for row in np.asarray(grid, dtype=np.int8)]


def read_hex_grid(path: Path) -> np.ndarray:
    rows = [line.strip().upper() for line in path.read_text().splitlines() if line.strip()]
    return grid_from_hex_rows(rows)


def _state_artifacts_root_for_active_game() -> Path | None:
    state_dir = str(os.getenv("ARC_STATE_DIR", "") or "").strip()
    game_id = str(os.getenv("ARC_ACTIVE_GAME_ID", "") or "").strip()
    if not state_dir or not game_id:
        return None
    safe = sanitize_game_id(game_id)
    return Path(state_dir).expanduser() / "game_artifacts" / f"game_{safe}"


def _level_current_matches(level_current: Path, level: int) -> bool:
    meta_candidates = [level_current / "meta.json", level_current / "initial_state.meta.json"]
    for meta_path in meta_candidates:
        if not meta_path.exists():
            continue
        try:
            payload = json.loads(meta_path.read_text())
        except Exception:
            continue
        try:
            parsed = int(payload.get("level"))
        except Exception:
            continue
        if parsed == int(level):
            return True
    return False


def _iter_level_directories(game_dir: Path) -> list[Path]:
    dirs: dict[int, Path] = {}
    roots = [game_dir, game_dir / "levels"]
    state_root = _state_artifacts_root_for_active_game()
    if state_root is not None:
        roots.extend([state_root, state_root / "levels"])
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
    level_current = game_dir / "level_current"
    if level_current.exists() and level_current.is_dir():
        for lvl in sorted(dirs):
            if _level_current_matches(level_current, lvl):
                dirs[lvl] = level_current
                break
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
    state_root = _state_artifacts_root_for_active_game()
    if state_root is not None:
        candidates.extend([state_root / target_name, state_root / "levels" / target_name])
    for candidate in candidates:
        if candidate.exists() and candidate.is_dir():
            return candidate
    level_current = game_dir / "level_current"
    if level_current.exists() and level_current.is_dir():
        if _level_current_matches(level_current, int(level)):
            return level_current
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
