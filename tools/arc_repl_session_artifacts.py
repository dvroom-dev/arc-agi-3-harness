from __future__ import annotations

import json
from pathlib import Path
import re
import shutil

import numpy as np


def steps_since_level_start(events: list[dict]) -> int:
    steps_in_level = 0
    current_levels = 0
    for event in events:
        kind = str(event.get("kind", "")).strip()
        if kind == "reset":
            steps_in_level = 0
            continue
        if kind != "step":
            continue
        try:
            levels_now = int(event.get("levels_completed", current_levels))
        except Exception:
            levels_now = current_levels
        if levels_now != current_levels:
            steps_in_level = 0
        else:
            steps_in_level += 1
        current_levels = levels_now
    return steps_in_level


def write_state_artifacts(
    session,
    *,
    action_label: str,
    state_before_action: str | None,
    levels_before_action: int | None,
    script_output: str,
    error: str,
    pre_pixels: np.ndarray | None,
    step_snapshots: list[tuple[str, np.ndarray]],
    step_results: list[dict] | None,
) -> Path:
    final_pixels = session.pixels
    session.deps.write_game_state(
        session.arc_dir / "game-state.md",
        session.frame,
        final_pixels,
        game_id=session.game_id,
        last_action=action_label,
        script_output=script_output,
        error=error,
        step_snapshots=step_snapshots,
        pre_turn_pixels=pre_pixels,
        step_results=step_results,
    )
    session.deps.write_machine_state(
        session.arc_dir,
        session.frame,
        final_pixels,
        game_id=session.game_id,
        last_action=action_label,
        step_snapshots=step_snapshots,
    )
    trace_path = session.deps._write_turn_trace(
        arc_dir=session.arc_dir,
        turn=session.turn,
        action_name=action_label,
        pre_pixels=pre_pixels,
        step_snapshots=step_snapshots,
        step_results=step_results,
        final_pixels=final_pixels,
        script_output=script_output,
        error=error,
    )
    _write_level_turn_files(
        session=session,
        action_label=action_label,
        state_before_action=state_before_action,
        levels_before_action=levels_before_action,
        pre_pixels=pre_pixels,
        step_snapshots=step_snapshots,
        step_results=step_results,
        final_pixels=final_pixels,
        trace_path=trace_path,
    )
    return trace_path


def _safe_dir_name(value: str) -> str:
    raw = str(value or "").strip()
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("._")
    return safe or "game"


def _canonical_game_artifacts_dir(session) -> Path:
    safe_game = _safe_dir_name(str(session.game_id))
    root = session.arc_dir / "game_artifacts" / f"game_{safe_game}"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _remove_path(path: Path) -> None:
    if not path.exists() and not path.is_symlink():
        return
    if path.is_symlink() or path.is_file():
        try:
            path.unlink()
        except Exception:
            pass
        return
    shutil.rmtree(path, ignore_errors=True)


def _materialize_level_current_view(
    *,
    session,
    agent_game_dir: Path,
    artifacts_game_dir: Path,
    current_level: int,
) -> None:
    src = artifacts_game_dir / f"level_{int(current_level)}"
    if not src.exists() or not src.is_dir():
        return

    agent_game_dir.mkdir(parents=True, exist_ok=True)
    level_current = agent_game_dir / "level_current"
    temp = agent_game_dir / ".level_current.tmp"
    _remove_path(temp)
    shutil.copytree(src, temp)
    (temp / "meta.json").write_text(
        json.dumps(
            {
                "schema_version": "arc_repl.level_current.v1",
                "game_id": str(session.game_id),
                "level": int(current_level),
                "source": str(src),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    _remove_path(level_current)
    temp.rename(level_current)

    for child in agent_game_dir.iterdir():
        if child.name == "level_current":
            continue
        if child.name.startswith("level_"):
            _remove_path(child)

    compat_level = agent_game_dir / f"level_{int(current_level)}"
    _remove_path(compat_level)
    try:
        compat_level.symlink_to(level_current.name, target_is_directory=True)
    except Exception:
        shutil.copytree(level_current, compat_level)

    stale_turn_index = agent_game_dir / "turn_index.jsonl"
    if stale_turn_index.exists():
        _remove_path(stale_turn_index)


def _grid_hex_rows(grid: np.ndarray) -> list[str]:
    return ["".join(f"{int(v):X}" for v in row) for row in grid]


def _write_hex_grid(path: Path, grid: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(_grid_hex_rows(grid)) + "\n")


def _build_diff_hex_rows(before_grid: np.ndarray, after_grid: np.ndarray) -> list[str]:
    out: list[str] = []
    for r in range(before_grid.shape[0]):
        chars: list[str] = []
        for c in range(before_grid.shape[1]):
            before = int(before_grid[r, c])
            after = int(after_grid[r, c])
            chars.append("." if before == after else f"{after:X}")
        out.append("".join(chars))
    return out


def _write_level_turn_files(
    *,
    session,
    action_label: str,
    state_before_action: str | None,
    levels_before_action: int | None,
    pre_pixels: np.ndarray | None,
    step_snapshots: list[tuple[str, np.ndarray]],
    step_results: list[dict] | None,
    final_pixels: np.ndarray,
    trace_path: Path,
) -> None:
    agent_game_dir = session.play_lib_file.parent
    artifacts_game_dir = _canonical_game_artifacts_dir(session)
    level_number = (
        int(levels_before_action) + 1
        if isinstance(levels_before_action, int)
        else int(session.frame.levels_completed) + 1
    )
    level_dir = artifacts_game_dir / f"level_{level_number}"
    turn_dir = level_dir / f"turn_{int(session.turn):04d}"
    turn_dir.mkdir(parents=True, exist_ok=True)

    before_grid = np.array(pre_pixels if pre_pixels is not None else final_pixels, copy=True)
    after_grid = np.array(final_pixels, copy=True)
    _write_hex_grid(turn_dir / "before_state.hex", before_grid)
    _write_hex_grid(turn_dir / "after_state.hex", after_grid)
    _write_hex_grid(level_dir / "current_state.hex", after_grid)

    aggregate_diff = session.deps.build_aggregate_diff_record(
        pre_turn_pixels=pre_pixels,
        final_pixels=after_grid,
        step_snapshots=step_snapshots,
        step_results=step_results,
    )
    diff_baseline = before_grid
    if bool(aggregate_diff.get("suppressed_cross_level_diff", False)):
        try:
            baseline_step = int(aggregate_diff.get("aggregate_baseline_step", 0) or 0)
        except Exception:
            baseline_step = 0
        if baseline_step > 0 and baseline_step <= len(step_snapshots):
            diff_baseline = np.array(step_snapshots[baseline_step - 1][1], copy=True)
    diff_rows = _build_diff_hex_rows(diff_baseline, after_grid)
    (turn_dir / "diff.hex").write_text("\n".join(diff_rows) + "\n")

    changed_pixels = aggregate_diff.get("changed_pixels")
    if not isinstance(changed_pixels, int):
        changed_pixels = 0
    try:
        trace_rel = str(trace_path.relative_to(session.cwd))
    except Exception:
        trace_rel = str(trace_path)
    meta = {
        "schema_version": "arc_repl.level_turn_artifact.v1",
        "game_id": str(session.game_id),
        "game_dir": str(agent_game_dir),
        "artifacts_dir": str(artifacts_game_dir),
        "action_label": str(action_label),
        "tool_turn": int(session.turn),
        "level_before": level_number,
        "level_after": int(session.frame.levels_completed) + 1,
        "levels_completed_before": (
            int(levels_before_action)
            if isinstance(levels_before_action, int)
            else int(session.frame.levels_completed)
        ),
        "levels_completed_after": int(session.frame.levels_completed),
        "state_before_action": str(state_before_action or ""),
        "state_after_action": str(session.frame.state.value),
        "steps_executed": len(step_snapshots),
        "changed_pixels": int(changed_pixels),
        "suppressed_cross_level_diff": bool(
            aggregate_diff.get("suppressed_cross_level_diff", False)
        ),
        "aggregate_baseline_step": aggregate_diff.get("aggregate_baseline_step"),
        "trace_file": trace_rel,
        "files": {
            "before_state_hex": "before_state.hex",
            "after_state_hex": "after_state.hex",
            "diff_hex": "diff.hex",
        },
    }
    (turn_dir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")

    # Per-level append-only index, plus game-wide index for quick scan.
    level_index = level_dir / "turn_index.jsonl"
    game_index = artifacts_game_dir / "turn_index.jsonl"
    entry = {
        "tool_turn": int(session.turn),
        "level": level_number,
        "action_label": str(action_label),
        "state_before_action": str(state_before_action or ""),
        "state_after_action": str(session.frame.state.value),
        "steps_executed": len(step_snapshots),
        "changed_pixels": int(changed_pixels),
        "turn_dir": f"level_{level_number}/turn_{int(session.turn):04d}",
    }
    for idx in (level_index, game_index):
        idx.parent.mkdir(parents=True, exist_ok=True)
        with idx.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=True) + "\n")

    _sync_level_sequences(session=session, game_dir=artifacts_game_dir)
    current_level = int(session.frame.levels_completed) + 1
    _materialize_level_current_view(
        session=session,
        agent_game_dir=agent_game_dir,
        artifacts_game_dir=artifacts_game_dir,
        current_level=current_level,
    )


def _grid_from_hex_rows(rows: list[str]) -> np.ndarray:
    if not rows:
        return np.zeros((0, 0), dtype=np.int8)
    return np.array([[int(ch, 16) for ch in row] for row in rows], dtype=np.int8)


def _safe_action_slug(name: str) -> str:
    raw = str(name or "").strip().lower()
    safe = re.sub(r"[^a-z0-9_.-]+", "_", raw).strip("._")
    return safe or "action"


def _sync_level_sequences(*, session, game_dir: Path) -> None:
    records = list(getattr(session.action_history, "records", []))
    levels_root = game_dir
    levels_root.mkdir(parents=True, exist_ok=True)

    # Regenerate sequence artifacts deterministically from action-history.
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
            # A transition action often lands on the next level's initial state.
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
        initial_state = _grid_from_hex_rows(rows)
        _write_hex_grid(level_dir / "initial_state.hex", initial_state)
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
            before_grid = _grid_from_hex_rows(action["before_rows"])
            after_grid = _grid_from_hex_rows(action["after_rows"])
            slug = _safe_action_slug(action.get("action_name", "action"))
            step_dir = actions_root / (
                f"step_{int(action['local_step']):04d}_"
                f"action_{int(action['action_index']):06d}_{slug}"
            )
            step_dir.mkdir(parents=True, exist_ok=True)
            _write_hex_grid(step_dir / "before_state.hex", before_grid)
            _write_hex_grid(step_dir / "after_state.hex", after_grid)
            diff_rows = _build_diff_hex_rows(before_grid, after_grid)
            (step_dir / "diff.hex").write_text("\n".join(diff_rows) + "\n")

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
                    "diff_hex": "diff.hex",
                },
            }
            (step_dir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")

            action["files"] = {
                "before_state_hex": str(step_dir.relative_to(level_dir) / "before_state.hex"),
                "after_state_hex": str(step_dir.relative_to(level_dir) / "after_state.hex"),
                "diff_hex": str(step_dir.relative_to(level_dir) / "diff.hex"),
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


def save_level_completion_records(
    session,
    *,
    levels_before_exec: int,
    script_source: str,
) -> str | None:
    levels_after_exec = int(session.frame.levels_completed)
    if levels_after_exec <= levels_before_exec:
        return None

    scripts_dir = session.arc_dir / "script-history"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    script_file = scripts_dir / f"turn_{session.turn:03d}_script.py"
    script_file.write_text(script_source)

    max_recorded = session.deps._read_max_recorded_completion_level(session.completions_path)
    completion_windows = session.deps._completion_action_windows_by_level(session.events)

    try:
        script_rel = str(script_file.relative_to(session.cwd))
    except Exception:
        script_rel = str(script_file)

    for completed_level in range(levels_before_exec + 1, levels_after_exec + 1):
        if completed_level <= max_recorded:
            continue
        actions = completion_windows.get(completed_level, [])
        session.deps._append_level_completion(
            path=session.completions_path,
            completed_level=completed_level,
            actions=actions,
            tool_turn=session.turn,
            winning_script_relpath=script_rel,
        )
        max_recorded = completed_level
    return script_rel
