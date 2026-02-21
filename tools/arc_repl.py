#!/usr/bin/env python3
"""Stateful ARC Python REPL tool for super shell usage.

JSON stdin contract:
- action=status
- action=exec (inline script only via `script`)
- action=reset_level
- action=shutdown (stop conversation REPL daemon)

The REPL is conversation-scoped (ARC_CONVERSATION_ID) and persists Python globals
across calls in a daemon process. New conversations start a fresh REPL namespace,
seeded with an `env` already positioned at the current game state via replay history.
"""

from __future__ import annotations

import argparse
import io
import json
import multiprocessing.connection
import os
import re
import subprocess
import sys
import time
import traceback
from contextlib import redirect_stderr, redirect_stdout
from hashlib import sha1
from pathlib import Path
from typing import Any

import numpy as np

from arcengine import GameAction
from arcengine.enums import FrameDataRaw

from arc_action import (
    _action_from_event_name,
    _arc_dir,
    _append_level_completion,
    _call_quiet,
    _change_bbox,
    _completion_action_windows_by_level,
    _default_game_id,
    _ensure_agent_lib_file,
    _ensure_level_completions_file,
    _error_payload,
    _get_pixels,
    _iter_cell_changes,
    _load_history,
    _make_env,
    _make_id_candidates,
    _read_max_recorded_completion_level,
    _replay_history,
    _save_history,
    _write_turn_trace,
    build_aggregate_diff_record,
    build_step_diff_records,
    format_diff_minimal,
    frame_action_metadata,
    write_game_state,
    write_machine_state,
)

SCHEMA_VERSION = "arc_repl.v1"
SOCKET_WAIT_TIMEOUT_S = 12.0


def _error(*, action: str, requested_game_id: str, message: str, error_type: str, details: str = "") -> dict:
    payload = _error_payload(
        action=action,
        requested_game_id=requested_game_id,
        message=message,
        error_type=error_type,
        details=details,
    )
    payload["schema_version"] = SCHEMA_VERSION
    return payload


def _read_args() -> dict:
    raw = sys.stdin.read().strip()
    if not raw:
        return {"_error": "expected JSON args on stdin"}
    try:
        parsed = json.loads(raw)
    except Exception as exc:
        return {"_error": f"invalid JSON args: {exc}"}
    if not isinstance(parsed, dict):
        return {"_error": "JSON args must be an object"}
    return parsed


def _emit_json(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, indent=2))
    if not sys.stdout.isatty():
        sys.stdout.write("\n")


def _conversation_id() -> str:
    raw = str(os.getenv("ARC_CONVERSATION_ID", "") or "").strip()
    if not raw:
        raw = "default"
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("._")
    return safe[:120] or "default"


def _session_dir(cwd: Path, conversation_id: str) -> Path:
    return _arc_dir(cwd) / "repl-sessions" / conversation_id


def _socket_path(cwd: Path, conversation_id: str) -> Path:
    key = f"{_arc_dir(cwd)}::{conversation_id}"
    digest = sha1(key.encode("utf-8")).hexdigest()[:20]
    return Path("/tmp") / f"arc-repl-{digest}.sock"


def _pid_path(cwd: Path, conversation_id: str) -> Path:
    return _session_dir(cwd, conversation_id) / "daemon.pid"


def _meta_path(cwd: Path, conversation_id: str) -> Path:
    return _session_dir(cwd, conversation_id) / "session.json"


def _daemon_log_path(cwd: Path, conversation_id: str) -> Path:
    return _session_dir(cwd, conversation_id) / "daemon.log"


def _same_game_lineage(existing_game_id: str, requested_game_id: str) -> bool:
    a = str(existing_game_id).strip()
    b = str(requested_game_id).strip()
    if not a or not b:
        return True
    if a == b:
        return True
    a_candidates = set(_make_id_candidates(a))
    b_candidates = set(_make_id_candidates(b))
    return bool(a_candidates.intersection(b_candidates))


def _grid_from_hex_rows(rows: list[str]) -> np.ndarray:
    parsed: list[list[int]] = []
    for row in rows:
        if not isinstance(row, str):
            raise RuntimeError("hex rows must contain strings")
        parsed.append([int(ch, 16) for ch in row.strip()])
    arr = np.array(parsed, dtype=np.int16)
    if arr.ndim != 2:
        raise RuntimeError("hex rows must form a 2D grid")
    return arr


def _chunk_for_bbox(grid: np.ndarray, bbox: dict | None, *, pad: int = 0) -> dict:
    if bbox is None:
        return {"bbox": None, "rows_hex": []}
    rows, cols = grid.shape
    r0 = max(0, int(bbox["min_row"]) - pad)
    r1 = min(rows - 1, int(bbox["max_row"]) + pad)
    c0 = max(0, int(bbox["min_col"]) - pad)
    c1 = min(cols - 1, int(bbox["max_col"]) + pad)
    view = grid[r0 : r1 + 1, c0 : c1 + 1]
    hex_rows = ["".join(f"{int(v):X}" for v in row) for row in view]
    return {
        "bbox": {
            "min_row": r0,
            "max_row": r1,
            "min_col": c0,
            "max_col": c1,
        },
        "rows_hex": hex_rows,
    }


def _coerce_grid(state_like: Any, current_grid: np.ndarray | None = None) -> np.ndarray:
    if state_like is None:
        if current_grid is None:
            raise RuntimeError("no state provided and no current grid available")
        return np.array(current_grid, copy=True)

    if isinstance(state_like, np.ndarray):
        return np.array(state_like, copy=True)

    if isinstance(state_like, FrameDataRaw):
        return _get_pixels(None, state_like)  # type: ignore[arg-type]

    if isinstance(state_like, list):
        if state_like and all(isinstance(x, str) for x in state_like):
            return _grid_from_hex_rows(state_like)
        return np.array(state_like)

    if isinstance(state_like, dict):
        if "grid_hex_rows" in state_like and isinstance(state_like["grid_hex_rows"], list):
            return _grid_from_hex_rows(state_like["grid_hex_rows"])
        if "frame" in state_like:
            frame = state_like["frame"]
            if isinstance(frame, list) and frame and isinstance(frame[0], list):
                return np.array(frame[0])

    if hasattr(state_like, "frame"):
        frame = getattr(state_like, "frame")
        if isinstance(frame, (list, tuple)) and frame and isinstance(frame[0], np.ndarray):
            return np.array(frame[0], copy=True)

    raise RuntimeError(f"unsupported state type for diff(): {type(state_like)!r}")


class _StopScript(Exception):
    pass


class ReplSession:
    def __init__(
        self,
        *,
        cwd: Path,
        conversation_id: str,
        requested_game_id: str,
    ) -> None:
        self.cwd = cwd
        self.conversation_id = conversation_id
        self.arc_dir = _arc_dir(cwd)
        self.session_dir = _session_dir(cwd, conversation_id)
        self.session_dir.mkdir(parents=True, exist_ok=True)

        game_id = str(requested_game_id or "").strip() or _default_game_id(cwd)
        if not game_id:
            raise RuntimeError(
                "game_id is required (or initialize state first with action=status and game_id)"
            )

        self.agent_lib_file = _ensure_agent_lib_file(cwd)
        self.completions_path = _ensure_level_completions_file(cwd)
        self.history = _load_history(cwd, game_id)
        self.turn = int(self.history.get("turn", 0))
        self.events: list[dict] = list(self.history.get("events", []))

        self.env = _call_quiet(_make_env, game_id)
        self.frame = _call_quiet(_replay_history, self.env, self.events)
        self.pixels = _get_pixels(self.env, self.frame)
        self.game_id = str(getattr(self.frame, "game_id", "")).strip() or game_id
        self.history["game_id"] = self.game_id

        self.script_counter = 0
        self.last_agent_lib_mtime_ns: int | None = None
        self.globals: dict[str, Any] = {
            "np": np,
            "json": json,
            "env": self.env,
            "current": self.env,
            "GameAction": GameAction,
            "GA": GameAction,
            "get_state": self._state_payload,
            "diff": self.diff,
        }
        self._refresh_agent_lib(force=True)

    def _refresh_agent_lib(self, *, force: bool = False) -> None:
        try:
            stat = self.agent_lib_file.stat()
            mtime_ns = int(stat.st_mtime_ns)
        except Exception:
            return
        if not force and self.last_agent_lib_mtime_ns == mtime_ns:
            return
        source = self.agent_lib_file.read_text()
        exec(compile(source, str(self.agent_lib_file), "exec"), self.globals)
        self.last_agent_lib_mtime_ns = mtime_ns

    def _state_payload(self) -> dict:
        frame = self.frame
        scorecard_id = str(os.getenv("ARC_SCORECARD_ID", "") or "").strip() or None
        return {
            "state": str(frame.state.value),
            "current_level": int(frame.levels_completed) + 1,
            "levels_completed": int(frame.levels_completed),
            "win_levels": int(frame.win_levels),
            "guid": getattr(frame, "guid", None),
            "scorecard_id": scorecard_id,
            "available_actions": [int(a) for a in getattr(frame, "available_actions", [])],
            "full_reset": bool(getattr(frame, "full_reset", False)),
            **frame_action_metadata(frame),
            "grid_hex_rows": [
                "".join(f"{int(v):X}" for v in row)
                for row in self.pixels
            ],
        }

    def _sync_history_file(self) -> None:
        self.history["game_id"] = self.game_id
        self.history["events"] = self.events
        self.history["turn"] = self.turn
        _save_history(self.cwd, self.history)

    def _write_state_artifacts(
        self,
        *,
        action_label: str,
        script_output: str,
        error: str,
        pre_pixels: np.ndarray | None,
        step_snapshots: list[tuple[str, np.ndarray]],
        step_results: list[dict] | None,
    ) -> Path:
        final_pixels = self.pixels
        write_game_state(
            self.arc_dir / "game-state.md",
            self.frame,
            final_pixels,
            game_id=self.game_id,
            last_action=action_label,
            script_output=script_output,
            error=error,
            step_snapshots=step_snapshots,
            pre_turn_pixels=pre_pixels,
            step_results=step_results,
        )
        write_machine_state(
            self.arc_dir,
            self.frame,
            final_pixels,
            game_id=self.game_id,
            last_action=action_label,
            step_snapshots=step_snapshots,
        )
        return _write_turn_trace(
            arc_dir=self.arc_dir,
            turn=self.turn,
            action_name=action_label,
            pre_pixels=pre_pixels,
            step_snapshots=step_snapshots,
            step_results=step_results,
            final_pixels=final_pixels,
            script_output=script_output,
            error=error,
        )

    def _save_level_completion_records(
        self,
        *,
        levels_before_exec: int,
        executed_events: list[dict],
        script_source: str,
    ) -> str | None:
        levels_after_exec = int(self.frame.levels_completed)
        if levels_after_exec <= levels_before_exec:
            return None

        scripts_dir = self.arc_dir / "script-history"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        script_file = scripts_dir / f"turn_{self.turn:03d}_script.py"
        script_file.write_text(script_source)

        max_recorded = _read_max_recorded_completion_level(self.completions_path)
        completion_windows = _completion_action_windows_by_level(self.events)

        try:
            script_rel = str(script_file.relative_to(self.cwd))
        except Exception:
            script_rel = str(script_file)

        for completed_level in range(levels_before_exec + 1, levels_after_exec + 1):
            if completed_level <= max_recorded:
                continue
            actions = completion_windows.get(completed_level, [])
            _append_level_completion(
                path=self.completions_path,
                completed_level=completed_level,
                actions=actions,
                tool_turn=self.turn,
                winning_script_relpath=script_rel,
            )
            max_recorded = completed_level
        return script_rel

    def _normalize_action(self, action: Any) -> tuple[GameAction, str]:
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
            raise RuntimeError(f"unknown action id: {candidate}")
        name = str(candidate).strip()
        if re.fullmatch(r"-?\d+", name):
            return self._normalize_action(int(name))
        if hasattr(GameAction, name):
            member = getattr(GameAction, name)
            return member, member.name
        upper = name.upper()
        if hasattr(GameAction, upper):
            member = getattr(GameAction, upper)
            return member, member.name
        # Allow action names from history payload style.
        member = _action_from_event_name(name)
        return member, member.name

    def diff(
        self,
        before_state: Any,
        after_state: Any,
        *,
        output: str = "json",
        pad: int = 0,
    ) -> dict | str:
        before = _coerce_grid(before_state, self.pixels)
        after = _coerce_grid(after_state, self.pixels)
        changes = _iter_cell_changes(before, after)
        bbox = _change_bbox(changes)
        if str(output).lower() == "text":
            return format_diff_minimal(before, after)
        return {
            "changed_pixels": len(changes),
            "bbox": bbox,
            "before": _chunk_for_bbox(before, bbox, pad=pad),
            "after": _chunk_for_bbox(after, bbox, pad=pad),
            "changes": [
                {
                    "row": int(r),
                    "col": int(c),
                    "before": f"{int(b):X}",
                    "after": f"{int(a):X}",
                }
                for (r, c, b, a) in changes
            ],
        }

    def _finalize_result(
        self,
        *,
        action: str,
        requested_game_id: str,
        state_before_action: str,
        levels_before_action: int,
        pre_pixels: np.ndarray | None,
        step_snapshots: list[tuple[str, np.ndarray]],
        step_results: list[dict],
        script_output: str,
        script_error: str,
        transitions: list[str],
        trace_path: Path,
        session_created: bool,
    ) -> dict:
        step_diffs = build_step_diff_records(
            pre_pixels,
            step_snapshots,
            step_results=step_results,
        )
        aggregate_diff = build_aggregate_diff_record(
            pre_pixels,
            self.pixels,
            step_snapshots=step_snapshots,
            step_results=step_results,
        )

        try:
            trace_rel = str(trace_path.relative_to(self.cwd))
        except Exception:
            trace_rel = str(trace_path)

        result = {
            "schema_version": SCHEMA_VERSION,
            "ok": not bool(script_error),
            "action": action,
            "requested_game_id": requested_game_id,
            "game_id": self.game_id,
            "scorecard_id": str(os.getenv("ARC_SCORECARD_ID", "") or "").strip() or None,
            "conversation_id": self.conversation_id,
            "guid": getattr(self.frame, "guid", None),
            "state": str(self.frame.state.value),
            "state_before_action": state_before_action,
            "state_changed_in_call": state_before_action != str(self.frame.state.value),
            "current_level": int(self.frame.levels_completed) + 1,
            "levels_completed": int(self.frame.levels_completed),
            "levels_before_action": int(levels_before_action),
            "win_levels": int(self.frame.win_levels),
            "levels_gained_in_call": int(self.frame.levels_completed) - int(levels_before_action),
            "full_reset": bool(getattr(self.frame, "full_reset", False)),
            "available_actions": [int(a) for a in self.frame.available_actions],
            **frame_action_metadata(self.frame),
            "steps_executed": len(step_snapshots),
            "step_results": step_results,
            "step_diffs": step_diffs,
            "aggregate_diff": aggregate_diff,
            "trace_file": trace_rel,
            "state_file": str((self.arc_dir / "state.json")),
            "transitions": transitions,
            "script_stdout": script_output,
            "script_error": script_error or None,
            "repl": {
                "conversation_id": self.conversation_id,
                "session_created": session_created,
                "daemon_pid": os.getpid(),
            },
        }
        return result

    def do_status(self, requested_game_id: str, *, session_created: bool) -> dict:
        if requested_game_id and not _same_game_lineage(self.game_id, requested_game_id):
            raise RuntimeError(
                f"active REPL game_id={self.game_id!r} does not match requested_game_id={requested_game_id!r}"
            )

        state_before = str(self.frame.state.value)
        levels_before = int(self.frame.levels_completed)
        self.turn += 1
        self._sync_history_file()
        trace_path = self._write_state_artifacts(
            action_label="status",
            script_output="",
            error="",
            pre_pixels=None,
            step_snapshots=[],
            step_results=[],
        )
        return self._finalize_result(
            action="status",
            requested_game_id=requested_game_id,
            state_before_action=state_before,
            levels_before_action=levels_before,
            pre_pixels=None,
            step_snapshots=[],
            step_results=[],
            script_output="",
            script_error="",
            transitions=[],
            trace_path=trace_path,
            session_created=session_created,
        )

    def do_reset_level(self, requested_game_id: str, *, session_created: bool) -> dict:
        if requested_game_id and not _same_game_lineage(self.game_id, requested_game_id):
            raise RuntimeError(
                f"active REPL game_id={self.game_id!r} does not match requested_game_id={requested_game_id!r}"
            )

        state_before = str(self.frame.state.value)
        levels_before = int(self.frame.levels_completed)
        self.frame = _call_quiet(self.env.reset)
        if self.frame is None:
            raise RuntimeError("env.reset() returned None")
        self.pixels = _get_pixels(self.env, self.frame)
        self.events.append({"kind": "reset"})
        self.turn += 1
        self._sync_history_file()

        trace_path = self._write_state_artifacts(
            action_label="reset_level",
            script_output="",
            error="",
            pre_pixels=None,
            step_snapshots=[],
            step_results=[],
        )
        return self._finalize_result(
            action="reset_level",
            requested_game_id=requested_game_id,
            state_before_action=state_before,
            levels_before_action=levels_before,
            pre_pixels=None,
            step_snapshots=[],
            step_results=[],
            script_output="",
            script_error="",
            transitions=[],
            trace_path=trace_path,
            session_created=session_created,
        )

    def do_exec(self, requested_game_id: str, script: str, *, session_created: bool) -> dict:
        if requested_game_id and not _same_game_lineage(self.game_id, requested_game_id):
            raise RuntimeError(
                f"active REPL game_id={self.game_id!r} does not match requested_game_id={requested_game_id!r}"
            )
        if not str(script or "").strip():
            raise RuntimeError("exec requires non-empty inline script")

        self._refresh_agent_lib()

        self.script_counter += 1
        script_label = f"<arc_repl_exec_{self.script_counter:04d}>"
        pre_pixels = np.array(self.pixels, copy=True)
        state_before = str(self.frame.state.value)
        levels_before = int(self.frame.levels_completed)

        transition_log: list[str] = []
        step_snapshots: list[tuple[str, np.ndarray]] = []
        step_results: list[dict] = []
        executed_events: list[dict] = []
        terminal_halt = False

        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()
        error = ""

        original_step = self.env.step

        def logging_step(action, data=None, reasoning=None):
            nonlocal terminal_halt
            if terminal_halt:
                raise _StopScript()
            action_enum, action_name = self._normalize_action(action)
            prev_state = str(self.frame.state.value)
            prev_levels = int(self.frame.levels_completed)
            frame = original_step(action_enum, data=data, reasoning=reasoning)
            if frame is None:
                raise RuntimeError("env.step() returned None")
            self.frame = frame
            current_pixels = _get_pixels(self.env, frame)
            changes = _iter_cell_changes(self.pixels, current_pixels)
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
                step_bbox = _change_bbox(changes)
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
            self.pixels = current_pixels
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

        self.env.step = logging_step
        self.globals["env"] = self.env
        self.globals["current"] = self.env

        try:
            with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
                exec(compile(script, script_label, "exec"), self.globals)
        except _StopScript:
            pass
        except BaseException:
            error = traceback.format_exc()
        finally:
            self.env.step = original_step

        worker_stderr = stderr_capture.getvalue().strip()
        script_output = stdout_capture.getvalue()
        if worker_stderr:
            script_output = (
                script_output
                + ("\n" if script_output and not script_output.endswith("\n") else "")
                + worker_stderr
                + "\n"
            )

        self.events.extend(executed_events)
        self.turn += 1
        self._sync_history_file()
        self._save_level_completion_records(
            levels_before_exec=levels_before,
            executed_events=executed_events,
            script_source=script,
        )

        trace_path = self._write_state_artifacts(
            action_label=f"exec({script_label})",
            script_output=script_output,
            error=error,
            pre_pixels=pre_pixels,
            step_snapshots=step_snapshots,
            step_results=step_results,
        )

        return self._finalize_result(
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


def _spawn_daemon(cwd: Path, conversation_id: str, game_id: str) -> None:
    session_dir = _session_dir(cwd, conversation_id)
    session_dir.mkdir(parents=True, exist_ok=True)

    socket_path = _socket_path(cwd, conversation_id)
    if socket_path.exists():
        try:
            socket_path.unlink()
        except Exception:
            pass

    log_path = _daemon_log_path(cwd, conversation_id)
    with log_path.open("a", encoding="utf-8") as logf:
        proc = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--daemon",
                "--cwd",
                str(cwd),
                "--conversation-id",
                conversation_id,
                "--game-id",
                game_id,
            ],
            cwd=str(cwd),
            env=dict(os.environ),
            stdin=subprocess.DEVNULL,
            stdout=logf,
            stderr=subprocess.STDOUT,
        )
    _pid_path(cwd, conversation_id).write_text(str(proc.pid) + "\n")


def _wait_for_daemon(cwd: Path, conversation_id: str, timeout_s: float = SOCKET_WAIT_TIMEOUT_S) -> None:
    socket_path = _socket_path(cwd, conversation_id)
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if socket_path.exists():
            try:
                conn = multiprocessing.connection.Client(str(socket_path), family="AF_UNIX")
            except Exception:
                time.sleep(0.05)
                continue
            try:
                conn.send({"action": "ping"})
                resp = conn.recv()
                if isinstance(resp, dict) and resp.get("ok"):
                    return
            except Exception:
                pass
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
        time.sleep(0.05)
    raise RuntimeError(f"arc_repl daemon did not start within {timeout_s}s")


def _send_request(cwd: Path, conversation_id: str, request: dict) -> tuple[dict, bool]:
    """Send request to conversation daemon, starting it if needed.

    Returns (response, session_created).
    """
    socket_path = _socket_path(cwd, conversation_id)
    session_created = False

    def _try_send() -> dict:
        conn = multiprocessing.connection.Client(str(socket_path), family="AF_UNIX")
        try:
            conn.send(request)
            resp = conn.recv()
            if not isinstance(resp, dict):
                raise RuntimeError("daemon returned non-object response")
            return resp
        finally:
            conn.close()

    try:
        return _try_send(), session_created
    except Exception:
        requested_game_id = str(request.get("game_id", "") or "").strip() or _default_game_id(cwd)
        if not requested_game_id:
            raise RuntimeError(
                "game_id is required (or initialize state first with action=status and game_id)"
            )
        _spawn_daemon(cwd, conversation_id, requested_game_id)
        _wait_for_daemon(cwd, conversation_id)
        session_created = True
        return _try_send(), session_created


def _daemon_main(cwd: Path, conversation_id: str, requested_game_id: str) -> int:
    session_dir = _session_dir(cwd, conversation_id)
    session_dir.mkdir(parents=True, exist_ok=True)

    socket_path = _socket_path(cwd, conversation_id)
    if socket_path.exists():
        try:
            socket_path.unlink()
        except Exception:
            pass

    session = ReplSession(cwd=cwd, conversation_id=conversation_id, requested_game_id=requested_game_id)
    _meta_path(cwd, conversation_id).write_text(
        json.dumps(
            {
                "conversation_id": conversation_id,
                "game_id": session.game_id,
                "socket": str(socket_path),
                "pid": os.getpid(),
                "started_at_unix": time.time(),
            },
            indent=2,
        )
        + "\n"
    )

    listener = multiprocessing.connection.Listener(str(socket_path), family="AF_UNIX")
    should_stop = False
    try:
        while not should_stop:
            conn = listener.accept()
            try:
                request = conn.recv()
                if not isinstance(request, dict):
                    conn.send({"ok": False, "error": "request must be an object"})
                    continue
                action = str(request.get("action", "")).strip()
                requested_game_id = str(request.get("game_id", "") or "").strip()

                if action == "ping":
                    conn.send({"ok": True, "action": "ping"})
                    continue
                if action == "status":
                    result = session.do_status(requested_game_id, session_created=False)
                elif action == "reset_level":
                    result = session.do_reset_level(requested_game_id, session_created=False)
                elif action == "exec":
                    script = str(request.get("script", "") or "")
                    result = session.do_exec(requested_game_id, script, session_created=False)
                elif action == "shutdown":
                    result = {
                        "schema_version": SCHEMA_VERSION,
                        "ok": True,
                        "action": "shutdown",
                        "conversation_id": conversation_id,
                        "game_id": session.game_id,
                    }
                    should_stop = True
                else:
                    result = _error(
                        action=action,
                        requested_game_id=requested_game_id,
                        message="unknown action. expected: status|exec|reset_level|shutdown",
                        error_type="unknown_action",
                    )
                conn.send(result)
            except Exception as exc:
                conn.send(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "ok": False,
                        "error": {
                            "type": "daemon_exception",
                            "message": str(exc),
                            "details": traceback.format_exc(),
                        },
                    }
                )
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
    finally:
        try:
            listener.close()
        except Exception:
            pass
        try:
            if socket_path.exists():
                socket_path.unlink()
        except Exception:
            pass
    return 0


def _parse_daemon_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--daemon", action="store_true")
    parser.add_argument("--cwd", default="")
    parser.add_argument("--conversation-id", default="")
    parser.add_argument("--game-id", default="")
    return parser.parse_args(argv)


def main() -> int:
    daemon_args = _parse_daemon_args(sys.argv[1:])
    if daemon_args.daemon:
        cwd = Path(daemon_args.cwd).resolve()
        conversation_id = str(daemon_args.conversation_id).strip() or _conversation_id()
        requested_game_id = str(daemon_args.game_id).strip()
        try:
            return _daemon_main(cwd, conversation_id, requested_game_id)
        except Exception:
            traceback.print_exc()
            return 1

    cwd = Path.cwd().resolve()
    args = _read_args()
    action = str(args.get("action", "")).strip() if isinstance(args, dict) else ""
    requested_game_id = str(args.get("game_id", "")).strip() if isinstance(args, dict) else ""

    if "_error" in args:
        _emit_json(
            _error(
                action=action or "status",
                requested_game_id=requested_game_id,
                message=str(args["_error"]),
                error_type="invalid_args",
            )
        )
        return 1

    if not action:
        _emit_json(
            _error(
                action="",
                requested_game_id=requested_game_id,
                message="missing required `action` (expected: status|exec|reset_level|shutdown)",
                error_type="missing_action",
            )
        )
        return 1

    if action == "exec" and not str(args.get("script", "") or "").strip():
        _emit_json(
            _error(
                action="exec",
                requested_game_id=requested_game_id,
                message="exec requires non-empty inline `script`",
                error_type="invalid_exec_args",
            )
        )
        return 1

    conversation_id = _conversation_id()
    request = {
        "action": action,
        "game_id": requested_game_id,
    }
    if action == "exec":
        request["script"] = str(args.get("script", ""))

    try:
        result, session_created = _send_request(cwd, conversation_id, request)
        if isinstance(result, dict):
            result.setdefault("schema_version", SCHEMA_VERSION)
            repl = result.get("repl") if isinstance(result.get("repl"), dict) else {}
            repl.setdefault("conversation_id", conversation_id)
            repl["session_created"] = bool(session_created or repl.get("session_created"))
            result["repl"] = repl
        if action == "exec":
            if not isinstance(result, dict):
                if result is not None:
                    sys.stdout.write(str(result))
                    if not str(result).endswith("\n"):
                        sys.stdout.write("\n")
                return 1
            script_stdout = str(result.get("script_stdout", "") or "")
            if script_stdout:
                sys.stdout.write(script_stdout)
                if not script_stdout.endswith("\n"):
                    sys.stdout.write("\n")
            if not bool(result.get("ok")):
                script_error = str(result.get("script_error", "") or "").strip()
                if script_error:
                    sys.stderr.write(script_error)
                    if not script_error.endswith("\n"):
                        sys.stderr.write("\n")
                else:
                    err = result.get("error")
                    if isinstance(err, dict):
                        msg = str(err.get("message", "") or "").strip()
                        details = str(err.get("details", "") or "").strip()
                        if msg:
                            sys.stderr.write(msg)
                            if not msg.endswith("\n"):
                                sys.stderr.write("\n")
                        if details:
                            sys.stderr.write(details)
                            if not details.endswith("\n"):
                                sys.stderr.write("\n")
                return 1
            return 0

        _emit_json(result)
        return 0 if bool(result.get("ok")) else 1
    except Exception as exc:
        _emit_json(
            _error(
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
