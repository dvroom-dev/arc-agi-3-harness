#!/usr/bin/env python3
"""Local simulator scaffold with an arc_repl-compatible command surface.

Supported commands:
  - status [--game-id GAME]
  - reset_level [--game-id GAME]
  - exec [--game-id GAME]          (reads script from stdin)
  - exec_file [--game-id GAME] PATH
  - shutdown

Dry-run workflow:
  - Run `./simulate.py exec_file ./play.py` before `arc_repl exec_file ./play.py`.
  - Compare simulator output and real-game output to maintain parity.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import traceback
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from arcengine import GameAction


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
        self.value = int(getattr(action, "value", action))


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


@dataclass(frozen=True)
class LevelConfig:
    level_num: int
    name: str
    turn_budget: int


LEVEL_REGISTRY = {
    1: LevelConfig(level_num=1, name="level_1", turn_budget=100),
}


class SimulatorEnv:
    """Incremental simulator scaffold.

    Organize mechanics as:
    1) always-on base mechanics in `_apply_base_mechanics`
    2) level-specific additions in `_apply_level_mechanics`
    """

    def __init__(self, game_id):
        self.game_id = str(game_id or "game")
        self.guid = "sim-guid"
        self.state = "NOT_FINISHED"
        self.levels_completed = 0
        self.win_levels = 7
        self.full_reset = False
        self.turn = 0
        self.available_actions = [int(a.value) for a in GameAction]
        self.action_space = [a for a in GameAction]

        self.current_level = 1
        self.turn_budget = 100
        self.grid = np.zeros((8, 8), dtype=np.int8)
        self._init_level(1)

    def _init_level(self, level_num: int) -> None:
        cfg = LEVEL_REGISTRY.get(level_num)
        self.current_level = level_num
        self.turn = 0
        self.state = "NOT_FINISHED"
        self.full_reset = False
        if cfg is not None:
            self.turn_budget = int(cfg.turn_budget)
        self.grid = np.zeros((8, 8), dtype=np.int8)

    def _apply_base_mechanics(self, action, data=None, reasoning=None):
        """Mechanics shared across levels."""
        _ = action, data, reasoning
        self.turn += 1
        self.turn_budget -= 1

    def _apply_level_1(self, action, data=None, reasoning=None):
        """Level 1-only mechanics.

        Replace this with game-specific mechanics validated by evidence.
        """
        _ = action, data, reasoning

    def _apply_level_mechanics(self, action, data=None, reasoning=None):
        """Level-specific mechanics dispatcher."""
        handler = getattr(self, f"_apply_level_{self.current_level}", None)
        if callable(handler):
            handler(action, data=data, reasoning=reasoning)

    def _check_level_complete(self):
        """Set completion transition when level win condition is met."""
        # TODO: Replace with evidence-backed completion condition.
        return False

    def step(self, action, data=None, reasoning=None):
        self._apply_base_mechanics(action, data=data, reasoning=reasoning)
        self._apply_level_mechanics(action, data=data, reasoning=reasoning)
        if self._check_level_complete():
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
        self.env = SimulatorEnv(game_id)
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

    def get_state(self):
        frame = self.frame
        return {
            "state": str(frame.state.value),
            "current_level": int(frame.levels_completed) + 1,
            "levels_completed": int(frame.levels_completed),
            "win_levels": int(frame.win_levels),
            "guid": getattr(frame, "guid", None),
            "available_actions": [int(a) for a in getattr(frame, "available_actions", [])],
            "full_reset": bool(getattr(frame, "full_reset", False)),
            "grid_hex_rows": ["".join(f"{int(v):X}" for v in row) for row in self.grid],
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
        self.frame = self.env.reset()
        self.grid = np.array(self.frame.frame[-1], dtype=np.int8, copy=True)
        return {"ok": True, "action": "reset_level", **self.get_state()}

    def execute(self, script):
        if not str(script or "").strip():
            raise RuntimeError("exec requires non-empty script")
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()
        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
            exec(compile(script, "<simulator_exec>", "exec"), self.globals)
        stdout = stdout_capture.getvalue()
        stderr = stderr_capture.getvalue()
        if stdout:
            print(stdout, end="")
        if stderr:
            print(stderr, end="", file=sys.stderr)

    def shutdown(self):
        return {"ok": True, "action": "shutdown"}


def _build_parser():
    parser = argparse.ArgumentParser(description="Local ARC simulator scaffold")
    sub = parser.add_subparsers(dest="action", required=True)
    for name in ("status", "reset_level", "exec"):
        command = sub.add_parser(name)
        command.add_argument("--game-id", default="game")
    file_cmd = sub.add_parser("exec_file")
    file_cmd.add_argument("--game-id", default="game")
    file_cmd.add_argument("script_path")
    sub.add_parser("shutdown")
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
