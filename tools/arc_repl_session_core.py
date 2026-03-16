from __future__ import annotations
import json, os, re
from pathlib import Path
from typing import Any
import numpy as np
from arcengine import GameAction
try:
    from arc_repl_action_history import ActionHistoryStore
    from arc_repl_session_compat import (
        build_frame_snapshot,
        install_env_compat_bindings,
    )
    from arc_repl_session_artifacts import steps_since_level_start, write_state_artifacts
    from arc_repl_session_exec import execute_exec_turn  # noqa: F401
    from arc_repl_session_grid import (
        _chunk_for_bbox,
        _coerce_grid,
        _grid_from_hex_rows,  # noqa: F401
        _same_game_lineage,
    )
    from arc_repl_session_restore import restore_session_from_history
except Exception:
    from tools.arc_repl_action_history import ActionHistoryStore
    from tools.arc_repl_session_compat import (
        build_frame_snapshot,
        install_env_compat_bindings,
    )
    from tools.arc_repl_session_artifacts import steps_since_level_start, write_state_artifacts
    from tools.arc_repl_session_exec import execute_exec_turn  # noqa: F401
    from tools.arc_repl_session_grid import (
        _chunk_for_bbox,
        _coerce_grid,
        _grid_from_hex_rows,  # noqa: F401
        _same_game_lineage,
    )
    from tools.arc_repl_session_restore import restore_session_from_history
class BaseReplSession:
    def __init__(
        self,
        *,
        cwd: Path,
        conversation_id: str,
        requested_game_id: str,
        enable_history_functions: bool,
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
        self.frame = deps._reset_env_with_retry(
            self.env,
            context="at session start",
        )
        self.pixels = deps._get_pixels(self.env, self.frame)
        if self.events:
            self.events = restore_session_from_history(self, self.events)
        self.game_id = str(getattr(self.frame, "game_id", "")).strip() or game_id
        self.history["game_id"] = self.game_id
        self.action_history = ActionHistoryStore(
            path=self.arc_dir / "action-history.json",
            game_id=self.game_id,
            make_id_candidates=self.deps._make_id_candidates,
        )
        self.latest_turn_artifacts: dict[str, Any] | None = None
        self.action_history_path = self.action_history.path

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
            "get_frame": lambda: build_frame_snapshot(self),
            "diff": self.diff,
        }
        install_env_compat_bindings(self)
        self.history_functions_enabled = False
        self.set_history_helpers_enabled(bool(enable_history_functions))
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
    def _state_payload_for(self, frame, pixels: np.ndarray) -> dict:
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
            "grid_hex_rows": ["".join(f"{int(v):X}" for v in row) for row in pixels],
            "action_history_count": len(self.action_history.records),
            "action_history_file": str(self.action_history_path),
        }
    def _state_payload(self) -> dict:
        return self._state_payload_for(self.frame, self.pixels)
    def _append_action_history_record(
        self,
        *,
        call_action: str,
        action_name: str,
        action_data: Any,
        source: str | None,
        tool_turn: int,
        step_in_call: int,
        before_frame,
        before_pixels: np.ndarray,
        after_frame,
        after_pixels: np.ndarray,
    ) -> None:
        before_state = self._state_payload_for(before_frame, before_pixels)
        after_state = self._state_payload_for(after_frame, after_pixels)
        diff_payload = self.diff(before_state, after_state, output="json")
        self.action_history.append(
            call_action=call_action,
            action_name=action_name,
            action_data=action_data,
            source=source,
            tool_turn=tool_turn,
            step_in_call=step_in_call,
            state_before=before_state,
            state_after=after_state,
            diff_payload=diff_payload,
        )
    def get_action_record(self, action_index: int) -> dict | None:
        return self.action_history.get_record(action_index)
    def get_action_history(
        self,
        *,
        level: int | None = None,
        action_name: str | None = None,
        since: int | None = None,
        until: int | None = None,
        last: int | None = None,
    ) -> list[dict]:
        return self.action_history.get_history(
            level=level,
            action_name=action_name,
            since=since,
            until=until,
            last=last,
        )
    def set_history_helpers_enabled(self, enabled: bool) -> None:
        if enabled:
            self.globals["get_action_history"] = self.get_action_history
            self.globals["get_action_record"] = self.get_action_record
            self.history_functions_enabled = True
            return
        self.globals.pop("get_action_history", None)
        self.globals.pop("get_action_record", None)
        self.history_functions_enabled = False
    def _sync_history_file(self) -> None:
        self.history["game_id"] = self.game_id
        self.history["events"] = self.events
        self.history["turn"] = self.turn
        self.deps._save_history(self.cwd, self.history)
    def _reset_noop_reason(self) -> str | None:
        """Return noop reason when reset_level must not call env.reset()."""
        if steps_since_level_start(self.events) == 0:
            return "already_at_level_start"

        # Defense-in-depth: if the most recent recorded action was RESET_LEVEL
        # for this same level snapshot, treat another reset as consecutive noop
        # even if in-memory event counters are stale/missing.
        if self.action_history.records:
            last = self.action_history.records[-1]
            action_name = str(last.get("action_name", "")).strip().upper()
            if action_name == "RESET_LEVEL":
                try:
                    same_level = int(last.get("level_after", -1)) == (int(self.frame.levels_completed) + 1)
                    same_progress = int(last.get("levels_completed_after", -1)) == int(self.frame.levels_completed)
                except Exception:
                    same_level = False
                    same_progress = False
                if same_level and same_progress:
                    return "consecutive_reset_guard"
        return None
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
            "action_history_count": len(self.action_history.records),
            "action_history_file": str(self.action_history_path),
            "transitions": transitions,
            "script_stdout": script_output,
            "script_error": script_error or None,
            "repl": {
                "conversation_id": self.conversation_id,
                "session_created": session_created,
                "daemon_pid": os.getpid(),
            },
        }
        if action == "exec" and step_snapshots and self.latest_turn_artifacts:
            result["artifacts"] = dict(self.latest_turn_artifacts)
        return result
    def do_status(self, requested_game_id: str, *, session_created: bool) -> dict:
        if requested_game_id and not self._same_game_lineage(requested_game_id):
            raise RuntimeError(
                f"active REPL game_id={self.game_id!r} does not match requested_game_id={requested_game_id!r}"
            )

        state_before = str(self.frame.state.value)
        levels_before = int(self.frame.levels_completed)
        pre_pixels = np.array(self.pixels, copy=True)
        self.turn += 1
        self._sync_history_file()
        trace_path = write_state_artifacts(
            self,
            action_label="status",
            state_before_action=state_before,
            levels_before_action=levels_before,
            script_output="",
            error="",
            pre_pixels=pre_pixels,
            step_snapshots=[],
            step_results=[],
        )
        return self._finalize_result(
            action="status",
            requested_game_id=requested_game_id,
            state_before_action=state_before,
            levels_before_action=levels_before,
            pre_pixels=pre_pixels,
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
        before_frame = self.frame
        before_pixels = np.array(self.pixels, copy=True)
        call_turn = self.turn + 1
        noop_reason = self._reset_noop_reason()
        if noop_reason is not None:
            self.turn += 1
            self._sync_history_file()
            self._append_action_history_record(
                call_action="reset_level",
                action_name="RESET_LEVEL",
                action_data={},
                source="reset_level(noop)",
                tool_turn=call_turn,
                step_in_call=1,
                before_frame=before_frame,
                before_pixels=before_pixels,
                after_frame=self.frame,
                after_pixels=np.array(self.pixels, copy=True),
            )
            trace_path = write_state_artifacts(
                self,
                action_label="reset_level(noop)",
                state_before_action=state_before,
                levels_before_action=levels_before,
                script_output="",
                error="",
                pre_pixels=before_pixels,
                step_snapshots=[],
                step_results=[],
            )
            result = self._finalize_result(
                action="reset_level",
                requested_game_id=requested_game_id,
                state_before_action=state_before,
                levels_before_action=levels_before,
                pre_pixels=before_pixels,
                step_snapshots=[],
                step_results=[],
                script_output="",
                script_error="",
                transitions=[],
                trace_path=trace_path,
                session_created=session_created,
            )
            result["reset_noop"] = True
            result["noop_reason"] = noop_reason
            return result
        self.frame = self.env.reset()
        if self.frame is None:
            raise RuntimeError("env.reset() returned None")
        self.pixels = self.deps._get_pixels(self.env, self.frame)
        self.events.append({"kind": "reset"})
        self.turn += 1
        self._sync_history_file()
        self._append_action_history_record(
            call_action="reset_level",
            action_name="RESET_LEVEL",
            action_data={},
            source="reset_level",
            tool_turn=call_turn,
            step_in_call=1,
            before_frame=before_frame,
            before_pixels=before_pixels,
            after_frame=self.frame,
            after_pixels=np.array(self.pixels, copy=True),
        )
        trace_path = write_state_artifacts(
            self,
            action_label="reset_level",
            state_before_action=state_before,
            levels_before_action=levels_before,
            script_output="",
            error="",
            pre_pixels=before_pixels,
            step_snapshots=[],
            step_results=[],
        )
        result = self._finalize_result(
            action="reset_level",
            requested_game_id=requested_game_id,
            state_before_action=state_before,
            levels_before_action=levels_before,
            pre_pixels=before_pixels,
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
    def do_exec(
        self,
        requested_game_id: str,
        script: str,
        *,
        session_created: bool,
        source: str | None = None,
        script_path: str | None = None,
    ) -> dict:
        return execute_exec_turn(
            self,
            requested_game_id,
            script,
            session_created=session_created,
            source=source,
            script_path=script_path,
        )
