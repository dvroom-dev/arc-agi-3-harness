from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import numpy as np


def grid_from_hex_rows(rows: list[str]) -> np.ndarray:
    if not rows:
        return np.zeros((0, 0), dtype=np.int8)
    return np.array([[int(ch, 16) for ch in row] for row in rows], dtype=np.int8)


def write_hex_grid(path: Path, grid: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = ["".join(f"{int(v):X}" for v in row) for row in grid]
    path.write_text("\n".join(rows) + "\n")


def _safe_action_slug(name: str) -> str:
    raw = str(name or "").strip().lower()
    safe = re.sub(r"[^a-z0-9_.-]+", "_", raw).strip("._")
    return safe or "action"


def sync_level_sequences(*, session, game_dir: Path) -> None:
    records = list(getattr(session.action_history, "records", []))
    levels_root = game_dir
    levels_root.mkdir(parents=True, exist_ok=True)

    for level_dir in levels_root.glob("level_*"):
        seq_root = level_dir / "sequences"
        if not seq_root.exists():
            continue
        for child in seq_root.iterdir():
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            elif child.is_file() and child.suffix.lower() == ".json":
                try:
                    child.unlink()
                except Exception:
                    pass

    sequences: list[dict] = []
    active: dict | None = None
    next_seq_number_by_level: dict[int, int] = {}
    first_before_rows_by_level: dict[int, list[str]] = {}

    def start_sequence(rec: dict) -> dict:
        level = int(rec.get("level_before", 1) or 1)
        seq_num = next_seq_number_by_level.get(level, 0) + 1
        next_seq_number_by_level[level] = seq_num
        return {
            "schema_version": "arc_repl.level_sequence.v1",
            "game_id": str(session.game_id),
            "level": level,
            "sequence_id": f"seq_{seq_num:04d}",
            "sequence_number": seq_num,
            "start_action_index": int(rec.get("action_index", 0) or 0),
            "start_recorded_at_utc": str(rec.get("recorded_at_utc", "")),
            "end_action_index": None,
            "end_recorded_at_utc": "",
            "end_reason": "open",
            "actions": [],
        }

    def close_active(*, rec: dict | None, reason: str) -> None:
        nonlocal active
        if active is None:
            return
        if rec is not None:
            active["end_action_index"] = int(rec.get("action_index", 0) or 0)
            active["end_recorded_at_utc"] = str(rec.get("recorded_at_utc", ""))
        elif active["actions"]:
            last = active["actions"][-1]
            active["end_action_index"] = int(last.get("action_index", 0) or 0)
            active["end_recorded_at_utc"] = str(last.get("recorded_at_utc", ""))
        active["end_reason"] = str(reason)
        if active["actions"]:
            sequences.append(active)
        active = None

    for rec in records:
        action_name = str(rec.get("action_name", "")).strip().upper()
        level_before = int(rec.get("level_before", 1) or 1)
        level_after = int(rec.get("level_after", level_before) or level_before)
        levels_before = int(rec.get("levels_completed_before", 0) or 0)
        levels_after = int(rec.get("levels_completed_after", levels_before) or levels_before)
        state_after = str(rec.get("state_after", {}).get("state", "")).strip().upper()
        state_before_rows = list(rec.get("state_before", {}).get("grid_hex_rows", []) or [])
        state_after_rows = list(rec.get("state_after", {}).get("grid_hex_rows", []) or [])

        if action_name == "RESET_LEVEL":
            close_active(rec=rec, reason="reset_level")
            continue

        if active is None or int(active.get("level", -1)) != level_before:
            close_active(rec=rec, reason="level_change")
            active = start_sequence(rec)

        if level_before not in first_before_rows_by_level and state_before_rows:
            first_before_rows_by_level[level_before] = state_before_rows
        if (
            level_after != level_before
            and level_after not in first_before_rows_by_level
            and state_after_rows
        ):
            first_before_rows_by_level[level_after] = state_after_rows

        local_step = len(active["actions"]) + 1
        active["actions"].append(
            {
                "local_step": int(local_step),
                "action_index": int(rec.get("action_index", 0) or 0),
                "tool_turn": int(rec.get("tool_turn", 0) or 0),
                "step_in_call": int(rec.get("step_in_call", 0) or 0),
                "call_action": str(rec.get("call_action", "")),
                "action_name": str(rec.get("action_name", "")),
                "action_data": rec.get("action_data", {}),
                "recorded_at_utc": str(rec.get("recorded_at_utc", "")),
                "state_before": str(rec.get("state_before", {}).get("state", "")),
                "state_after": str(rec.get("state_after", {}).get("state", "")),
                "level_before": level_before,
                "level_after": level_after,
                "levels_completed_before": levels_before,
                "levels_completed_after": levels_after,
                "before_rows": state_before_rows,
                "after_rows": state_after_rows,
                "files": {},
            }
        )

        if level_after != level_before or levels_after != levels_before:
            close_active(rec=rec, reason="level_change")
            continue
        if state_after in {"WIN", "GAME_OVER"}:
            close_active(rec=rec, reason=state_after.lower())

    close_active(rec=None, reason="open")

    for level, rows in first_before_rows_by_level.items():
        level_dir = levels_root / f"level_{int(level)}"
        level_dir.mkdir(parents=True, exist_ok=True)
        initial_state = grid_from_hex_rows(rows)
        write_hex_grid(level_dir / "initial_state.hex", initial_state)
        init_meta = {
            "schema_version": "arc_repl.level_initial_state.v1",
            "game_id": str(session.game_id),
            "level": int(level),
            "rows": int(initial_state.shape[0]),
            "cols": int(initial_state.shape[1]) if initial_state.ndim == 2 else 0,
            "source": "action_history_first_before_state",
        }
        (level_dir / "initial_state.meta.json").write_text(json.dumps(init_meta, indent=2) + "\n")

    for seq in sequences:
        level = int(seq["level"])
        level_dir = levels_root / f"level_{level}"
        seq_root = level_dir / "sequences"
        seq_root.mkdir(parents=True, exist_ok=True)
        seq_id = str(seq["sequence_id"])
        seq_dir = seq_root / seq_id
        actions_root = seq_dir / "actions"
        actions_root.mkdir(parents=True, exist_ok=True)

        for action in seq["actions"]:
            before_grid = grid_from_hex_rows(action["before_rows"])
            after_grid = grid_from_hex_rows(action["after_rows"])
            slug = _safe_action_slug(action.get("action_name", "action"))
            step_dir = actions_root / (
                f"step_{int(action['local_step']):04d}_"
                f"action_{int(action['action_index']):06d}_{slug}"
            )
            step_dir.mkdir(parents=True, exist_ok=True)
            write_hex_grid(step_dir / "before_state.hex", before_grid)
            write_hex_grid(step_dir / "after_state.hex", after_grid)

            meta = {
                "schema_version": "arc_repl.sequence_action.v1",
                "game_id": str(session.game_id),
                "level": level,
                "sequence_id": seq_id,
                "sequence_number": int(seq["sequence_number"]),
                "local_step": int(action["local_step"]),
                "action_index": int(action["action_index"]),
                "tool_turn": int(action["tool_turn"]),
                "step_in_call": int(action["step_in_call"]),
                "call_action": str(action["call_action"]),
                "action_name": str(action["action_name"]),
                "action_data": action.get("action_data", {}),
                "state_before": str(action["state_before"]),
                "state_after": str(action["state_after"]),
                "level_before": int(action["level_before"]),
                "level_after": int(action["level_after"]),
                "levels_completed_before": int(action["levels_completed_before"]),
                "levels_completed_after": int(action["levels_completed_after"]),
                "recorded_at_utc": str(action["recorded_at_utc"]),
                "files": {
                    "before_state_hex": "before_state.hex",
                    "after_state_hex": "after_state.hex",
                    "meta_json": "meta.json",
                },
            }
            (step_dir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")

            action["files"] = {
                "before_state_hex": str(step_dir.relative_to(level_dir) / "before_state.hex"),
                "after_state_hex": str(step_dir.relative_to(level_dir) / "after_state.hex"),
                "meta_json": str(step_dir.relative_to(level_dir) / "meta.json"),
            }
            action.pop("before_rows", None)
            action.pop("after_rows", None)

        seq["action_count"] = len(seq["actions"])
        seq_payload = {
            "schema_version": "arc_repl.level_sequence.v1",
            "game_id": str(seq["game_id"]),
            "level": int(seq["level"]),
            "sequence_id": str(seq["sequence_id"]),
            "sequence_number": int(seq["sequence_number"]),
            "start_action_index": int(seq["start_action_index"]),
            "end_action_index": int(seq["end_action_index"] or seq["start_action_index"]),
            "start_recorded_at_utc": str(seq["start_recorded_at_utc"]),
            "end_recorded_at_utc": str(seq["end_recorded_at_utc"]),
            "end_reason": str(seq["end_reason"]),
            "action_count": int(seq["action_count"]),
            "actions": seq["actions"],
        }
        (seq_root / f"{seq_id}.json").write_text(json.dumps(seq_payload, indent=2) + "\n")
