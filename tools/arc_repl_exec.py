from __future__ import annotations

import io
import json
import multiprocessing
import re
import traceback
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
from arcengine import GameAction
from arcengine.enums import FrameDataRaw

try:
    from arc_repl_diffs import (
        _change_bbox,
        _changes_sample,
        _iter_cell_changes,
        build_aggregate_diff_record,
        build_step_diff_records,
        format_change_records,
    )
except Exception:
    from tools.arc_repl_diffs import (
        _change_bbox,
        _changes_sample,
        _iter_cell_changes,
        build_aggregate_diff_record,
        build_step_diff_records,
        format_change_records,
    )


SAFE_BUILTINS = {
    "abs": abs,
    "all": all,
    "any": any,
    "bool": bool,
    "dict": dict,
    "dir": dir,
    "enumerate": enumerate,
    "Exception": Exception,
    "filter": filter,
    "float": float,
    "getattr": getattr,
    "hasattr": hasattr,
    "int": int,
    "isinstance": isinstance,
    "issubclass": issubclass,
    "len": len,
    "list": list,
    "map": map,
    "max": max,
    "min": min,
    "print": print,
    "range": range,
    "reversed": reversed,
    "round": round,
    "set": set,
    "sorted": sorted,
    "str": str,
    "sum": sum,
    "tuple": tuple,
    "vars": vars,
    "zip": zip,
}


def _script_worker_main(conn, script_source: str, play_lib_source: str, script_label: str) -> None:
    class _StopScript(Exception):
        pass

    class _FrameView:
        def __init__(self, payload: dict):
            self.state = SimpleNamespace(value=str(payload.get("state", "")))
            self.levels_completed = int(payload.get("levels_completed", 0))
            self.win_levels = int(payload.get("win_levels", 0))
            self.current_level = int(payload.get("current_level", self.levels_completed + 1))
            self.full_reset = bool(payload.get("full_reset", False))
            self.available_actions = list(payload.get("available_actions", []))
            self.action_input_id = payload.get("action_input_id", 0)
            self.action_input_name = payload.get("action_input_name", "")
            for key, value in payload.items():
                if not hasattr(self, key):
                    setattr(self, key, value)

        def get(self, key, default=None):
            return getattr(self, key, default)

    class _ScriptEnv:
        __slots__ = ()

        def step(self, action, data=None, reasoning=None):
            conn.send({"op": "step", "action": action, "data": data, "reasoning": reasoning})
            resp = conn.recv()
            if not isinstance(resp, dict):
                raise RuntimeError("invalid step response")
            if resp.get("terminal"):
                raise _StopScript()
            if not resp.get("ok", False):
                raise RuntimeError(str(resp.get("error", "step failed")))
            return _FrameView(resp.get("frame", {}))

        def reset(self):
            raise RuntimeError("env.reset() cannot be called inside run_script; use action=reset_level")

        def state(self):
            conn.send({"op": "get_state"})
            resp = conn.recv()
            if not isinstance(resp, dict) or not resp.get("ok", False):
                raise RuntimeError(str(resp.get("error", "state unavailable")))
            return dict(resp.get("state", {}))

    game_action = SimpleNamespace(**{member.name: int(member.value) for member in GameAction})
    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()
    worker_error = ""
    script_globals = {
        "__builtins__": SAFE_BUILTINS,
        "env": _ScriptEnv(),
        "GameAction": game_action,
    }

    try:
        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
            if play_lib_source.strip():
                exec(compile(play_lib_source, "play_lib.py", "exec"), script_globals)
            exec(compile(script_source, script_label, "exec"), script_globals)
    except _StopScript:
        pass
    except BaseException:
        worker_error = traceback.format_exc()
    finally:
        conn.send(
            {
                "op": "done",
                "stdout": stdout_capture.getvalue(),
                "stderr": stderr_capture.getvalue(),
                "error": worker_error,
            }
        )
        conn.close()


def _normalize_action(action: Any) -> tuple[GameAction, str]:
    if isinstance(action, GameAction):
        return action, action.name
    candidate = action
    if hasattr(candidate, "value"):
        try:
            candidate = int(getattr(candidate, "value"))
        except Exception:
            candidate = getattr(candidate, "value")
    if isinstance(candidate, int):
        for member in GameAction:
            try:
                if int(member.value) == int(candidate):
                    return member, member.name
            except Exception:
                continue
        raise ValueError(f"unknown action id: {candidate}")
    name = str(candidate).strip()
    if re.fullmatch(r"-?\d+", name):
        return _normalize_action(int(name))
    if hasattr(GameAction, name):
        member = getattr(GameAction, name)
        return member, member.name
    upper = name.upper()
    if hasattr(GameAction, upper):
        member = getattr(GameAction, upper)
        return member, member.name
    raise ValueError(f"unknown action: {candidate}")


def _frame_view_dict(frame: FrameDataRaw, step_info: dict | None = None) -> dict:
    action_input = getattr(frame, "action_input", None)
    action_id_obj = getattr(action_input, "id", None) if action_input is not None else None
    action_id = getattr(action_id_obj, "value", action_id_obj)
    action_name = getattr(action_id_obj, "name", "")
    try:
        action_id = int(action_id) if action_id is not None else 0
    except Exception:
        action_id = 0
    payload = {
        "state": str(frame.state.value),
        "levels_completed": int(frame.levels_completed),
        "win_levels": int(frame.win_levels),
        "current_level": int(frame.levels_completed) + 1,
        "full_reset": bool(getattr(frame, "full_reset", False)),
        "available_actions": [int(a) for a in getattr(frame, "available_actions", [])],
        "action_input_id": action_id,
        "action_input_name": str(action_name),
    }
    if step_info is not None:
        payload.update(
            {
                "step_index": int(step_info.get("step", 0)),
                "changed_pixels": int(step_info.get("changed_pixels", 0)),
                "change_bbox": step_info.get("change_bbox"),
                "changes_sample": step_info.get("changes_sample", []),
                "levels_gained_in_step": int(step_info.get("levels_gained_in_step", 0)),
                "state_changed_in_step": bool(step_info.get("state_changed_in_step", False)),
                "step_diffs": [
                    {
                        "changed_pixels": int(step_info.get("changed_pixels", 0)),
                        "changes_sample": step_info.get("changes_sample", []),
                    }
                ],
            }
        )
    return payload


def _frame_sequence_hex_rows(frame: FrameDataRaw) -> list[list[str]]:
    data = getattr(frame, "frame", None)
    if not isinstance(data, (list, tuple)) or not data:
        return []
    out: list[list[str]] = []
    for pixels in data:
        grid = np.array(pixels, copy=True)
        out.append(["".join(f"{int(v):X}" for v in row) for row in grid])
    return out


def _execute_script(
    script_source: str,
    env,
    *,
    script_label: str,
    initial_frame: FrameDataRaw,
    play_lib_source: str = "",
    get_pixels,
) -> tuple[
    FrameDataRaw | None,
    str,
    str,
    list[str],
    list[tuple[str, np.ndarray]],
    list[dict],
    list[dict],
]:
    transition_log: list[str] = []
    step_snapshots: list[tuple[str, np.ndarray]] = []
    executed_events: list[dict] = []
    step_results: list[dict] = []
    last_frame: FrameDataRaw | None = None
    terminal_halt = False

    class _TerminalStateReached(Exception):
        pass

    original_step = env.step
    last_pixels = get_pixels(env, initial_frame)

    def logging_step(action, data=None, reasoning=None):
        nonlocal last_frame, terminal_halt, last_pixels
        if terminal_halt:
            raise _TerminalStateReached()
        action_enum, action_name = _normalize_action(action)
        prev_state = str(last_frame.state.value if last_frame is not None else initial_frame.state.value)
        prev_levels = int(last_frame.levels_completed if last_frame is not None else initial_frame.levels_completed)
        prev_frame = last_frame if last_frame is not None else initial_frame
        guid_before = getattr(prev_frame, "guid", None)
        available_before = [int(a) for a in getattr(prev_frame, "available_actions", [])]
        frame = original_step(action_enum, data=data, reasoning=reasoning)
        if frame is not None:
            last_frame = frame
            frame_sequence_rows = _frame_sequence_hex_rows(frame)
            current_pixels = get_pixels(env, frame)
            changes = _iter_cell_changes(last_pixels, current_pixels)
            levels_gained = int(frame.levels_completed) - prev_levels
            step_index = len(step_results) + 1
            if levels_gained > 0:
                step_changed_pixels = 0
                step_changes_sample: list[dict] = []
            else:
                step_changed_pixels = len(changes)
                step_changes_sample = _changes_sample(changes)
            step_record = {
                "step": step_index,
                "action": action_name,
                "changed_pixels": step_changed_pixels,
                "change_bbox": _change_bbox(changes) if levels_gained <= 0 else None,
                "changes_sample": step_changes_sample,
                "state": str(frame.state.value),
                "state_before_step": prev_state,
                "state_changed_in_step": prev_state != str(frame.state.value),
                "levels_completed": int(frame.levels_completed),
                "levels_before_step": prev_levels,
                "levels_gained_in_step": levels_gained,
                "is_terminal": str(frame.state.value) in {"WIN", "GAME_OVER"},
                "guid": getattr(frame, "guid", None),
                "available_actions": [int(a) for a in getattr(frame, "available_actions", [])],
                "full_reset": bool(getattr(frame, "full_reset", False)),
                "frame_count": int(len(frame_sequence_rows) or 1),
            }
            if frame_sequence_rows:
                step_record["frame_sequence_rows"] = frame_sequence_rows
            if levels_gained > 0:
                step_record["suppressed_cross_level_diff"] = True
            step_results.append(step_record)
            last_pixels = current_pixels
            executed_events.append(
                {
                    "kind": "step",
                    "action": action_name,
                    "data": data,
                    "levels_completed": int(frame.levels_completed),
                }
            )
            desc = f"{action_name}{' data=' + str(data) if data else ''} -> state={frame.state.value} levels={frame.levels_completed}/{frame.win_levels}"
            transition_log.append(desc)
            step_snapshots.append((desc, current_pixels))
            if frame.state.value in {"WIN", "GAME_OVER"}:
                terminal_halt = True
                raise _TerminalStateReached()
        else:
            failure = getattr(env, "_arc_last_step_failure", None)
            step_record = {
                "step": len(step_results) + 1,
                "action": action_name,
                "state_before_step": prev_state,
                "levels_before_step": prev_levels,
                "guid_before_step": guid_before,
                "available_actions_before_step": available_before,
                "error": "env.step() returned None",
                "failure_details": failure if isinstance(failure, dict) else {},
            }
            step_results.append(step_record)
            detail_text = json.dumps(step_record.get("failure_details", {}), ensure_ascii=True)
            raise RuntimeError(f"env.step() returned None; diagnostics={detail_text}")
        return frame, (step_results[-1] if step_results else None)

    ctx = multiprocessing.get_context("spawn")
    parent_conn, child_conn = ctx.Pipe()
    proc = ctx.Process(target=_script_worker_main, args=(child_conn, script_source, play_lib_source, script_label))
    proc.start()
    child_conn.close()
    last_frame = initial_frame
    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()
    error = ""

    try:
        while True:
            msg = parent_conn.recv()
            if not isinstance(msg, dict):
                continue
            op = str(msg.get("op", "")).strip()
            if op == "step":
                try:
                    frame, step_info = logging_step(
                        msg.get("action"),
                        data=msg.get("data"),
                        reasoning=msg.get("reasoning"),
                    )
                    parent_conn.send({"ok": True, "frame": _frame_view_dict(frame, step_info)})
                except _TerminalStateReached:
                    parent_conn.send({"ok": True, "terminal": True})
                except BaseException as exc:
                    parent_conn.send({"ok": False, "error": str(exc)})
            elif op == "get_state":
                frame = last_frame or initial_frame
                parent_conn.send({"ok": True, "state": _frame_view_dict(frame)})
            elif op == "done":
                stdout_capture.write(str(msg.get("stdout", "")))
                stderr_capture.write(str(msg.get("stderr", "")))
                error = str(msg.get("error", ""))
                break
            else:
                parent_conn.send({"ok": False, "error": f"unsupported op: {op}"})
    except EOFError:
        if not error:
            error = "script worker terminated unexpectedly"
    finally:
        parent_conn.close()
        proc.join(timeout=2.0)
        if proc.is_alive():
            proc.terminate()
            proc.join(timeout=1.0)
        env.step = original_step

    output = stdout_capture.getvalue()
    worker_stderr = stderr_capture.getvalue().strip()
    if worker_stderr:
        output = (output + ("\n" if output and not output.endswith("\n") else "")) + worker_stderr + "\n"
    return (
        last_frame,
        output,
        error,
        transition_log,
        step_snapshots,
        executed_events,
        step_results,
    )


def _write_turn_trace(
    arc_dir: Path,
    turn: int,
    action_name: str,
    pre_pixels: np.ndarray | None,
    step_snapshots: list[tuple[str, np.ndarray]],
    step_results: list[dict] | None,
    final_pixels: np.ndarray,
    script_output: str = "",
    error: str = "",
) -> Path:
    trace_dir = arc_dir / "turn-traces"
    trace_dir.mkdir(parents=True, exist_ok=True)
    trace_path = trace_dir / f"turn_{turn:03d}_trace.md"
    parts = [
        f"# Turn {turn:03d} Trace",
        "",
        f"- action: `{action_name}`",
        f"- steps: {len(step_snapshots)}",
        f"- script_error: {bool(error)}",
    ]
    if script_output:
        parts.extend(["", "## Script Output", "```", script_output, "```"])
    if error:
        parts.extend(["", "## Script Error", "```", error, "```"])
    if step_results:
        parts.extend(["", "## Step Diagnostics", "```json"])
        for rec in step_results:
            compact = {
                "step": rec.get("step"),
                "action": rec.get("action"),
                "state": rec.get("state"),
                "state_before_step": rec.get("state_before_step"),
                "levels_before_step": rec.get("levels_before_step"),
                "levels_completed": rec.get("levels_completed"),
                "levels_gained_in_step": rec.get("levels_gained_in_step"),
                "changed_pixels": rec.get("changed_pixels"),
                "guid": rec.get("guid", rec.get("guid_before_step")),
                "available_actions": rec.get(
                    "available_actions",
                    rec.get("available_actions_before_step"),
                ),
                "full_reset": rec.get("full_reset"),
                "error": rec.get("error"),
                "failure_details": rec.get("failure_details"),
            }
            parts.append(json.dumps(compact, ensure_ascii=True))
        parts.append("```")
    if pre_pixels is not None:
        parts.extend(["", "## Initial Grid", "```"])
        for row in pre_pixels:
            parts.append("".join(f"{int(v):X}" for v in row))
        parts.append("```")
    if pre_pixels is not None and step_snapshots:
        step_diff_records = build_step_diff_records(
            pre_pixels,
            step_snapshots,
            step_results=step_results,
        )
        aggregate_diff = build_aggregate_diff_record(
            pre_pixels,
            final_pixels,
            step_snapshots=step_snapshots,
            step_results=step_results,
        )
        parts.append("")
        parts.append("## Per-Step Diffs")
        for record in step_diff_records:
            step_num = int(record.get("step", 0))
            desc = str(record.get("description", ""))
            parts.extend(["", f"### Step {step_num}: {desc}", "```"])
            if bool(record.get("suppressed_cross_level_diff", False)):
                parts.append("(suppressed: level transition occurred in this step)")
            else:
                changes = record.get("changes")
                if isinstance(changes, list):
                    parts.append(format_change_records(changes))
                else:
                    parts.append("(no changes)")
            parts.append("```")
        parts.extend(["", "## Aggregate Diff (Initial -> Final)", "```"])
        agg_changes = aggregate_diff.get("changes")
        if isinstance(agg_changes, list):
            parts.append(format_change_records(agg_changes))
        else:
            parts.append("(no changes)")
        if bool(aggregate_diff.get("suppressed_cross_level_diff", False)):
            baseline_step = aggregate_diff.get("aggregate_baseline_step")
            parts.append(
                f"note: cross-level changes suppressed; baseline reset after step {baseline_step}"
            )
        parts.append("```")
    parts.extend(["", "## Final Grid", "```"])
    for row in final_pixels:
        parts.append("".join(f"{int(v):X}" for v in row))
    parts.append("```")
    trace_path.write_text("\n".join(parts) + "\n")
    return trace_path
