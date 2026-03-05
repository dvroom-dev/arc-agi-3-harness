from __future__ import annotations

import argparse
import io
import json
import sys
import traceback
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

import numpy as np
from arcengine import GameAction

from .utils import (
    action_from_name,
    diff_payload,
    discover_level_initial_states,
    from_jsonable,
    grid_from_hex_rows,
    grid_hex_rows,
    read_hex_grid,
    resolve_level_dir,
    session_state_path,
    to_jsonable,
)

MODEL_SESSION_SCHEMA_VERSION = 1


class ModelHooks:
    """Agent-owned mechanics hooks.

    model.py should implement these methods and delegate to this runtime.
    """

    def init_level(self, env: "ModelEnv", level: int) -> None:  # pragma: no cover - hook default
        _ = env, level

    def apply_action(  # pragma: no cover - hook default
        self,
        env: "ModelEnv",
        action: GameAction,
        *,
        data: dict | None = None,
        reasoning: str | None = None,
    ) -> None:
        _ = env, action, data, reasoning

    def is_level_complete(self, env: "ModelEnv") -> bool:  # pragma: no cover - hook default
        _ = env
        return False


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
        self.available_model_levels: list[int] = [1]
        self.current_level = 1
        self.win_levels = 7
        self.turn_budget = 100
        self.grid = np.zeros((8, 8), dtype=np.int8)
        self.refresh_level_initial_states()
        self._init_level(1)

    def refresh_level_initial_states(self) -> None:
        discovered = discover_level_initial_states(self.game_dir)
        self._level_initial_states = {k: np.array(v, dtype=np.int8, copy=True) for k, v in discovered.items()}
        levels = sorted(self._level_initial_states.keys())
        if not levels:
            levels = [1]
        self.available_model_levels = levels
        self.win_levels = max(7, int(levels[-1]))

    def initial_grid_for_level(self, level: int) -> np.ndarray:
        grid = self._level_initial_states.get(int(level))
        if grid is None:
            return np.zeros((8, 8), dtype=np.int8)
        return np.array(grid, dtype=np.int8, copy=True)

    def _init_level(self, level: int) -> None:
        self.current_level = int(level)
        self.turn = 0
        self.state = "NOT_FINISHED"
        self.full_reset = False
        self.grid = self.initial_grid_for_level(level)
        self.hooks.init_level(self, int(level))

    def step(self, action: GameAction, data=None, reasoning=None):
        self.hooks.apply_action(self, action, data=data, reasoning=reasoning)
        if self.hooks.is_level_complete(self):
            self.levels_completed += 1
            if self.levels_completed >= self.win_levels:
                self.state = "WIN"
            else:
                self._init_level(self.levels_completed + 1)
        return self

    def reset(self):
        self._init_level(self.current_level)
        return self


class ModelSession:
    def __init__(self, *, game_id: str, game_dir: Path, hooks: ModelHooks):
        self.game_dir = Path(game_dir)
        self.hooks = hooks
        self.env = ModelEnv(game_id, self.game_dir, self.hooks)
        self.state_path = session_state_path(self.game_dir, self.env.game_id)
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

    def _load_helper_file(self, path: Path, *, required: bool) -> None:
        if not path.exists():
            if required:
                raise RuntimeError(f"required helper file missing: {path}")
            return
        source = path.read_text()
        if not source.strip():
            return
        exec(compile(source, str(path), "exec"), self.globals)

    def _persist_env_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in self.env.__dict__.items():
            if key in {"action_space", "game_dir", "hooks"}:
                continue
            out[key] = value
        return out

    def _persist_to_disk(self, action_name: str) -> None:
        payload = {
            "schema_version": MODEL_SESSION_SCHEMA_VERSION,
            "game_id": str(self.env.game_id),
            "last_action_name": str(action_name),
            "env": to_jsonable(self._persist_env_dict()),
        }
        tmp = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2))
        tmp.replace(self.state_path)

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

    def get_state(self) -> dict:
        self.env.refresh_level_initial_states()
        return {
            "state": str(self.env.state),
            "current_level": int(self.env.current_level),
            "levels_completed": int(self.env.levels_completed),
            "win_levels": int(self.env.win_levels),
            "guid": getattr(self.env, "guid", None),
            "available_actions": [int(a) for a in getattr(self.env, "available_actions", [])],
            "available_model_levels": [int(v) for v in self.env.available_model_levels],
            "full_reset": bool(getattr(self.env, "full_reset", False)),
            "grid_hex_rows": grid_hex_rows(self.env.grid),
        }

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
        return {"ok": True, "action": "status", **self.get_state()}

    def do_reset_level(self) -> dict:
        self.env.reset()
        self._persist_to_disk("reset_level")
        return {"ok": True, "action": "reset_level", **self.get_state()}

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
        return {"ok": True, "action": "set_level", **self.get_state()}

    def do_exec(self, script: str) -> tuple[dict, int]:
        if not str(script or "").strip():
            return self._error("exec", "invalid_exec_args", "exec requires script content"), 1
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()
        try:
            with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
                exec(compile(script, "<model_exec>", "exec"), self.globals)
            self._persist_to_disk("exec")
            if stdout_capture.getvalue():
                print(stdout_capture.getvalue(), end="")
            if stderr_capture.getvalue():
                print(stderr_capture.getvalue(), end="", file=sys.stderr)
            return {"ok": True, "action": "exec", **self.get_state()}, 0
        except Exception as exc:
            return self._error("exec", "exec_error", str(exc), traceback.format_exc()), 1

    def do_exec_file(self, script_path: Path) -> tuple[dict, int]:
        if not script_path.exists():
            return self._error("exec_file", "missing_script_file", f"script file not found: {script_path}"), 1
        script = script_path.read_text()
        if not script.strip():
            return self._error("exec_file", "invalid_exec_file_args", "script file is empty"), 1
        payload, code = self.do_exec(script)
        payload["action"] = "exec_file"
        return payload, code

    def _compare_one_sequence(self, *, level: int, level_dir: Path, payload: dict) -> dict:
        compare_env = ModelEnv(self.env.game_id, self.game_dir, self.hooks)
        compare_env.levels_completed = int(level) - 1
        compare_env._init_level(level)
        seq_id = str(payload.get("sequence_id", "seq_unknown"))
        actions = list(payload.get("actions", []) or [])
        report: dict[str, Any] = {
            "level": int(level),
            "sequence_id": seq_id,
            "actions_total": int(len(actions)),
            "actions_compared": 0,
            "matched": True,
            "divergence_step": None,
            "divergence_reason": "",
            "game_step_diff": None,
            "model_step_diff": None,
            "state_diff": None,
        }
        for action in actions:
            local_step = int(action.get("local_step", 0) or 0)
            files = action.get("files", {}) if isinstance(action.get("files"), dict) else {}
            before_path = level_dir / str(files.get("before_state_hex", ""))
            after_path = level_dir / str(files.get("after_state_hex", ""))
            if not before_path.exists() or not after_path.exists():
                report["matched"] = False
                report["divergence_step"] = local_step
                report["divergence_reason"] = "missing_action_files"
                break
            game_before = read_hex_grid(before_path)
            game_after = read_hex_grid(after_path)
            model_before = np.array(compare_env.grid, dtype=np.int8, copy=True)
            if model_before.shape != game_before.shape or not np.array_equal(model_before, game_before):
                report["matched"] = False
                report["divergence_step"] = local_step
                report["divergence_reason"] = "before_state_mismatch"
                report["game_step_diff"] = diff_payload(game_before, game_after)
                report["model_step_diff"] = diff_payload(model_before, model_before)
                report["state_diff"] = diff_payload(game_before, model_before)
                break
            action_name = str(action.get("action_name", "")).strip()
            action_data = action.get("action_data", {}) if isinstance(action.get("action_data"), dict) else {}
            compare_env.step(action_from_name(action_name), data=action_data, reasoning=None)
            model_after = np.array(compare_env.grid, dtype=np.int8, copy=True)
            report["actions_compared"] = int(local_step)
            if model_after.shape != game_after.shape or not np.array_equal(model_after, game_after):
                report["matched"] = False
                report["divergence_step"] = local_step
                report["divergence_reason"] = "after_state_mismatch"
                report["game_step_diff"] = diff_payload(game_before, game_after)
                report["model_step_diff"] = diff_payload(model_before, model_after)
                report["state_diff"] = diff_payload(game_after, model_after)
                break
        return report

    def _report_md(self, report: dict) -> str:
        lines = [f"# Sequence Comparison: {report['sequence_id']}", ""]
        lines.append(f"- level: {int(report['level'])}")
        lines.append(f"- actions_total: {int(report['actions_total'])}")
        lines.append(f"- actions_compared: {int(report['actions_compared'])}")
        lines.append(f"- matched: {bool(report['matched'])}")
        if report.get("divergence_step") is not None:
            lines.append(f"- divergence_step: {int(report['divergence_step'])}")
            lines.append(f"- divergence_reason: {str(report.get('divergence_reason', ''))}")
        for section, value in (
            ("Game Step Diff", report.get("game_step_diff")),
            ("Model Step Diff", report.get("model_step_diff")),
            ("State Diff (Game After vs Model After)", report.get("state_diff")),
        ):
            if not value:
                continue
            lines.extend(["", f"## {section}", "```json", json.dumps(value, indent=2), "```"])
        return "\n".join(lines).rstrip() + "\n"

    def do_compare_sequences(self, *, level: int | None, sequence_id: str | None) -> tuple[dict, int]:
        target_level = int(level) if level is not None else int(self.env.current_level)
        level_dir = resolve_level_dir(self.game_dir, target_level)
        if level_dir is None:
            return self._error("compare_sequences", "missing_level_dir", f"missing level dir for level {target_level}"), 1
        seq_root = level_dir / "sequences"
        if not seq_root.exists():
            return self._error("compare_sequences", "missing_sequences", f"missing sequences dir: {seq_root}"), 1
        seq_files = [seq_root / f"{sequence_id}.json"] if sequence_id else sorted(seq_root.glob("seq_*.json"))
        if not seq_files or not all(p.exists() for p in seq_files):
            return self._error("compare_sequences", "missing_sequence", f"sequence not found under: {seq_root}"), 1
        compare_root = level_dir / "sequence_compare"
        compare_root.mkdir(parents=True, exist_ok=True)
        reports: list[dict] = []
        diverged = 0
        for seq_file in seq_files:
            payload = json.loads(seq_file.read_text())
            report = self._compare_one_sequence(level=target_level, level_dir=level_dir, payload=payload)
            report_file = compare_root / f"{report['sequence_id']}.md"
            report_file.write_text(self._report_md(report))
            report["report_file"] = str(report_file.relative_to(self.game_dir))
            reports.append(report)
            if not bool(report.get("matched", False)):
                diverged += 1
        self._persist_to_disk("compare_sequences")
        return {
            "ok": True,
            "action": "compare_sequences",
            "level": int(target_level),
            "compared_sequences": int(len(reports)),
            "diverged_sequences": int(diverged),
            "all_match": bool(diverged == 0),
            "reports": reports,
            **self.get_state(),
        }, 0

    def do_shutdown(self) -> dict:
        if self.state_path.exists():
            self.state_path.unlink()
        return {"ok": True, "action": "shutdown"}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local ARC model scaffold")
    sub = parser.add_subparsers(dest="action", required=True)
    for name in ("status", "reset_level", "exec"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--game-id", default="game")
    set_level_cmd = sub.add_parser("set_level")
    set_level_cmd.add_argument("--game-id", default="game")
    set_level_cmd.add_argument("level", type=int)
    compare_cmd = sub.add_parser("compare_sequences")
    compare_cmd.add_argument("--game-id", default="game")
    compare_cmd.add_argument("--level", type=int, default=None)
    compare_cmd.add_argument("--sequence", default=None)
    file_cmd = sub.add_parser("exec_file")
    file_cmd.add_argument("--game-id", default="game")
    file_cmd.add_argument("script_path")
    shutdown_cmd = sub.add_parser("shutdown")
    shutdown_cmd.add_argument("--game-id", default="game")
    return parser


def run_model_cli(hooks: ModelHooks, *, game_dir: Path, argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    session = ModelSession(game_id=getattr(args, "game_id", "game"), game_dir=game_dir, hooks=hooks)
    if args.action == "status":
        print(json.dumps(session.do_status(), indent=2))
        return 0
    if args.action == "reset_level":
        print(json.dumps(session.do_reset_level(), indent=2))
        return 0
    if args.action == "set_level":
        payload = session.do_set_level(int(args.level))
        print(json.dumps(payload, indent=2))
        return 0 if payload.get("ok") else 1
    if args.action == "compare_sequences":
        payload, code = session.do_compare_sequences(level=args.level, sequence_id=args.sequence)
        print(json.dumps(payload, indent=2))
        return code
    if args.action == "exec":
        payload, code = session.do_exec(sys.stdin.read())
        print(json.dumps(payload, indent=2))
        return code
    if args.action == "exec_file":
        payload, code = session.do_exec_file(Path(args.script_path))
        print(json.dumps(payload, indent=2))
        return code
    if args.action == "shutdown":
        print(json.dumps(session.do_shutdown(), indent=2))
        return 0
    print(json.dumps({"ok": False, "error": {"type": "unknown_action", "message": str(args.action)}}))
    return 1
