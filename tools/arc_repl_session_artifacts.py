from __future__ import annotations

import json
from pathlib import Path
import re

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
    # Keep artifact location stable for the agent: always under the game workspace.
    game_dir = session.play_lib_file.parent
    level_number = (
        int(levels_before_action) + 1
        if isinstance(levels_before_action, int)
        else int(session.frame.levels_completed) + 1
    )
    level_dir = game_dir / f"level_{level_number}"
    turn_dir = level_dir / f"turn_{int(session.turn):04d}"
    turn_dir.mkdir(parents=True, exist_ok=True)

    before_grid = np.array(pre_pixels if pre_pixels is not None else final_pixels, copy=True)
    after_grid = np.array(final_pixels, copy=True)
    _write_hex_grid(turn_dir / "before_state.hex", before_grid)
    _write_hex_grid(turn_dir / "after_state.hex", after_grid)

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
        "game_dir": str(game_dir),
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
    game_index = game_dir / "turn_index.jsonl"
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
