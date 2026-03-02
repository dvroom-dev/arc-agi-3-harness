from __future__ import annotations

from pathlib import Path

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
    return session.deps._write_turn_trace(
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
