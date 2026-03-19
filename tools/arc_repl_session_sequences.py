from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import numpy as np

CANONICAL_INITIAL_STATE_SOURCES = {
    "session_bootstrap_reset",
    "level_transition_after_state",
    "reset_level_after_state",
}


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


def _state_rows_equal(left: list[str] | None, right: list[str] | None) -> bool:
    return list(left or []) == list(right or [])


def _candidate_for_level(*, level: int, rows: list[str], rec: dict, source: str) -> dict:
    return {
        "level": int(level),
        "rows": list(rows),
        "source": str(source),
        "source_action_index": int(rec.get("action_index", 0) or 0),
        "source_action_name": str(rec.get("action_name", "")),
        "source_recorded_at_utc": str(rec.get("recorded_at_utc", "")),
    }


def _assert_matching_candidates(*, level: int, candidates: list[dict], message_prefix: str) -> None:
    normalized = [candidate for candidate in candidates if isinstance(candidate, dict)]
    if len(normalized) < 2:
        return
    first = normalized[0]
    for other in normalized[1:]:
        if _state_rows_equal(first.get("rows"), other.get("rows")):
            continue
        raise RuntimeError(
            f"{message_prefix} for level {int(level)}: "
            f"{first.get('source')}@{first.get('source_action_index')} "
            f"!= {other.get('source')}@{other.get('source_action_index')}"
        )


def _load_existing_canonical_candidates(game_dir: Path) -> dict[int, dict]:
    candidates: dict[int, dict] = {}
    for level_dir in sorted(game_dir.glob("level_*")):
        if not level_dir.is_dir():
            continue
        try:
            level = int(level_dir.name.split("_", 1)[1])
        except Exception:
            continue
        init_path = level_dir / "initial_state.hex"
        meta_path = level_dir / "initial_state.meta.json"
        if not init_path.exists() or not meta_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        source = str(meta.get("initial_state_source") or meta.get("source") or "").strip()
        if source not in CANONICAL_INITIAL_STATE_SOURCES:
            continue
        rows = [line.strip().upper() for line in init_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not rows:
            continue
        candidates[level] = {
            "level": int(level),
            "rows": rows,
            "source": source,
            "source_action_index": int(meta.get("source_action_index", 0) or 0),
            "source_action_name": str(meta.get("source_action_name", "")),
            "source_recorded_at_utc": str(meta.get("source_recorded_at_utc", "")),
        }
    return candidates


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
    existing_canonical_by_level = _load_existing_canonical_candidates(levels_root)
    reset_after_rows_by_level: dict[int, dict] = {}
    transition_after_rows_by_level: dict[int, dict] = {}
    observed_levels: set[int] = set(existing_canonical_by_level)

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
        state_before_name = str(rec.get("state_before", {}).get("state", "")).strip().upper()
        state_after = str(rec.get("state_after", {}).get("state", "")).strip().upper()
        state_before_rows = list(rec.get("state_before", {}).get("grid_hex_rows", []) or [])
        state_after_rows = list(rec.get("state_after", {}).get("grid_hex_rows", []) or [])
        observed_levels.add(level_before)
        observed_levels.add(level_after)

        if action_name == "RESET_LEVEL" and state_after_rows:
            candidate = _candidate_for_level(
                level=level_before,
                rows=state_after_rows,
                rec=rec,
                source="reset_level_after_state",
            )
            existing = reset_after_rows_by_level.get(level_before)
            if existing is None:
                reset_after_rows_by_level[level_before] = candidate
            else:
                _assert_matching_candidates(
                    level=level_before,
                    candidates=[existing, candidate],
                    message_prefix="inconsistent RESET_LEVEL start state",
                )
        if action_name == "RESET_LEVEL":
            close_active(rec=rec, reason="reset_level")
            continue

        if active is None or int(active.get("level", -1)) != level_before:
            close_active(rec=rec, reason="level_change")
            active = start_sequence(rec)

        if level_after != level_before and state_after_rows:
            candidate = _candidate_for_level(
                level=level_after,
                rows=state_after_rows,
                rec=rec,
                source="level_transition_after_state",
            )
            existing = transition_after_rows_by_level.get(level_after)
            if existing is None:
                transition_after_rows_by_level[level_after] = candidate
            else:
                _assert_matching_candidates(
                    level=level_after,
                    candidates=[existing, candidate],
                    message_prefix="inconsistent level-transition start state",
                )

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
                "level_complete_before": bool(rec.get("level_complete_before", False)),
                "level_complete_after": bool(
                    rec.get("level_complete_after", levels_after > levels_before or state_after == "WIN")
                ),
                "game_over_before": bool(rec.get("game_over_before", state_before_name == "GAME_OVER")),
                "game_over_after": bool(rec.get("game_over_after", state_after == "GAME_OVER")),
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

    for level in sorted(observed_levels):
        existing_observed = existing_canonical_by_level.get(level)
        reset_observed = reset_after_rows_by_level.get(level)
        transition_observed = transition_after_rows_by_level.get(level)
        if existing_observed is not None and transition_observed is not None:
            _assert_matching_candidates(
                level=level,
                candidates=[existing_observed, transition_observed],
                message_prefix="existing canonical state does not match transition start",
            )
        if existing_observed is not None and reset_observed is not None:
            _assert_matching_candidates(
                level=level,
                candidates=[existing_observed, reset_observed],
                message_prefix="existing canonical state does not match reset start",
            )
        if transition_observed is not None and reset_observed is not None:
            _assert_matching_candidates(
                level=level,
                candidates=[transition_observed, reset_observed],
                message_prefix="reset state does not match canonical level start",
            )
        canonical = transition_observed or reset_observed or existing_observed
        if canonical is None:
            raise RuntimeError(
                f"missing canonical initial state for level {int(level)}: "
                "no session bootstrap, level transition, or reset snapshot was captured"
            )
        level_dir = levels_root / f"level_{int(level)}"
        level_dir.mkdir(parents=True, exist_ok=True)
        initial_state = grid_from_hex_rows(list(canonical.get("rows", []) or []))
        write_hex_grid(level_dir / "initial_state.hex", initial_state)
        init_meta = {
            "schema_version": "arc_repl.level_initial_state.v1",
            "game_id": str(session.game_id),
            "level": int(level),
            "rows": int(initial_state.shape[0]),
            "cols": int(initial_state.shape[1]) if initial_state.ndim == 2 else 0,
            "initial_state_source": str(canonical.get("source", "")),
            "source_action_index": int(canonical.get("source_action_index", 0) or 0),
            "source_action_name": str(canonical.get("source_action_name", "")),
            "source_recorded_at_utc": str(canonical.get("source_recorded_at_utc", "")),
            "provisional": False,
            "reset_verified": reset_observed is not None,
        }
        if transition_observed is not None:
            init_meta["transition_source_action_index"] = int(
                transition_observed.get("source_action_index", 0) or 0
            )
        if reset_observed is not None:
            init_meta["reset_source_action_index"] = int(
                reset_observed.get("source_action_index", 0) or 0
            )
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
