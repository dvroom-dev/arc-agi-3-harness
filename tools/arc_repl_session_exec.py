from __future__ import annotations

import io
import traceback
from contextlib import redirect_stderr, redirect_stdout

import numpy as np


class _StopScript(Exception):
    pass


def execute_exec_turn(session, requested_game_id: str, script: str, *, session_created: bool) -> dict:
    if requested_game_id and not session._same_game_lineage(requested_game_id):
        raise RuntimeError(
            f"active REPL game_id={session.game_id!r} does not match requested_game_id={requested_game_id!r}"
        )
    if not str(script or "").strip():
        raise RuntimeError("exec requires non-empty inline script")

    session._refresh_play_lib()

    session.script_counter += 1
    script_label = f"<arc_repl_exec_{session.script_counter:04d}>"
    pre_pixels = np.array(session.pixels, copy=True)
    state_before = str(session.frame.state.value)
    levels_before = int(session.frame.levels_completed)

    transition_log: list[str] = []
    step_snapshots: list[tuple[str, np.ndarray]] = []
    step_results: list[dict] = []
    executed_events: list[dict] = []
    terminal_halt = False

    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()
    error = ""

    original_step = session.env.step

    def logging_step(action, data=None, reasoning=None):
        nonlocal terminal_halt
        if terminal_halt:
            raise _StopScript()
        action_enum, action_name = session._normalize_action(action)
        prev_state = str(session.frame.state.value)
        prev_levels = int(session.frame.levels_completed)
        frame = original_step(action_enum, data=data, reasoning=reasoning)
        if frame is None:
            raise RuntimeError("env.step() returned None")
        session.frame = frame
        current_pixels = session.deps._get_pixels(session.env, frame)
        changes = session.deps._iter_cell_changes(session.pixels, current_pixels)
        levels_gained = int(frame.levels_completed) - prev_levels
        step_index = len(step_results) + 1
        if levels_gained > 0:
            step_changed_pixels = 0
            step_changes: list[dict] = []
            step_bbox = None
        else:
            step_changed_pixels = len(changes)
            step_changes = [
                {
                    "row": int(r),
                    "col": int(c),
                    "before": f"{int(b):X}",
                    "after": f"{int(a):X}",
                }
                for (r, c, b, a) in changes
            ]
            step_bbox = session.deps._change_bbox(changes)
        step_record = {
            "step": step_index,
            "action": action_name,
            "changed_pixels": step_changed_pixels,
            "change_bbox": step_bbox,
            "changes": step_changes,
            "state": str(frame.state.value),
            "state_before_step": prev_state,
            "state_changed_in_step": prev_state != str(frame.state.value),
            "levels_completed": int(frame.levels_completed),
            "levels_before_step": prev_levels,
            "levels_gained_in_step": levels_gained,
            "is_terminal": str(frame.state.value) in {"WIN", "GAME_OVER"},
        }
        if levels_gained > 0:
            step_record["suppressed_cross_level_diff"] = True
        step_results.append(step_record)
        session.pixels = current_pixels
        executed_events.append(
            {
                "kind": "step",
                "action": action_name,
                "data": data,
                "levels_completed": int(frame.levels_completed),
            }
        )
        desc = (
            f"{action_name}{' data=' + str(data) if data else ''} -> "
            f"state={frame.state.value} levels={frame.levels_completed}/{frame.win_levels}"
        )
        transition_log.append(desc)
        step_snapshots.append((desc, current_pixels))
        if frame.state.value in {"WIN", "GAME_OVER"}:
            terminal_halt = True
            raise _StopScript()
        return frame

    session.env.step = logging_step
    session.globals["env"] = session.env
    session.globals["current"] = session.env

    try:
        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
            exec(compile(script, script_label, "exec"), session.globals)
    except _StopScript:
        pass
    except BaseException:
        error = traceback.format_exc()
    finally:
        session.env.step = original_step

    worker_stderr = stderr_capture.getvalue().strip()
    script_output = stdout_capture.getvalue()
    if worker_stderr:
        script_output = (
            script_output
            + ("\n" if script_output and not script_output.endswith("\n") else "")
            + worker_stderr
            + "\n"
        )

    session.events.extend(executed_events)
    session.turn += 1
    session._sync_history_file()
    session._save_level_completion_records(
        levels_before_exec=levels_before,
        script_source=script,
    )

    trace_path = session._write_state_artifacts(
        action_label=f"exec({script_label})",
        script_output=script_output,
        error=error,
        pre_pixels=pre_pixels,
        step_snapshots=step_snapshots,
        step_results=step_results,
    )

    return session._finalize_result(
        action="exec",
        requested_game_id=requested_game_id,
        state_before_action=state_before,
        levels_before_action=levels_before,
        pre_pixels=pre_pixels,
        step_snapshots=step_snapshots,
        step_results=step_results,
        script_output=script_output,
        script_error=error,
        transitions=transition_log,
        trace_path=trace_path,
        session_created=session_created,
    )
