from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import numpy as np
from arcengine import GameAction

try:
    from arc_repl_session_exec import _StopScript, execute_exec_turn
    from arc_repl_session_grid import (
        _chunk_for_bbox,
        _coerce_grid,
        _grid_from_hex_rows,
        _same_game_lineage,
    )
except Exception:
    from tools.arc_repl_session_exec import _StopScript, execute_exec_turn
    from tools.arc_repl_session_grid import (
        _chunk_for_bbox,
        _coerce_grid,
        _grid_from_hex_rows,
        _same_game_lineage,
    )


class BaseReplSession:
    def __init__(
        self,
        *,
        cwd: Path,
        conversation_id: str,
        requested_game_id: str,
        deps,
    ) -> None:
        self.cwd = cwd
        self.conversation_id = conversation_id
        self.deps = deps
        self.arc_dir = deps._arc_dir(cwd)
        self.session_dir = deps._session_dir(cwd, conversation_id)
        self.session_dir.mkdir(parents=True, exist_ok=True)

        game_id = str(requested_game_id or "").strip() or deps._default_game_id(cwd)
        if not game_id:
            raise RuntimeError(
                "game_id is required (or initialize state first with action=status and game_id)"
            )

        self.play_lib_file = deps._ensure_play_lib_file(cwd)
        self.completions_path = deps._ensure_level_completions_file(cwd)
        self.history = deps._load_history(cwd, game_id)
        self.turn = int(self.history.get("turn", 0))
        self.events: list[dict] = list(self.history.get("events", []))

        self.env = deps._make_env(game_id)
        self.frame = deps._replay_history(self.env, self.events)
        self.pixels = deps._get_pixels(self.env, self.frame)
        self.game_id = str(getattr(self.frame, "game_id", "")).strip() or game_id
        self.history["game_id"] = self.game_id

        self.script_counter = 0
        self.last_play_lib_mtime_ns: int | None = None
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
        self._refresh_play_lib(force=True)

    def _same_game_lineage(self, requested_game_id: str) -> bool:
        return _same_game_lineage(
            self.game_id,
            requested_game_id,
            self.deps._make_id_candidates,
        )

    def _refresh_play_lib(self, *, force: bool = False) -> None:
        try:
            stat = self.play_lib_file.stat()
            mtime_ns = int(stat.st_mtime_ns)
        except Exception:
            return
        if not force and self.last_play_lib_mtime_ns == mtime_ns:
            return
        source = self.play_lib_file.read_text()
        exec(compile(source, str(self.play_lib_file), "exec"), self.globals)
        self.last_play_lib_mtime_ns = mtime_ns

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
            **self.deps.frame_action_metadata(frame),
            "grid_hex_rows": ["".join(f"{int(v):X}" for v in row) for row in self.pixels],
        }

    def _sync_history_file(self) -> None:
        self.history["game_id"] = self.game_id
        self.history["events"] = self.events
        self.history["turn"] = self.turn
        self.deps._save_history(self.cwd, self.history)

    def _steps_since_level_start(self) -> int:
        steps_in_level = 0
        current_levels = 0
        for event in self.events:
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
        self.deps.write_game_state(
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
        self.deps.write_machine_state(
            self.arc_dir,
            self.frame,
            final_pixels,
            game_id=self.game_id,
            last_action=action_label,
            step_snapshots=step_snapshots,
        )
        return self.deps._write_turn_trace(
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
        script_source: str,
    ) -> str | None:
        levels_after_exec = int(self.frame.levels_completed)
        if levels_after_exec <= levels_before_exec:
            return None

        scripts_dir = self.arc_dir / "script-history"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        script_file = scripts_dir / f"turn_{self.turn:03d}_script.py"
        script_file.write_text(script_source)

        max_recorded = self.deps._read_max_recorded_completion_level(self.completions_path)
        completion_windows = self.deps._completion_action_windows_by_level(self.events)

        try:
            script_rel = str(script_file.relative_to(self.cwd))
        except Exception:
            script_rel = str(script_file)

        for completed_level in range(levels_before_exec + 1, levels_after_exec + 1):
            if completed_level <= max_recorded:
                continue
            actions = completion_windows.get(completed_level, [])
            self.deps._append_level_completion(
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
        member = self.deps._action_from_event_name(name)
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
        changes = self.deps._iter_cell_changes(before, after)
        bbox = self.deps._change_bbox(changes)
        if str(output).lower() == "text":
            return self.deps.format_diff_minimal(before, after)
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
        step_diffs = self.deps.build_step_diff_records(
            pre_pixels,
            step_snapshots,
            step_results=step_results,
        )
        aggregate_diff = self.deps.build_aggregate_diff_record(
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
            "schema_version": self.deps.SCHEMA_VERSION,
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
            **self.deps.frame_action_metadata(self.frame),
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
        if requested_game_id and not self._same_game_lineage(requested_game_id):
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
        if requested_game_id and not self._same_game_lineage(requested_game_id):
            raise RuntimeError(
                f"active REPL game_id={self.game_id!r} does not match requested_game_id={requested_game_id!r}"
            )

        state_before = str(self.frame.state.value)
        levels_before = int(self.frame.levels_completed)
        if self._steps_since_level_start() == 0:
            self.turn += 1
            self._sync_history_file()
            trace_path = self._write_state_artifacts(
                action_label="reset_level(noop)",
                script_output="",
                error="",
                pre_pixels=None,
                step_snapshots=[],
                step_results=[],
            )
            result = self._finalize_result(
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
            result["reset_noop"] = True
            result["noop_reason"] = "already_at_level_start"
            return result

        self.frame = self.env.reset()
        if self.frame is None:
            raise RuntimeError("env.reset() returned None")
        self.pixels = self.deps._get_pixels(self.env, self.frame)
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
        result = self._finalize_result(
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
        result["reset_noop"] = False
        return result

    def do_exec(self, requested_game_id: str, script: str, *, session_created: bool) -> dict:
        return execute_exec_turn(
            self,
            requested_game_id,
            script,
            session_created=session_created,
        )
