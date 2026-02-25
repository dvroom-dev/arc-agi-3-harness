#!/usr/bin/env python3
"""ARC action execution tool for super custom tool-calling."""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

import arc_agi
from arcengine import GameAction

# Ensure imports from run workspace root resolve when executed as tools/arc_action.py
RUN_ROOT = Path(__file__).resolve().parent.parent
if str(RUN_ROOT) not in sys.path:
    sys.path.insert(0, str(RUN_ROOT))

try:
    from arc_action_diffs import (
        _change_bbox,
        _changes_sample,
        _iter_cell_changes,
        _step_crosses_level,
        build_aggregate_diff_record,
        build_step_diff_records,
        format_change_records,
        format_diff_minimal,
        frame_action_metadata,
        write_game_state,
        write_machine_state,
    )
    from arc_action_env import (
        _action_from_event_name,
        _call_quiet,
        _get_pixels,
        _make_env,
        _make_id_candidates,
        _replay_history,
        _resolve_environments_dir,
        _resolve_operation_mode,
    )
    from arc_action_exec import _execute_script as _execute_script_impl
    from arc_action_exec import _script_worker_main
    from arc_action_exec import _write_turn_trace
    from arc_action_state import (
        _play_lib_path,
        _append_level_completion,
        _arc_dir,
        _completion_action_windows_by_level,
        _default_game_id,
        _emit_json,
        _ensure_play_lib_file,
        _ensure_level_completions_file,
        _error_payload,
        _history_path,
        _level_completions_path,
        _read_args,
        _read_max_recorded_completion_level,
        _save_history,
    )
    from arc_action_state import _load_history as _load_history_impl
except Exception:
    from tools.arc_action_diffs import (
        _change_bbox,
        _changes_sample,
        _iter_cell_changes,
        _step_crosses_level,
        build_aggregate_diff_record,
        build_step_diff_records,
        format_change_records,
        format_diff_minimal,
        frame_action_metadata,
        write_game_state,
        write_machine_state,
    )
    from tools.arc_action_env import (
        _action_from_event_name,
        _call_quiet,
        _get_pixels,
        _make_env,
        _make_id_candidates,
        _replay_history,
        _resolve_environments_dir,
        _resolve_operation_mode,
    )
    from tools.arc_action_exec import _execute_script as _execute_script_impl
    from tools.arc_action_exec import _script_worker_main
    from tools.arc_action_exec import _write_turn_trace
    from tools.arc_action_state import (
        _play_lib_path,
        _append_level_completion,
        _arc_dir,
        _completion_action_windows_by_level,
        _default_game_id,
        _emit_json,
        _ensure_play_lib_file,
        _ensure_level_completions_file,
        _error_payload,
        _history_path,
        _level_completions_path,
        _read_args,
        _read_max_recorded_completion_level,
        _save_history,
    )
    from tools.arc_action_state import _load_history as _load_history_impl


ARC_COLORS_RGB = {
    0: "#FFFFFF",
    1: "#CCCCCC",
    2: "#999999",
    3: "#666666",
    4: "#333333",
    5: "#000000",
    6: "#E53AA3",
    7: "#FF7BCC",
    8: "#F93C31",
    9: "#1E93FF",
    10: "#88D8F1",
    11: "#FFDC00",
    12: "#FF851B",
    13: "#921231",
    14: "#4FCC30",
    15: "#A356D6",
}


def _load_history(cwd: Path, game_id: str) -> dict:
    return _load_history_impl(cwd, game_id, _make_id_candidates)


def _execute_script(
    script_source: str,
    env,
    *,
    script_label: str,
    initial_frame,
    play_lib_source: str = "",
):
    return _execute_script_impl(
        script_source,
        env,
        script_label=script_label,
        initial_frame=initial_frame,
        play_lib_source=play_lib_source,
        get_pixels=_get_pixels,
    )


def main() -> int:
    cwd = Path.cwd().resolve()
    args = _read_args()
    action = str(args.get("action", "")).strip() if isinstance(args, dict) else ""
    requested_game_id = str(args.get("game_id", "")).strip() if isinstance(args, dict) else ""

    if "_error" in args:
        _emit_json(
            _error_payload(
                action=action or "status",
                requested_game_id=requested_game_id,
                message=str(args["_error"]),
                error_type="invalid_args",
            )
        )
        return 1
    if not action:
        _emit_json(
            _error_payload(
                action="",
                requested_game_id=requested_game_id,
                message="missing required `action` (expected: status|run_script|reset_level)",
                error_type="missing_action",
            )
        )
        return 1

    try:
        game_id = requested_game_id or _default_game_id(cwd)
        if not game_id:
            _emit_json(
                _error_payload(
                    action=action,
                    requested_game_id=requested_game_id,
                    message="game_id is required (or initialize state first with action=status and game_id)",
                    error_type="missing_game_id",
                )
            )
            return 1

        play_lib_file = _ensure_play_lib_file(cwd)
        history = _load_history(cwd, game_id)
        events = list(history.get("events", []))
        turn = int(history.get("turn", 0))
        arc_dir = _arc_dir(cwd)

        env = _call_quiet(_make_env, game_id)
        frame = _call_quiet(_replay_history, env, events)
        pre_pixels = _get_pixels(env, frame)
        state_before_action = str(frame.state.value)
        levels_before_action = int(frame.levels_completed)

        transition_log: list[str] = []
        step_snapshots: list[tuple[str, object]] = []
        step_results: list[dict] = []
        script_output = ""
        error = ""
        action_label = action

        if action == "status":
            pass
        elif action == "reset_level":
            frame = _call_quiet(env.reset)
            if frame is None:
                raise RuntimeError("env.reset() returned None")
            events.append({"kind": "reset"})
            action_label = "reset_level"
        elif action == "run_script":
            script_path_arg = args.get("script_path")
            script_inline = args.get("script")
            levels_before_script = int(frame.levels_completed)
            script_label = "<inline_script>"
            script_path = str(script_path_arg).strip() if script_path_arg is not None else ""
            if script_path:
                _emit_json(
                    _error_payload(
                        action=action,
                        requested_game_id=requested_game_id,
                        message="script_path is not supported; provide inline `script` for action=run_script",
                        error_type="invalid_run_script_args",
                    )
                )
                return 1
            if script_inline is None or not str(script_inline).strip():
                _emit_json(
                    _error_payload(
                        action=action,
                        requested_game_id=requested_game_id,
                        message="run_script requires non-empty inline `script`",
                        error_type="invalid_run_script_args",
                    )
                )
                return 1
            script_source = str(script_inline)

            play_lib_source = play_lib_file.read_text()
            (
                last_frame,
                script_output,
                error,
                transition_log,
                step_snapshots,
                executed_events,
                step_results,
            ) = _execute_script(
                script_source,
                env,
                script_label=script_label,
                initial_frame=frame,
                play_lib_source=play_lib_source,
            )
            if last_frame is not None:
                frame = last_frame
            action_label = f"run_script({script_label})"

            scripts_dir = arc_dir / "script-history"
            scripts_dir.mkdir(parents=True, exist_ok=True)
            turn_hint = turn + 1
            winning_script_file = scripts_dir / f"turn_{turn_hint:03d}_script.py"
            winning_script_file.write_text(script_source)

            completions_path = _ensure_level_completions_file(cwd)
            max_recorded = _read_max_recorded_completion_level(completions_path)
            completion_windows = _completion_action_windows_by_level(events + executed_events)
            levels_after_script = int(frame.levels_completed)
            for completed_level in range(levels_before_script + 1, levels_after_script + 1):
                if completed_level <= max_recorded:
                    continue
                actions = completion_windows.get(completed_level, [])
                try:
                    winning_script_rel = str(winning_script_file.relative_to(cwd))
                except ValueError:
                    winning_script_rel = str(winning_script_file)
                _append_level_completion(
                    path=completions_path,
                    completed_level=completed_level,
                    actions=actions,
                    tool_turn=turn_hint,
                    winning_script_relpath=winning_script_rel,
                )
                max_recorded = completed_level
            events.extend(executed_events)
        else:
            _emit_json(
                _error_payload(
                    action=action,
                    requested_game_id=requested_game_id,
                    message="unknown action. expected: status|run_script|reset_level",
                    error_type="unknown_action",
                )
            )
            return 1

        final_pixels = _get_pixels(env, frame)
        resolved_game_id = str(getattr(frame, "game_id", "")).strip() or game_id
        turn += 1
        history["game_id"] = resolved_game_id
        history["events"] = events
        history["turn"] = turn
        _save_history(cwd, history)

        write_game_state(
            arc_dir / "game-state.md",
            frame,
            final_pixels,
            game_id=resolved_game_id,
            last_action=action_label,
            script_output=script_output,
            error=error,
            step_snapshots=step_snapshots,
            pre_turn_pixels=pre_pixels if action == "run_script" else None,
            step_results=step_results if action == "run_script" else [],
        )
        write_machine_state(
            arc_dir,
            frame,
            final_pixels,
            game_id=resolved_game_id,
            last_action=action_label,
            step_snapshots=step_snapshots,
        )
        trace_path = _write_turn_trace(
            arc_dir=arc_dir,
            turn=turn,
            action_name=action_label,
            pre_pixels=pre_pixels if action == "run_script" else None,
            step_snapshots=step_snapshots,
            step_results=step_results if action == "run_script" else [],
            final_pixels=final_pixels,
            script_output=script_output,
            error=error,
        )

        step_diff_records = build_step_diff_records(
            pre_pixels if action == "run_script" else None,
            step_snapshots,
            step_results=step_results if action == "run_script" else [],
        )
        aggregate_diff = build_aggregate_diff_record(
            pre_pixels if action == "run_script" else None,
            final_pixels,
            step_snapshots=step_snapshots if action == "run_script" else [],
            step_results=step_results if action == "run_script" else [],
        )
        action_meta = frame_action_metadata(frame)
        try:
            trace_file_rel = str(trace_path.relative_to(cwd))
        except ValueError:
            trace_file_rel = str(trace_path)

        result = {
            "schema_version": "arc_action.v2",
            "ok": not bool(error),
            "action": action,
            "requested_game_id": requested_game_id,
            "game_id": resolved_game_id,
            "guid": getattr(frame, "guid", None),
            "state": frame.state.value,
            "state_before_action": state_before_action,
            "state_changed_in_call": state_before_action != str(frame.state.value),
            "current_level": frame.levels_completed + 1,
            "levels_completed": frame.levels_completed,
            "levels_before_action": levels_before_action,
            "win_levels": frame.win_levels,
            "levels_gained_in_call": int(frame.levels_completed) - levels_before_action,
            "full_reset": bool(getattr(frame, "full_reset", False)),
            "available_actions": [int(a) for a in frame.available_actions],
            **action_meta,
            "steps_executed": len(step_snapshots),
            "step_results": step_results,
            "step_diffs": step_diff_records,
            "aggregate_diff": aggregate_diff,
            "trace_file": trace_file_rel,
            "state_file": str((arc_dir / "state.json")),
            "transitions": transition_log,
            "script_stdout": script_output,
            "script_stdout_lines": script_output.splitlines(),
            "script_error": error or None,
        }
        _emit_json(result)
        return 0 if result["ok"] else 1
    except Exception as exc:
        _emit_json(
            _error_payload(
                action=action,
                requested_game_id=requested_game_id,
                message=str(exc),
                error_type="internal_exception",
                details=traceback.format_exc(),
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
