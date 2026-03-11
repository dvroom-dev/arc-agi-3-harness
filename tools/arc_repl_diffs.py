from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
from arcengine.enums import FrameDataRaw


def _iter_cell_changes(before: np.ndarray, after: np.ndarray) -> list[tuple[int, int, int, int]]:
    changed = np.argwhere(before != after)
    return [(int(r), int(c), int(before[r, c]), int(after[r, c])) for r, c in changed]


def _change_bbox(changes: list[tuple[int, int, int, int]]) -> dict | None:
    if not changes:
        return None
    rows = [r for r, _, _, _ in changes]
    cols = [c for _, c, _, _ in changes]
    return {
        "min_row": min(rows),
        "max_row": max(rows),
        "min_col": min(cols),
        "max_col": max(cols),
    }


def _changes_sample(changes: list[tuple[int, int, int, int]], limit: int = 24) -> list[dict]:
    out: list[dict] = []
    for row, col, before, after in changes[:limit]:
        out.append(
            {"row": row, "col": col, "before": f"{before:X}", "after": f"{after:X}"}
        )
    return out


def format_diff_minimal(before: np.ndarray, after: np.ndarray) -> str:
    changes = _iter_cell_changes(before, after)
    if not changes:
        return "(no changes)"
    lines = [
        f"changed_pixels={len(changes)}",
        "format: (row,col): before->after",
    ]
    for row, col, prev, nxt in changes:
        lines.append(f"({row},{col}): {prev:X}->{nxt:X}")
    return "\n".join(lines)


def format_change_records(changes: list[dict]) -> str:
    if not changes:
        return "(no changes)"
    lines = [
        f"changed_pixels={len(changes)}",
        "format: (row,col): before->after",
    ]
    for change in changes:
        try:
            row = int(change.get("row"))
            col = int(change.get("col"))
            before = str(change.get("before", "?"))
            after = str(change.get("after", "?"))
        except Exception:
            continue
        lines.append(f"({row},{col}): {before}->{after}")
    return "\n".join(lines) if len(lines) > 2 else "(no changes)"


def _step_crosses_level(step_results: list[dict] | None, step_index: int) -> bool:
    if not isinstance(step_results, list):
        return False
    if step_index < 0 or step_index >= len(step_results):
        return False
    meta = step_results[step_index]
    if not isinstance(meta, dict):
        return False
    try:
        return int(meta.get("levels_gained_in_step", 0) or 0) > 0
    except Exception:
        return False


def build_step_diff_records(
    pre_turn_pixels: np.ndarray | None,
    step_snapshots: list[tuple[str, np.ndarray]],
    *,
    step_results: list[dict] | None = None,
) -> list[dict]:
    if pre_turn_pixels is None or not step_snapshots:
        return []
    records: list[dict] = []
    for idx, (desc, snap) in enumerate(step_snapshots):
        if _step_crosses_level(step_results, idx):
            records.append(
                {
                    "step": idx + 1,
                    "description": desc,
                    "changed_pixels": 0,
                    "changes": [],
                    "suppressed_cross_level_diff": True,
                    "suppressed_reason": "level_transition",
                }
            )
            continue
        prev = pre_turn_pixels if idx == 0 else step_snapshots[idx - 1][1]
        changes = _iter_cell_changes(prev, snap)
        records.append(
            {
                "step": idx + 1,
                "description": desc,
                "changed_pixels": len(changes),
                "changes": [
                    {"row": row, "col": col, "before": f"{before:X}", "after": f"{after:X}"}
                    for row, col, before, after in changes
                ],
            }
        )
    return records


def build_aggregate_diff_record(
    pre_turn_pixels: np.ndarray | None,
    final_pixels: np.ndarray,
    *,
    step_snapshots: list[tuple[str, np.ndarray]] | None = None,
    step_results: list[dict] | None = None,
) -> dict:
    if pre_turn_pixels is None:
        return {"changed_pixels": 0, "changes": []}
    baseline = pre_turn_pixels
    baseline_note: dict[str, object] = {}
    if isinstance(step_snapshots, list) and isinstance(step_results, list):
        transition_steps = [
            idx
            for idx in range(min(len(step_snapshots), len(step_results)))
            if _step_crosses_level(step_results, idx)
        ]
        if transition_steps:
            last_idx = transition_steps[-1]
            baseline = step_snapshots[last_idx][1]
            baseline_note = {
                "suppressed_cross_level_diff": True,
                "aggregate_baseline": "post_last_level_transition",
                "aggregate_baseline_step": last_idx + 1,
            }
    changes = _iter_cell_changes(baseline, final_pixels)
    return {
        "changed_pixels": len(changes),
        "changes": [
            {"row": row, "col": col, "before": f"{before:X}", "after": f"{after:X}"}
            for row, col, before, after in changes
        ],
        **baseline_note,
    }


def frame_action_metadata(frame: FrameDataRaw) -> dict:
    action_input = getattr(frame, "action_input", None)
    action_id_obj = getattr(action_input, "id", None)
    action_name = getattr(action_id_obj, "name", str(action_id_obj)) if action_id_obj is not None else ""
    action_id = getattr(action_id_obj, "value", None)
    if not isinstance(action_id, int):
        try:
            action_id = int(action_id) if action_id is not None else None
        except Exception:
            action_id = None
    data = getattr(action_input, "data", {}) if action_input is not None else {}
    reasoning = getattr(action_input, "reasoning", None) if action_input is not None else None
    return {
        "action_input_id": action_id,
        "action_input_name": action_name,
        "action_input_data": data,
        "action_input_reasoning": reasoning,
    }


def write_machine_state(
    directory: Path,
    frame: FrameDataRaw,
    pixels: np.ndarray,
    *,
    game_id: str,
    last_action: str,
    step_snapshots: list[tuple[str, np.ndarray]],
    history_events: list[dict] | None = None,
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    scorecard_id = str(os.getenv("ARC_SCORECARD_ID", "") or "").strip() or None
    np.save(directory / "current_grid.npy", pixels.astype(np.int8))
    if step_snapshots:
        grids = np.stack([g for _, g in step_snapshots], axis=0).astype(np.int8)
    else:
        grids = np.empty((0, 64, 64), dtype=np.int8)
    np.save(directory / "all_grids.npy", grids)
    if isinstance(history_events, list):
        total_run_steps = sum(
            1 for event in history_events if str(event.get("kind", "")).strip() == "step"
        )
        total_run_resets = sum(
            1 for event in history_events if str(event.get("kind", "")).strip() == "reset"
        )
    else:
        total_run_steps = len(step_snapshots)
        total_run_resets = 0
    state = {
        "game_id": game_id,
        "scorecard_id": scorecard_id,
        "current_level": frame.levels_completed + 1,
        "state": frame.state.value,
        "levels_completed": frame.levels_completed,
        "win_levels": frame.win_levels,
        "guid": getattr(frame, "guid", None),
        "available_actions": [int(a) for a in frame.available_actions],
        "last_action": last_action,
        "full_reset": bool(getattr(frame, "full_reset", False)),
        **frame_action_metadata(frame),
        "total_steps": total_run_steps,
        "current_attempt_steps": len(step_snapshots),
        "total_resets": total_run_resets,
        "steps": [desc for desc, _ in step_snapshots],
    }
    (directory / "state.json").write_text(json.dumps(state, indent=2))


def write_game_state(
    path: Path,
    frame: FrameDataRaw,
    pixels: np.ndarray,
    *,
    game_id: str,
    last_action: str,
    script_output: str,
    error: str,
    step_snapshots: list[tuple[str, np.ndarray]],
    pre_turn_pixels: np.ndarray | None,
    step_results: list[dict] | None = None,
) -> None:
    lines = [
        "# Game State",
        "",
        f"- game_id: {game_id}",
        f"- guid: {getattr(frame, 'guid', None)}",
        f"- state: {frame.state.value}",
        f"- levels_completed: {frame.levels_completed}",
        f"- win_levels: {frame.win_levels}",
        f"- last_action: {last_action}",
        f"- full_reset: {bool(getattr(frame, 'full_reset', False))}",
    ]
    action_meta = frame_action_metadata(frame)
    lines.extend(
        [
            f"- action_input_id: {action_meta['action_input_id']}",
            f"- action_input_name: {action_meta['action_input_name']}",
            f"- action_input_data: {json.dumps(action_meta['action_input_data'])}",
            f"- action_input_reasoning: {json.dumps(action_meta['action_input_reasoning'])}",
        ]
    )
    if error:
        lines.extend(["", "## Error", "```", error, "```"])
    if script_output:
        lines.extend(["", "## Script Output", "```", script_output, "```"])
    if pre_turn_pixels is not None:
        lines.extend(["", "## Initial Grid", "```"])
        for row in pre_turn_pixels:
            lines.append("".join(f"{int(v):X}" for v in row))
        lines.append("```")
    if pre_turn_pixels is not None and step_snapshots:
        step_diff_records = build_step_diff_records(
            pre_turn_pixels,
            step_snapshots,
            step_results=step_results,
        )
        aggregate_diff = build_aggregate_diff_record(
            pre_turn_pixels,
            pixels,
            step_snapshots=step_snapshots,
            step_results=step_results,
        )
        lines.extend(["", "## Step Diffs"])
        for record in step_diff_records:
            step_num = int(record.get("step", 0))
            desc = str(record.get("description", ""))
            lines.extend(["", f"### Step {step_num}: {desc}", "```"])
            if bool(record.get("suppressed_cross_level_diff", False)):
                lines.append("(suppressed: level transition occurred in this step)")
            else:
                changes = record.get("changes")
                if isinstance(changes, list):
                    lines.append(format_change_records(changes))
                else:
                    lines.append("(no changes)")
            lines.append("```")
        lines.extend(["", "## Aggregate Diff (Initial -> Final)", "```"])
        agg_changes = aggregate_diff.get("changes")
        if isinstance(agg_changes, list):
            lines.append(format_change_records(agg_changes))
        else:
            lines.append("(no changes)")
        if bool(aggregate_diff.get("suppressed_cross_level_diff", False)):
            baseline_step = aggregate_diff.get("aggregate_baseline_step")
            lines.append(
                f"note: cross-level changes suppressed; baseline reset after step {baseline_step}"
            )
        lines.append("```")
    lines.extend(["", "## Grid", "```"])
    for row in pixels:
        lines.append("".join(f"{int(v):X}" for v in row))
    lines.append("```")
    path.write_text("\n".join(lines) + "\n")
