from __future__ import annotations

import json
from pathlib import Path
import re
import shutil

import numpy as np
from arc_model_runtime.utils import effective_analysis_level, sanitize_visible_level_tree
from arc_model_runtime.visible_artifacts import LEVEL_TRANSITION_FILE, level_transition_payload
from arc_model_runtime.io_utils import write_json_atomic, write_text_atomic

try:
    from arc_repl_session_sequences import (
        sync_level_sequences,
        write_hex_grid,
    )
except Exception:
    from tools.arc_repl_session_sequences import (
        sync_level_sequences,
        write_hex_grid,
    )


def _read_hex_rows_if_exists(path: Path) -> list[str] | None:
    if not path.exists():
        return None
    rows = [line.strip().upper() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return rows or None


def ensure_level_initial_state(
    *,
    session,
    level: int,
    grid: np.ndarray,
    source: str,
    source_action_index: int | None = None,
    source_action_name: str | None = None,
    source_recorded_at_utc: str | None = None,
    reset_verified: bool = False,
) -> Path:
    artifacts_game_dir = _canonical_game_artifacts_dir(session)
    level_dir = artifacts_game_dir / f"level_{int(level)}"
    level_dir.mkdir(parents=True, exist_ok=True)
    rows = ["".join(f"{int(v):X}" for v in row) for row in np.asarray(grid, dtype=np.int8)]
    initial_state_path = level_dir / "initial_state.hex"
    existing_rows = _read_hex_rows_if_exists(initial_state_path)
    if existing_rows is not None and existing_rows != rows:
        raise RuntimeError(
            f"canonical initial_state mismatch for level {int(level)}: "
            f"existing artifact differs from {str(source)}"
        )
    if existing_rows is None:
        write_hex_grid(initial_state_path, np.asarray(grid, dtype=np.int8))
    meta = {
        "schema_version": "arc_repl.level_initial_state.v1",
        "game_id": str(session.game_id),
        "level": int(level),
        "rows": int(np.asarray(grid, dtype=np.int8).shape[0]),
        "cols": int(np.asarray(grid, dtype=np.int8).shape[1]) if np.asarray(grid, dtype=np.int8).ndim == 2 else 0,
        "initial_state_source": str(source),
        "provisional": False,
        "reset_verified": bool(reset_verified),
    }
    if source_action_index is not None:
        meta["source_action_index"] = int(source_action_index)
    if source_action_name:
        meta["source_action_name"] = str(source_action_name)
    if source_recorded_at_utc:
        meta["source_recorded_at_utc"] = str(source_recorded_at_utc)
    (level_dir / "initial_state.meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return level_dir


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
        history_events=session.events,
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
    visible_level = effective_analysis_level(agent_game_dir, frontier_level=int(current_level))
    if visible_level is None:
        visible_level = int(current_level)
    src = artifacts_game_dir / f"level_{int(visible_level)}"
    if not src.exists() or not src.is_dir():
        return

    agent_game_dir.mkdir(parents=True, exist_ok=True)
    level_current = agent_game_dir / "level_current"
    temp = agent_game_dir / ".level_current.tmp"
    _remove_path(temp)
    shutil.copytree(src, temp)
    sanitize_visible_level_tree(temp, visible_level=int(visible_level))
    write_json_atomic(
        temp / "meta.json",
        {
            "schema_version": "arc_repl.level_current.v1",
            "game_id": str(session.game_id),
            "level": int(visible_level),
            "analysis_level_pinned": int(visible_level) != int(current_level),
        },
    )
    _remove_path(level_current)
    temp.rename(level_current)

    for child in agent_game_dir.iterdir():
        if child.name == "level_current":
            continue
        if child.name.startswith("level_"):
            _remove_path(child)

    compat_level = agent_game_dir / f"level_{int(visible_level)}"
    _remove_path(compat_level)
    try:
        compat_level.symlink_to(level_current.name, target_is_directory=True)
    except Exception:
        shutil.copytree(level_current, compat_level)

    stale_turn_index = agent_game_dir / "turn_index.jsonl"
    if stale_turn_index.exists():
        _remove_path(stale_turn_index)

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
    before_rows = ["".join(f"{int(v):X}" for v in row) for row in before_grid]
    after_rows = ["".join(f"{int(v):X}" for v in row) for row in after_grid]
    write_hex_grid(turn_dir / "before_state.hex", before_grid)
    write_hex_grid(turn_dir / "after_state.hex", after_grid)
    write_hex_grid(level_dir / "current_state.hex", after_grid)

    aggregate_diff = session.deps.build_aggregate_diff_record(
        pre_turn_pixels=pre_pixels,
        final_pixels=after_grid,
        step_snapshots=step_snapshots,
        step_results=step_results,
    )
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
        "level_complete_before": False,
        "level_complete_after": bool(
            int(
                int(session.frame.levels_completed)
                > (
                    int(levels_before_action)
                    if isinstance(levels_before_action, int)
                    else int(session.frame.levels_completed)
                )
            )
            or str(session.frame.state.value) == "WIN"
        ),
        "game_over_before": str(state_before_action or "") == "GAME_OVER",
        "game_over_after": str(session.frame.state.value) == "GAME_OVER",
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
            "meta_json": "meta.json",
        },
    }
    write_json_atomic(turn_dir / "meta.json", meta)
    if int(meta["level_after"]) > int(meta["level_before"]):
        write_json_atomic(
            turn_dir / LEVEL_TRANSITION_FILE,
            {
                **level_transition_payload(
                    visible_level=int(level_number),
                    redacted=False,
                    source_turn_dir=f"level_{level_number}/turn_{int(session.turn):04d}",
                ),
                "level_before": int(meta["level_before"]),
                "level_after": int(meta["level_after"]),
                "levels_completed_before": int(meta["levels_completed_before"]),
                "levels_completed_after": int(meta["levels_completed_after"]),
                "level_complete_before": bool(meta["level_complete_before"]),
                "level_complete_after": bool(meta["level_complete_after"]),
                "game_over_before": bool(meta["game_over_before"]),
                "game_over_after": bool(meta["game_over_after"]),
                "state_before_action": str(meta["state_before_action"]),
                "state_after_action": str(meta["state_after_action"]),
            },
        )

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
        existing = idx.read_text(encoding="utf-8") if idx.exists() else ""
        write_text_atomic(idx, existing + json.dumps(entry, ensure_ascii=True) + "\n")

    sync_level_sequences(session=session, game_dir=artifacts_game_dir)
    current_level = int(session.frame.levels_completed) + 1
    _materialize_level_current_view(
        session=session,
        agent_game_dir=agent_game_dir,
        artifacts_game_dir=artifacts_game_dir,
        current_level=current_level,
    )
    try:
        turn_dir_rel = str(turn_dir.relative_to(session.cwd))
    except Exception:
        turn_dir_rel = str(turn_dir)
    session.latest_turn_artifacts = {
        "level": int(level_number),
        "tool_turn": int(session.turn),
        "turn_dir": turn_dir_rel,
        "changed_pixels": int(changed_pixels),
        "before_state_hex_rows": before_rows,
        "before_state_hex": "\n".join(before_rows),
        "after_state_hex_rows": after_rows,
        "after_state_hex": "\n".join(after_rows),
        "files": {
            "before_state_hex": f"{turn_dir_rel}/before_state.hex",
            "after_state_hex": f"{turn_dir_rel}/after_state.hex",
            "meta_json": f"{turn_dir_rel}/meta.json",
        },
    }



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
    write_text_atomic(script_file, script_source)

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
