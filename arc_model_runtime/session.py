from __future__ import annotations

import io
import json
import os
import sys
import traceback
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from arcengine import GameAction

from .hooks import ModelHooks
from .state_views import state_payload, status_state, state_transition_flags
from .utils import (
    action_from_name,
    diff_payload,
    discover_level_initial_states,
    effective_analysis_level,
    from_jsonable,
    grid_from_hex_rows,
    grid_hex_rows,
    load_frontier_level_from_arc_state,
    model_status_path,
    read_hex_grid,
    resolve_level_dir,
    session_state_path,
    to_jsonable,
)
from .sequence_compare import compare_sequences as compare_sequences_impl
from .transition_diff import compare_transitions as compare_transitions_impl, diff_transition as diff_transition_impl
from .io_utils import write_json_atomic

MODEL_SESSION_SCHEMA_VERSION = 1
MODEL_STATUS_SCHEMA_VERSION = 1


def _persist_enabled() -> bool:
    raw = str(os.getenv("ARC_MODEL_PERSIST_STATUS", "") or "").strip().lower()
    return raw not in {"0", "false", "no", "off"}


class ModelEnv:
    def __init__(self, game_id: str, game_dir: Path, hooks: ModelHooks):
        self.game_id = str(game_id or "game")
        self.game_dir = Path(game_dir)
        self.hooks = hooks
        self.guid = "model-guid"
        self.state = "NOT_FINISHED"
        self.levels_completed = 0
        self.turn = 0
        self.full_reset = False
        self.available_actions = [int(a.value) for a in GameAction]
        self.action_space = [a for a in GameAction]
        self._level_initial_states: dict[int, np.ndarray] = {}
        self.available_model_levels: list[int] = []
        self.current_level = 1
        self.win_levels = 7
        self.turn_budget = 100
        self.level_complete = False
        self.last_step_level_complete = False
        self.last_completed_level: int | None = None
        self.game_over = False
        self.last_step_game_over = False
        self.last_game_over_level: int | None = None
        self.allow_missing_next_level_on_completion = True
        self.pending_level_init: int | None = None
        self.last_step_frames: list[np.ndarray] = []
        self.grid = np.zeros((0, 0), dtype=np.int8)
        self.refresh_level_initial_states()
        self._init_level(1)

    def refresh_level_initial_states(self) -> None:
        discovered = discover_level_initial_states(self.game_dir)
        self._level_initial_states = {k: np.array(v, dtype=np.int8, copy=True) for k, v in discovered.items()}
        levels = sorted(self._level_initial_states.keys())
        self.available_model_levels = levels
        if levels:
            self.win_levels = max(7, int(levels[-1]))

    def initial_grid_for_level(self, level: int) -> np.ndarray:
        grid = self._level_initial_states.get(int(level))
        if grid is None:
            discovered = [int(v) for v in self.available_model_levels]
            raise RuntimeError(
                f"missing initial_state.hex for level {int(level)}; "
                f"discovered initial states {discovered}"
            )
        return np.array(grid, dtype=np.int8, copy=True)

    def _init_level(self, level: int, *, clear_last_step_level_complete: bool = True) -> None:
        self.current_level = int(level)
        self.turn = 0
        self.state = "NOT_FINISHED"
        self.full_reset = False
        self.level_complete = False
        self.game_over = False
        self.pending_level_init = None
        if clear_last_step_level_complete:
            self.last_step_level_complete = False
            self.last_step_game_over = False
        self.last_step_frames = []
        self.grid = self.initial_grid_for_level(level)
        self.hooks.init_level(self, int(level))

    def set_step_frames(self, frames: list[np.ndarray] | list[list[list[int]]]) -> None:
        normalized: list[np.ndarray] = []
        for frame in frames:
            normalized.append(np.array(frame, dtype=np.int8, copy=True))
        self.last_step_frames = normalized

    def step(self, action: GameAction, data=None, reasoning=None):
        self.level_complete = False
        self.last_step_level_complete = False
        self.game_over = False
        self.last_step_game_over = False
        self.last_step_frames = []
        self.hooks.apply_action(self, action, data=data, reasoning=reasoning)
        if not self.last_step_frames:
            self.last_step_frames = [np.array(self.grid, dtype=np.int8, copy=True)]
        game_over = bool(self.hooks.is_game_over(self) or str(self.state) == "GAME_OVER")
        self.game_over = game_over
        self.last_step_game_over = game_over
        if game_over:
            self.last_game_over_level = int(self.current_level)
            self.state = "GAME_OVER"
            return self
        completed = bool(self.hooks.is_level_complete(self))
        self.level_complete = completed
        self.last_step_level_complete = completed
        if completed:
            completed_grid = np.array(self.grid, dtype=np.int8, copy=True)
            if not self.last_step_frames:
                self.last_step_frames = [completed_grid]
            self.last_completed_level = int(self.current_level)
            self.levels_completed += 1
            if self.levels_completed >= self.win_levels:
                self.state = "WIN"
            else:
                try:
                    self._init_level(
                        self.levels_completed + 1,
                        clear_last_step_level_complete=False,
                    )
                except RuntimeError:
                    if not bool(getattr(self, "allow_missing_next_level_on_completion", False)):
                        raise
                    self.pending_level_init = self.levels_completed + 1
                    self.current_level = int(self.last_completed_level or self.current_level)
                    self.grid = completed_grid
        return self

    def reset(self):
        self._init_level(self.current_level)
        return self


class ModelSession:
    def __init__(self, *, game_id: str, game_dir: Path, hooks: ModelHooks):
        self.game_dir = Path(game_dir)
        self.game_id = str(game_id or "game")
        self.hooks = hooks
        self.env = ModelEnv(self.game_id, self.game_dir, self.hooks)
        self.state_path = session_state_path(self.game_dir, self.env.game_id)
        self.model_status_path = model_status_path(self.game_dir)
        self.globals = {
            "np": np,
            "json": json,
            "env": self.env,
            "current": self.env,
            "GameAction": GameAction,
            "GA": GameAction,
            "get_state": self.get_state,
            "diff": self.diff,
        }
        self._load_helper_file(self.game_dir / "play_lib.py", required=False)
        self._load_helper_file(self.game_dir / "model_lib.py", required=False)
        if not self._restore_from_disk():
            self._persist_to_disk("status")

    def _model_status_summary(self, payload: dict[str, Any], *, action_name: str, exit_code: int) -> dict[str, Any]:
        state = self.get_status_state()
        summary: dict[str, Any] = {
            "schema_version": MODEL_STATUS_SCHEMA_VERSION,
            "runtime": "model",
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
            "game_id": str(self.env.game_id),
            "last_action_name": str(action_name),
            "ok": bool(payload.get("ok", False)),
            "exit_code": int(exit_code),
            "state": state,
        }
        if action_name == "compare_sequences":
            summary["compare"] = {
                "level": int(payload.get("level", state["current_level"])),
                "requested_sequences": int(payload.get("requested_sequences", 0) or 0),
                "eligible_sequences": int(payload.get("eligible_sequences", 0) or 0),
                "compared_sequences": int(payload.get("compared_sequences", 0) or 0),
                "diverged_sequences": int(payload.get("diverged_sequences", 0) or 0),
                "all_match": bool(payload.get("all_match", False)),
                "include_reset_ended": bool(payload.get("include_reset_ended", False)),
                "include_level_regressions": bool(payload.get("include_level_regressions", False)),
            }
            reports = payload.get("reports", [])
            if isinstance(reports, list):
                for report in reports:
                    if not isinstance(report, dict):
                        continue
                    if bool(report.get("matched", False)):
                        continue
                    summary["compare"]["first_divergence"] = {
                        "sequence_id": str(report.get("sequence_id", "")),
                        "divergence_step": report.get("divergence_step"),
                        "divergence_reason": str(report.get("divergence_reason", "")),
                    }
                    break
        elif not bool(payload.get("ok", False)):
            error = payload.get("error")
            if isinstance(error, dict):
                summary["error"] = {
                    "type": str(error.get("type", "")),
                    "message": str(error.get("message", "")),
                }
        return summary

    def persist_model_status(self, payload: dict[str, Any], *, action_name: str, exit_code: int) -> None:
        if not _persist_enabled():
            return
        summary = self._model_status_summary(payload, action_name=action_name, exit_code=exit_code)
        write_json_atomic(self.model_status_path, summary)

    def _load_helper_file(self, path: Path, *, required: bool) -> None:
        if not path.exists():
            if required:
                raise RuntimeError(f"required helper file missing: {path}")
            return
        source = path.read_text()
        if not source.strip():
            return
        old_file = self.globals.get("__file__", None)
        had_file = "__file__" in self.globals
        old_name = self.globals.get("__name__", None)
        had_name = "__name__" in self.globals
        self.globals["__file__"] = str(path.resolve())
        self.globals["__name__"] = "__main__"
        try:
            exec(compile(source, str(path), "exec"), self.globals)
        finally:
            if had_file:
                self.globals["__file__"] = old_file
            else:
                self.globals.pop("__file__", None)
            if had_name:
                self.globals["__name__"] = old_name
            else:
                self.globals.pop("__name__", None)

    def _persist_env_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in self.env.__dict__.items():
            if key in {"action_space", "game_dir", "hooks"}:
                continue
            out[key] = value
        return out

    def _persist_to_disk(self, action_name: str) -> None:
        if not _persist_enabled():
            return
        payload = {
            "schema_version": MODEL_SESSION_SCHEMA_VERSION,
            "game_id": str(self.env.game_id),
            "last_action_name": str(action_name),
            "env": to_jsonable(self._persist_env_dict()),
        }
        write_json_atomic(self.state_path, payload)

    def _restore_from_disk(self) -> bool:
        if not self.state_path.exists():
            return False
        payload = json.loads(self.state_path.read_text())
        if int(payload.get("schema_version", 0)) != MODEL_SESSION_SCHEMA_VERSION:
            return False
        if str(payload.get("game_id", "")) != str(self.env.game_id):
            return False
        env_data = from_jsonable(payload.get("env", {}))
        if not isinstance(env_data, dict):
            return False
        for key, value in env_data.items():
            setattr(self.env, key, value)
        self.env.action_space = [a for a in GameAction]
        self.env.refresh_level_initial_states()
        return True

    def _sync_to_frontier_level(self, *, action_name: str) -> dict | None:
        self.env.refresh_level_initial_states()
        pending_level = int(self.env.pending_level_init) if self.env.pending_level_init is not None else None
        if pending_level is not None:
            valid_levels = set(int(v) for v in self.env.available_model_levels)
            if action_name == "status":
                return None
            return self._error(
                action_name,
                "missing_initial_state",
                f"visible level {pending_level} is active for model work but no initial_state.hex "
                f"was discovered; discovered initial states {sorted(valid_levels)}",
            )
        frontier_level = load_frontier_level_from_arc_state()
        if frontier_level is None:
            return None
        visible_level = effective_analysis_level(self.game_dir, frontier_level=int(frontier_level))
        lvl = int(visible_level) if visible_level is not None else int(frontier_level)
        valid_levels = set(int(v) for v in self.env.available_model_levels)
        if lvl not in valid_levels:
            return self._error(
                action_name,
                "missing_initial_state",
                f"visible level {lvl} is active for model work but no initial_state.hex "
                f"was discovered; discovered initial states {sorted(valid_levels)}",
            )
        desired_completed = max(0, lvl - 1)
        if self.env.current_level == lvl and self.env.levels_completed == desired_completed:
            return None
        self.env.levels_completed = desired_completed
        self.env._init_level(lvl)
        self._persist_to_disk("sync_frontier")
        return None

    def get_state(self) -> dict:
        return state_payload(self.env)

    def get_status_state(self) -> dict:
        """Public model status surface for CLI output/artifacts.

        Keep this compact and artifact-focused. Do not leak internal runtime
        scaffolding like the model env grid snapshot or synthetic action list.
        """
        return status_state(game_dir=self.game_dir, env=self.env)

    def diff(self, before_state, after_state, output: str = "json"):
        before = np.array(before_state, copy=True) if isinstance(before_state, np.ndarray) else grid_from_hex_rows(before_state)
        after = np.array(after_state, copy=True) if isinstance(after_state, np.ndarray) else grid_from_hex_rows(after_state)
        payload = diff_payload(before, after)
        if str(output).lower() == "text":
            if payload.get("shape_mismatch"):
                return f"shape mismatch before={payload['before_shape']} after={payload['after_shape']}"
            if int(payload.get("changed_pixels", 0) or 0) == 0:
                return "(no changes)"
            lines = [f"changed_pixels={payload['changed_pixels']}"]
            for item in payload.get("changes", []):
                lines.append(f"({item['row']},{item['col']}): {item['before']}->{item['after']}")
            return "\n".join(lines)
        return payload

    def _error(self, action: str, err_type: str, message: str, details: str | None = None) -> dict:
        payload = {"ok": False, "action": action, "error": {"type": err_type, "message": message}}
        if details is not None:
            payload["error"]["details"] = details
        return payload

    def do_status(self) -> dict:
        synced_error = self._sync_to_frontier_level(action_name="status")
        if synced_error is not None:
            return synced_error
        return {"ok": True, "action": "status", **self.get_status_state()}

    def do_reset_level(self) -> dict:
        synced_error = self._sync_to_frontier_level(action_name="reset_level")
        if synced_error is not None:
            return synced_error
        self.env.reset()
        self._persist_to_disk("reset_level")
        return {"ok": True, "action": "reset_level", **self.get_status_state()}

    def do_set_level(self, level: int) -> dict:
        self.env.refresh_level_initial_states()
        lvl = int(level)
        valid_levels = set(int(v) for v in self.env.available_model_levels)
        if lvl not in valid_levels:
            return self._error(
                "set_level",
                "invalid_level",
                f"level must be in discovered initial states {sorted(valid_levels)}; got {lvl}",
            )
        self.env.levels_completed = lvl - 1
        self.env._init_level(lvl)
        self._persist_to_disk("set_level")
        return {"ok": True, "action": "set_level", **self.get_status_state()}

    def do_exec(self, script: str, *, script_path: Path | None = None) -> tuple[dict, int]:
        if not str(script or "").strip():
            return self._error("exec", "invalid_exec_args", "exec requires script content"), 1
        synced_error = self._sync_to_frontier_level(action_name="exec")
        if synced_error is not None:
            return synced_error, 1
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()
        old_file = self.globals.get("__file__", None)
        had_file = "__file__" in self.globals
        old_name = self.globals.get("__name__", None)
        had_name = "__name__" in self.globals
        compile_label = "<model_exec>"
        if script_path is not None:
            try:
                resolved = str(Path(script_path).expanduser().resolve())
            except Exception:
                resolved = str(script_path)
            self.globals["__file__"] = resolved
            compile_label = resolved
        self.globals["__name__"] = "__main__"
        try:
            with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
                exec(compile(script, compile_label, "exec"), self.globals)
            self._persist_to_disk("exec")
            if stdout_capture.getvalue():
                print(stdout_capture.getvalue(), end="")
            if stderr_capture.getvalue():
                print(stderr_capture.getvalue(), end="", file=sys.stderr)
            return {"ok": True, "action": "exec", **self.get_status_state()}, 0
        except Exception as exc:
            return self._error("exec", "exec_error", str(exc), traceback.format_exc()), 1
        finally:
            if had_file:
                self.globals["__file__"] = old_file
            else:
                self.globals.pop("__file__", None)
            if had_name:
                self.globals["__name__"] = old_name
            else:
                self.globals.pop("__name__", None)

    def do_exec_file(self, script_path: Path, *, reset_level_first: bool = False) -> tuple[dict, int]:
        if not script_path.exists():
            return self._error("exec_file", "missing_script_file", f"script file not found: {script_path}"), 1
        script = script_path.read_text()
        if not script.strip():
            return self._error("exec_file", "invalid_exec_file_args", "script file is empty"), 1
        reset_payload = None
        if reset_level_first:
            reset_payload = self.do_reset_level()
            if not reset_payload.get("ok"):
                return reset_payload, 1
        payload, code = self.do_exec(script, script_path=script_path)
        payload["action"] = "exec_file"
        if reset_level_first:
            payload["reset_level_first"] = True
            payload["reset_before_exec"] = {
                "performed": not bool(reset_payload.get("reset_noop")),
                "noop_reason": reset_payload.get("noop_reason"),
            }
        return payload, code

    def do_compare_sequences(
        self,
        *,
        level: int | None,
        sequence_id: str | None,
        include_reset_ended: bool = False,
        include_level_regressions: bool = False,
    ) -> tuple[dict, int]:
        if level is None:
            synced_error = self._sync_to_frontier_level(action_name="compare_sequences")
            if synced_error is not None:
                return synced_error, 1
        return compare_sequences_impl(
            self,
            level=level,
            sequence_id=sequence_id,
            include_reset_ended=include_reset_ended,
            include_level_regressions=include_level_regressions,
        )

    def do_diff_transition(
        self,
        *,
        level: int,
        sequence_id: str,
        local_step: int,
    ) -> tuple[dict, int]:
        try:
            payload = diff_transition_impl(
                game_dir=self.game_dir,
                level=int(level),
                sequence_id=str(sequence_id),
                local_step=int(local_step),
            )
            return payload, 0
        except Exception as exc:
            return self._error("diff_transition", "transition_diff_error", str(exc)), 1

    def do_compare_transitions(
        self,
        *,
        a_level: int,
        a_sequence_id: str,
        a_local_step: int,
        b_level: int,
        b_sequence_id: str,
        b_local_step: int,
    ) -> tuple[dict, int]:
        try:
            payload = compare_transitions_impl(
                game_dir=self.game_dir,
                a_level=int(a_level),
                a_sequence_id=str(a_sequence_id),
                a_local_step=int(a_local_step),
                b_level=int(b_level),
                b_sequence_id=str(b_sequence_id),
                b_local_step=int(b_local_step),
            )
            return payload, 0
        except Exception as exc:
            return self._error("compare_transitions", "transition_diff_error", str(exc)), 1

    def do_shutdown(self) -> dict:
        if self.state_path.exists():
            self.state_path.unlink()
        if self.model_status_path.exists():
            self.model_status_path.unlink()
        return {"ok": True, "action": "shutdown"}
