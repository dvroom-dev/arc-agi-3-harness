#!/usr/bin/env python3
"""Local model scaffold with an arc_repl-compatible command surface.
Supported commands:
  - status [--game-id GAME]
  - reset_level [--game-id GAME]
  - set_level [--game-id GAME] LEVEL
  - exec [--game-id GAME]          (reads script from stdin)
  - exec_file [--game-id GAME] PATH
  - shutdown [--game-id GAME]
State model:
  - Commands persist model session state per game-id to disk.
  - `set_level` therefore persists across subsequent `exec` / `exec_file` calls.
  - `shutdown` removes persisted model session state for that game-id.
Dry-run workflow:
  - Run `python3 "$GAME_DIR/model.py" exec_file "$GAME_DIR/play.py"` before `arc_repl exec_file "$GAME_DIR/play.py"`.
  - Compare model output and real-game output to maintain parity.
"""
from __future__ import annotations
import argparse
import io
import json
import re
import sys
import traceback
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import numpy as np
from arcengine import GameAction
import model_lib
def _coerce_grid(value, fallback):
    if value is None:
        return np.array(fallback, copy=True)
    if isinstance(value, np.ndarray):
        return np.array(value, copy=True)
    if isinstance(value, dict):
        rows = value.get("grid_hex_rows")
        if isinstance(rows, list):
            value = rows
    if isinstance(value, list):
        if value and all(isinstance(item, str) for item in value):
            return np.array([[int(ch, 16) for ch in row] for row in value], dtype=np.int8)
        return np.array(value, dtype=np.int8, copy=True)
    frame = getattr(value, "frame", None)
    if isinstance(frame, (list, tuple)) and frame:
        return np.array(frame[-1], dtype=np.int8, copy=True)
    raise RuntimeError("unsupported grid value")
def _iter_changes(before, after):
    changed = np.argwhere(before != after)
    out = []
    for row, col in changed:
        out.append((int(row), int(col), int(before[row, col]), int(after[row, col])))
    return out
def _change_bbox(changes):
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
def _chunk_for_bbox(grid, bbox, pad=0):
    if not bbox:
        return {"bbox": None, "rows_hex": []}
    r0 = max(0, int(bbox["min_row"]) - int(pad))
    c0 = max(0, int(bbox["min_col"]) - int(pad))
    r1 = min(grid.shape[0] - 1, int(bbox["max_row"]) + int(pad))
    c1 = min(grid.shape[1] - 1, int(bbox["max_col"]) + int(pad))
    sub = grid[r0 : r1 + 1, c0 : c1 + 1]
    rows_hex = ["".join(f"{int(v):X}" for v in row) for row in sub]
    return {
        "bbox": {"min_row": r0, "max_row": r1, "min_col": c0, "max_col": c1},
        "rows_hex": rows_hex,
    }
class _StateValue:
    def __init__(self, value):
        self.value = str(value)
class _ActionId:
    def __init__(self, action):
        self.name = str(getattr(action, "name", action))
        raw = getattr(action, "value", action)
        try:
            self.value = int(raw)
        except (TypeError, ValueError):
            self.value = 0
class _ActionInput:
    def __init__(self, action, data=None, reasoning=None):
        self.id = _ActionId(action)
        self.data = data or {}
        self.reasoning = reasoning
class _Frame:
    def __init__(self, env, action_name="status"):
        self.game_id = env.game_id
        self.guid = env.guid
        self.state = _StateValue(env.state)
        self.levels_completed = int(env.levels_completed)
        self.win_levels = int(env.win_levels)
        self.available_actions = list(env.available_actions)
        self.full_reset = bool(env.full_reset)
        self.action_input = _ActionInput(action_name)
        self.frame = [np.array(env.grid, dtype=np.int8, copy=True)]
# Keep model.py thin: all level data/mechanics belong in model_lib.py.
MODEL_SESSION_SCHEMA_VERSION = 1
def _sanitize_game_id(game_id: str) -> str:
    text = str(game_id or "game")
    sanitized = re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("._")
    return sanitized or "game"
def _session_state_path(game_dir: Path, game_id: str) -> Path:
    return game_dir / f".model_session_{_sanitize_game_id(game_id)}.json"
def _to_jsonable(value):
    if isinstance(value, np.ndarray):
        return {
            "__type__": "ndarray",
            "dtype": str(value.dtype),
            "data": value.tolist(),
        }
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, GameAction):
        return {"__type__": "game_action", "value": int(value.value)}
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return {"__type__": "tuple", "items": [_to_jsonable(v) for v in value]}
    if isinstance(value, set):
        return {"__type__": "set", "items": [_to_jsonable(v) for v in sorted(value, key=repr)]}
    if isinstance(value, list):
        return [_to_jsonable(v) for v in value]
    return value
def _from_jsonable(value):
    if isinstance(value, list):
        return [_from_jsonable(v) for v in value]
    if isinstance(value, dict):
        t = value.get("__type__")
        if t == "ndarray":
            return np.array(value.get("data", []), dtype=np.int8)
        if t == "game_action":
            return GameAction(int(value.get("value", 0)))
        if t == "tuple":
            return tuple(_from_jsonable(v) for v in value.get("items", []))
        if t == "set":
            return set(_from_jsonable(v) for v in value.get("items", []))
        return {k: _from_jsonable(v) for k, v in value.items()}
    return value
def _load_helper_file(path: Path, globals_dict: dict, *, required: bool) -> None:
    if not path.exists():
        if required:
            raise RuntimeError(f"required helper file missing: {path}")
        return
    source = path.read_text()
    if not source.strip():
        return
    exec(compile(source, str(path), "exec"), globals_dict)
class ModelEnv:
    """Game model with evidence-backed mechanics for LS20."""
    def __init__(self, game_id):
        self.game_id = str(game_id or "game")
        self.guid = "model-guid"
        self.state = "NOT_FINISHED"
        self.levels_completed = 0
        self.win_levels = 5
        self.full_reset = False
        self.turn = 0
        self.available_actions = [1, 2, 3, 4]
        self.action_space = [a for a in GameAction]
        self.current_level = 1
        self.grid = np.zeros((model_lib.GRID_SIZE, model_lib.GRID_SIZE), dtype=np.int8)
        self.player_pos = (0, 0)
        self.hud_symbol = [[0, 0, 0], [0, 0, 0], [0, 0, 0]]
        self.exit_active = False
        self.cross_consumed = False
        self.rotations_done = 0
        self.turns_remaining = 42
        self.lives = 3
        self.level_complete = False
        self.game_over = False
        self.refills_consumed = []
        self._init_level(1)
    def _init_level(self, level_num: int) -> None:
        cfg = model_lib.get_level_config(level_num)
        self.current_level = level_num
        self.turn = 0
        self.state = "NOT_FINISHED"
        self.full_reset = False
        self.level_complete = False
        self.game_over = False
        self.cross_consumed = False
        self.shape_consumed = False
        self.exit_active = False
        self.rotations_done = 0
        self.gate_matched = False
        self.gate_cleared = False
        if cfg is not None:
            self.grid = model_lib.load_initial_grid(level_num)
            self.player_pos = cfg.player_start
            self.hud_symbol = [r[:] for r in cfg.hud_symbol]
            self.turns_remaining = cfg.turn_budget
            self.refills_consumed = [False] * len(cfg.yellow_refill_positions)
            self.hud_color = cfg.hud_symbol_color
            self.rainbow_consumed = False
        else:
            self.grid = np.zeros((model_lib.GRID_SIZE, model_lib.GRID_SIZE), dtype=np.int8)
            self.player_pos = (0, 0)
            self.hud_symbol = [[0, 0, 0], [0, 0, 0], [0, 0, 0]]
            self.turns_remaining = 42
            self.refills_consumed = []
            self.hud_color = 0x9
            self.rainbow_consumed = False
    def step(self, action, data=None, reasoning=None):
        self.turn += 1
        model_lib.apply_shared_model_mechanics(self, action, data=data, reasoning=reasoning)
        if self.game_over:
            self.state = "GAME_OVER"
            self.full_reset = True
            self.levels_completed = 0
            self._init_level(1)
        elif self.level_complete:
            self.levels_completed += 1
            if self.levels_completed >= self.win_levels:
                self.state = "WIN"
            else:
                self._init_level(self.levels_completed + 1)
        return _Frame(self, action_name=getattr(action, "name", str(action)))
    def reset(self):
        self._init_level(self.current_level)
        return _Frame(self, action_name="reset_level")
class Session:
    def __init__(self, game_id):
        self.game_dir = Path(__file__).resolve().parent
        self.env = ModelEnv(game_id)
        self.state_path = _session_state_path(self.game_dir, self.env.game_id)
        self.current = self.env
        self.frame = self.env.reset()
        self.grid = np.array(self.frame.frame[-1], dtype=np.int8, copy=True)
        self.globals = {
            "np": np,
            "json": json,
            "env": self.env,
            "current": self.current,
            "GameAction": GameAction,
            "GA": GameAction,
            "get_state": self.get_state,
            "diff": self.diff,
        }
        _load_helper_file(self.game_dir / "play_lib.py", self.globals, required=False)
        _load_helper_file(self.game_dir / "model_lib.py", self.globals, required=True)
        restored = self._restore_from_disk()
        if not restored:
            self._sync_from_env(action_name="status")
            self._persist_to_disk(action_name="status")
    def _persist_env_dict(self):
        out = {}
        for key, value in self.env.__dict__.items():
            if key == "action_space":
                continue
            out[key] = value
        return out
    def _persist_to_disk(self, action_name="status"):
        payload = {
            "schema_version": MODEL_SESSION_SCHEMA_VERSION,
            "game_id": str(self.env.game_id),
            "last_action_name": str(action_name),
            "env": _to_jsonable(self._persist_env_dict()),
        }
        tmp = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2))
        tmp.replace(self.state_path)
    def _restore_from_disk(self) -> bool:
        if not self.state_path.exists():
            return False
        payload = json.loads(self.state_path.read_text())
        version = int(payload.get("schema_version", 0))
        if version != MODEL_SESSION_SCHEMA_VERSION:
            raise RuntimeError(
                f"unsupported model session schema in {self.state_path}: "
                f"{version} != {MODEL_SESSION_SCHEMA_VERSION}"
            )
        persisted_game_id = str(payload.get("game_id", ""))
        if persisted_game_id != str(self.env.game_id):
            raise RuntimeError(
                f"model session game_id mismatch in {self.state_path}: "
                f"{persisted_game_id!r} != {self.env.game_id!r}"
            )
        env_data = _from_jsonable(payload.get("env", {}))
        if not isinstance(env_data, dict):
            raise RuntimeError(f"invalid env payload in {self.state_path}")
        for key, value in env_data.items():
            setattr(self.env, key, value)
        # Reconstruct derived runtime-only fields.
        self.env.action_space = [a for a in GameAction]
        if not isinstance(getattr(self.env, "available_actions", None), list):
            self.env.available_actions = [int(a.value) for a in GameAction]
        self.env.grid = _coerce_grid(getattr(self.env, "grid", None), np.zeros((8, 8), dtype=np.int8))
        self.env.win_levels = max(int(getattr(self.env, "win_levels", 0)), 5)
        last_action_name = str(payload.get("last_action_name", "status"))
        self._sync_from_env(action_name=last_action_name)
        return True
    def _sync_from_env(self, action_name="status"):
        self.frame = _Frame(self.env, action_name=action_name)
        self.grid = np.array(self.env.grid, dtype=np.int8, copy=True)
    def get_state(self):
        env = self.env
        self._sync_from_env(action_name="status")
        return {
            "state": str(env.state),
            "current_level": int(env.current_level),
            "levels_completed": int(env.levels_completed),
            "win_levels": int(env.win_levels),
            "guid": getattr(env, "guid", None),
            "available_actions": [int(a) for a in getattr(env, "available_actions", [])],
            "full_reset": bool(getattr(env, "full_reset", False)),
            "grid_hex_rows": ["".join(f"{int(v):X}" for v in row) for row in env.grid],
        }
    def diff(self, before_state, after_state, output="json", pad=0):
        before = _coerce_grid(before_state, self.grid)
        after = _coerce_grid(after_state, self.grid)
        changes = _iter_changes(before, after)
        bbox = _change_bbox(changes)
        if str(output).lower() == "text":
            if not changes:
                return "(no changes)"
            lines = [f"changed_pixels={len(changes)}", "format: (row,col): before->after"]
            for row, col, b, a in changes:
                lines.append(f"({row},{col}): {b:X}->{a:X}")
            return "\n".join(lines)
        return {
            "changed_pixels": len(changes),
            "bbox": bbox,
            "before": _chunk_for_bbox(before, bbox, pad=pad),
            "after": _chunk_for_bbox(after, bbox, pad=pad),
            "changes": [
                {"row": row, "col": col, "before": f"{b:X}", "after": f"{a:X}"}
                for row, col, b, a in changes
            ],
        }
    def status(self):
        return {"ok": True, "action": "status", **self.get_state()}
    def reset_level(self):
        self.env.reset()
        self._sync_from_env(action_name="reset_level")
        self._persist_to_disk(action_name="reset_level")
        return {"ok": True, "action": "reset_level", **self.get_state()}
    def set_level(self, level: int):
        if level < 1 or level > int(self.env.win_levels):
            return {
                "ok": False,
                "action": "set_level",
                "error": {
                    "type": "invalid_level",
                    "message": f"level must be in [1, {int(self.env.win_levels)}], got {level}",
                },
            }
        self.env.levels_completed = int(level) - 1
        self.env._init_level(int(level))
        self._sync_from_env(action_name="set_level")
        self._persist_to_disk(action_name="set_level")
        return {"ok": True, "action": "set_level", **self.get_state()}
    def execute(self, script):
        if not str(script or "").strip():
            raise RuntimeError("exec requires non-empty script")
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()
        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
            exec(compile(script, "<model_exec>", "exec"), self.globals)
        self._sync_from_env(action_name="exec")
        self._persist_to_disk(action_name="exec")
        stdout = stdout_capture.getvalue()
        stderr = stderr_capture.getvalue()
        if stdout:
            print(stdout, end="")
        if stderr:
            print(stderr, end="", file=sys.stderr)
    def shutdown(self):
        if self.state_path.exists():
            self.state_path.unlink()
        return {"ok": True, "action": "shutdown"}
def _build_parser():
    parser = argparse.ArgumentParser(description="Local ARC model scaffold")
    sub = parser.add_subparsers(dest="action", required=True)
    for name in ("status", "reset_level", "exec"):
        command = sub.add_parser(name)
        command.add_argument("--game-id", default="game")
    set_level_cmd = sub.add_parser("set_level")
    set_level_cmd.add_argument("--game-id", default="game")
    set_level_cmd.add_argument("level", type=int)
    file_cmd = sub.add_parser("exec_file")
    file_cmd.add_argument("--game-id", default="game")
    file_cmd.add_argument("script_path")
    shutdown_cmd = sub.add_parser("shutdown")
    shutdown_cmd.add_argument("--game-id", default="game")
    return parser
def _print_json(payload):
    print(json.dumps(payload, indent=2))
def main():
    args = _build_parser().parse_args()
    session = Session(getattr(args, "game_id", "game"))
    if args.action == "status":
        _print_json(session.status())
        return 0
    if args.action == "reset_level":
        _print_json(session.reset_level())
        return 0
    if args.action == "set_level":
        payload = session.set_level(int(args.level))
        _print_json(payload)
        return 0 if payload.get("ok") else 1
    if args.action == "shutdown":
        _print_json(session.shutdown())
        return 0
    if args.action == "exec":
        script = sys.stdin.read()
        if not str(script or "").strip():
            _print_json(
                {
                    "ok": False,
                    "action": "exec",
                    "error": {
                        "type": "invalid_exec_args",
                        "message": "exec requires script content on stdin",
                    },
                }
            )
            return 1
        try:
            session.execute(script)
            _print_json({"ok": True, "action": "exec", **session.get_state()})
            return 0
        except Exception as exc:
            _print_json(
                {
                    "ok": False,
                    "action": "exec",
                    "error": {"type": "exec_error", "message": str(exc), "details": traceback.format_exc()},
                }
            )
            return 1
    if args.action == "exec_file":
        script_path = Path(args.script_path)
        if not script_path.exists():
            _print_json(
                {
                    "ok": False,
                    "action": "exec_file",
                    "error": {
                        "type": "missing_script_file",
                        "message": f"script file not found: {script_path}",
                    },
                }
            )
            return 1
        try:
            script = script_path.read_text()
            if not str(script or "").strip():
                _print_json(
                    {
                        "ok": False,
                        "action": "exec_file",
                        "error": {
                            "type": "invalid_exec_file_args",
                            "message": "script file is empty",
                        },
                    }
                )
                return 1
            session.execute(script)
            _print_json({"ok": True, "action": "exec_file", **session.get_state()})
            return 0
        except Exception as exc:
            _print_json(
                {
                    "ok": False,
                    "action": "exec_file",
                    "error": {
                        "type": "exec_file_error",
                        "message": str(exc),
                        "details": traceback.format_exc(),
                    },
                }
            )
            return 1
    _print_json({"ok": False, "error": {"type": "unknown_action", "message": f"unknown action: {args.action}"}})
    return 1
if __name__ == "__main__":
    raise SystemExit(main())
