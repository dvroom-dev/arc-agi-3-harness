#!/usr/bin/env python3
"""ARC action execution tool for super custom tool-calling.

Reads JSON args from stdin and executes one of:
- action=status
- action=reset_level
- action=run_script (inline script only)

It persists deterministic replay history under ARC_STATE_DIR
so each invocation can reconstruct the current environment state.

Each run_script call auto-loads `agent_lib.py` from the run root before
executing the provided script, so helper functions can persist across turns.
"""

from __future__ import annotations

import io
import json
import multiprocessing
import os
import re
import sys
import traceback
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace

import numpy as np

import arc_agi
from arc_agi import OperationMode
from arcengine import GameAction
from arcengine.enums import FrameDataRaw

# Ensure imports from run workspace root resolve when executed as tools/arc_action.py
RUN_ROOT = Path(__file__).resolve().parent.parent
if str(RUN_ROOT) not in sys.path:
    sys.path.insert(0, str(RUN_ROOT))

ARC_COLORS_RGB = {
    # Matches ARC web preview renderer palette (https://three.arcprize.org).
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


def _resolve_environments_dir() -> Path:
    """Resolve shared environment directory with fail-fast validation."""
    env_value = os.getenv("ARC_ENVIRONMENTS_DIR", "").strip()
    if not env_value:
        raise RuntimeError("ARC_ENVIRONMENTS_DIR is required in OFFLINE mode")
    from_env = Path(env_value).expanduser()
    if not from_env.is_dir():
        raise RuntimeError(
            f"ARC_ENVIRONMENTS_DIR does not exist or is not a directory: {from_env}"
        )
    return from_env


def _resolve_operation_mode() -> OperationMode:
    value = os.getenv("ARC_OPERATION_MODE", "NORMAL").strip().upper()
    if value in OperationMode.__members__:
        return OperationMode[value]
    raise RuntimeError(
        f"Invalid ARC_OPERATION_MODE={value!r}. "
        f"Expected one of: {', '.join(OperationMode.__members__.keys())}"
    )


def _make_id_candidates(game_id: str) -> list[str]:
    normalized = str(game_id).strip()
    if not normalized:
        return []
    out = [normalized]
    # API-resolved ids can include version suffixes (e.g. ls20-cb3b57cc).
    # `arcade.make(...)` accepts base ids in NORMAL/ONLINE mode.
    if re.fullmatch(r".+-[0-9a-f]{8}", normalized):
        base = normalized.rsplit("-", 1)[0]
        if base and base not in out:
            out.append(base)
    return out


def _call_quiet(fn, *args, **kwargs):
    """Run call while suppressing noisy stdout/stderr from environment internals."""
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        return fn(*args, **kwargs)


def diff_grids(before: np.ndarray, after: np.ndarray) -> np.ndarray:
    return after.astype(np.int16) - before.astype(np.int16)


def _iter_cell_changes(before: np.ndarray, after: np.ndarray) -> list[tuple[int, int, int, int]]:
    changed = np.argwhere(before != after)
    return [(int(r), int(c), int(before[r, c]), int(after[r, c])) for r, c in changed]


def _change_bbox(changes: list[tuple[int, int, int, int]]) -> dict | None:
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


def _changes_sample(changes: list[tuple[int, int, int, int]], limit: int = 24) -> list[dict]:
    out: list[dict] = []
    for row, col, before, after in changes[:limit]:
        out.append(
            {"row": row, "col": col, "before": f"{before:X}", "after": f"{after:X}"}
        )
    return out


def format_diff_minimal(before: np.ndarray, after: np.ndarray) -> str:
    changes = _iter_cell_changes(before, after)
    if not changes:
        return "(no changes)"
    lines = [
        f"changed_pixels={len(changes)}",
        "format: (row,col): before->after",
    ]
    for row, col, prev, nxt in changes:
        lines.append(f"({row},{col}): {prev:X}->{nxt:X}")
    return "\n".join(lines)


def build_step_diff_records(
    pre_turn_pixels: np.ndarray | None,
    step_snapshots: list[tuple[str, np.ndarray]],
) -> list[dict]:
    if pre_turn_pixels is None or not step_snapshots:
        return []
    records: list[dict] = []
    for idx, (desc, snap) in enumerate(step_snapshots):
        prev = pre_turn_pixels if idx == 0 else step_snapshots[idx - 1][1]
        changes = _iter_cell_changes(prev, snap)
        records.append(
            {
                "step": idx + 1,
                "description": desc,
                "changed_pixels": len(changes),
                "changes": [
                    {"row": row, "col": col, "before": f"{before:X}", "after": f"{after:X}"}
                    for row, col, before, after in changes
                ],
            }
        )
    return records


def build_aggregate_diff_record(
    pre_turn_pixels: np.ndarray | None,
    final_pixels: np.ndarray,
) -> dict:
    if pre_turn_pixels is None:
        return {"changed_pixels": 0, "changes": []}
    changes = _iter_cell_changes(pre_turn_pixels, final_pixels)
    return {
        "changed_pixels": len(changes),
        "changes": [
            {"row": row, "col": col, "before": f"{before:X}", "after": f"{after:X}"}
            for row, col, before, after in changes
        ],
    }


def frame_action_metadata(frame: FrameDataRaw) -> dict:
    action_input = getattr(frame, "action_input", None)
    action_id_obj = getattr(action_input, "id", None)
    action_name = getattr(action_id_obj, "name", str(action_id_obj)) if action_id_obj is not None else ""
    action_id = getattr(action_id_obj, "value", None)
    if not isinstance(action_id, int):
        try:
            action_id = int(action_id) if action_id is not None else None
        except Exception:
            action_id = None
    data = getattr(action_input, "data", {}) if action_input is not None else {}
    reasoning = getattr(action_input, "reasoning", None) if action_input is not None else None
    return {
        "action_input_id": action_id,
        "action_input_name": action_name,
        "action_input_data": data,
        "action_input_reasoning": reasoning,
    }


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def render_grid_to_image(pixels: np.ndarray, path: Path, scale: int = 8) -> None:
    raise RuntimeError(
        "render_grid_to_image() is not available in arc_action.py; "
        "use game_state.render_grid_to_image from harness paths."
    )


def write_machine_state(
    directory: Path,
    frame: FrameDataRaw,
    pixels: np.ndarray,
    *,
    game_id: str,
    last_action: str,
    step_snapshots: list[tuple[str, np.ndarray]],
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    np.save(directory / "current_grid.npy", pixels.astype(np.int8))
    if step_snapshots:
        grids = np.stack([g for _, g in step_snapshots], axis=0).astype(np.int8)
    else:
        grids = np.empty((0, 64, 64), dtype=np.int8)
    np.save(directory / "all_grids.npy", grids)
    state = {
        "game_id": game_id,
        "current_level": frame.levels_completed + 1,
        "state": frame.state.value,
        "levels_completed": frame.levels_completed,
        "win_levels": frame.win_levels,
        "guid": getattr(frame, "guid", None),
        "available_actions": [int(a) for a in frame.available_actions],
        "last_action": last_action,
        "full_reset": bool(getattr(frame, "full_reset", False)),
        **frame_action_metadata(frame),
        "total_steps": len(step_snapshots),
        "steps": [desc for desc, _ in step_snapshots],
    }
    (directory / "state.json").write_text(json.dumps(state, indent=2))


def write_game_state(
    path: Path,
    frame: FrameDataRaw,
    pixels: np.ndarray,
    *,
    game_id: str,
    last_action: str,
    script_output: str,
    error: str,
    step_snapshots: list[tuple[str, np.ndarray]],
    pre_turn_pixels: np.ndarray | None,
) -> None:
    lines = [
        "# Game State",
        "",
        f"- game_id: {game_id}",
        f"- guid: {getattr(frame, 'guid', None)}",
        f"- state: {frame.state.value}",
        f"- levels_completed: {frame.levels_completed}",
        f"- win_levels: {frame.win_levels}",
        f"- last_action: {last_action}",
        f"- full_reset: {bool(getattr(frame, 'full_reset', False))}",
    ]
    action_meta = frame_action_metadata(frame)
    lines.extend(
        [
            f"- action_input_id: {action_meta['action_input_id']}",
            f"- action_input_name: {action_meta['action_input_name']}",
            f"- action_input_data: {json.dumps(action_meta['action_input_data'])}",
            f"- action_input_reasoning: {json.dumps(action_meta['action_input_reasoning'])}",
        ]
    )
    if error:
        lines.extend(["", "## Error", "```", error, "```"])
    if script_output:
        lines.extend(["", "## Script Output", "```", script_output, "```"])
    if pre_turn_pixels is not None:
        lines.extend(["", "## Initial Grid", "```"])
        for row in pre_turn_pixels:
            lines.append("".join(f"{int(v):X}" for v in row))
        lines.append("```")
    if pre_turn_pixels is not None and step_snapshots:
        lines.extend(["", "## Step Diffs"])
        for idx, (desc, snap) in enumerate(step_snapshots):
            prev = pre_turn_pixels if idx == 0 else step_snapshots[idx - 1][1]
            lines.extend(["", f"### Step {idx + 1}: {desc}", "```", format_diff_minimal(prev, snap), "```"])
        lines.extend(["", "## Aggregate Diff (Initial -> Final)", "```", format_diff_minimal(pre_turn_pixels, pixels), "```"])
    lines.extend(["", "## Grid", "```"])
    for row in pixels:
        lines.append("".join(f"{int(v):X}" for v in row))
    lines.append("```")
    path.write_text("\n".join(lines) + "\n")


def _read_args() -> dict:
    raw = io.TextIOWrapper(buffer=getattr(__import__("sys"), "stdin").buffer, encoding="utf-8").read().strip()
    if not raw:
        return {"_error": "missing JSON args on stdin"}
    try:
        parsed = json.loads(raw)
    except Exception as exc:
        return {"_error": f"invalid JSON args: {exc}"}
    if not isinstance(parsed, dict):
        return {"_error": "args must be a JSON object"}
    return parsed


def _emit_json(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, indent=2))
    if not sys.stdout.isatty():
        sys.stdout.write("\n")


def _error_payload(
    *,
    action: str,
    requested_game_id: str,
    message: str,
    error_type: str = "runtime_error",
    details: str | None = None,
) -> dict:
    payload = {
        "schema_version": "arc_action.v2",
        "ok": False,
        "action": action,
        "requested_game_id": requested_game_id or "",
        "error": {
            "type": error_type,
            "message": message,
        },
    }
    if details:
        payload["error"]["details"] = details
    return payload


def _arc_dir(cwd: Path) -> Path:
    state_dir_env = os.getenv("ARC_STATE_DIR", "").strip()
    if not state_dir_env:
        raise RuntimeError("ARC_STATE_DIR is required")
    arc = Path(state_dir_env).expanduser()
    arc.mkdir(parents=True, exist_ok=True)
    return arc


def _history_path(cwd: Path) -> Path:
    return _arc_dir(cwd) / "tool-engine-history.json"


LEVEL_COMPLETIONS_TEMPLATE = """# Level Completions

Canonical record of completed levels and the exact action sequence
for each completed level window.
"""

AGENT_LIB_TEMPLATE = """\"\"\"Persistent helper library for ARC scripts.

Define reusable functions here. Every `arc_action` run_script call auto-loads this file,
so your inline scripts can call helpers directly without imports or boilerplate.
\"\"\"

# Example:
# def step_many(env, action, count):
#     for _ in range(count):
#         env.step(action)
"""


def _level_completions_path(cwd: Path) -> Path:
    return _arc_dir(cwd) / "level_completions.md"


def _ensure_level_completions_file(cwd: Path) -> Path:
    path = _level_completions_path(cwd)
    if not path.exists():
        path.write_text(LEVEL_COMPLETIONS_TEMPLATE)
    return path


def _agent_lib_path(cwd: Path) -> Path:
    return cwd / "agent_lib.py"


def _ensure_agent_lib_file(cwd: Path) -> Path:
    path = _agent_lib_path(cwd)
    if not path.exists():
        path.write_text(AGENT_LIB_TEMPLATE)
    return path


def _read_max_recorded_completion_level(path: Path) -> int:
    pattern = re.compile(r"^## Level (\d+) Completion\s*$")
    max_level = 0
    if not path.exists():
        return max_level
    for line in path.read_text().splitlines():
        m = pattern.match(line.strip())
        if not m:
            continue
        try:
            lvl = int(m.group(1))
        except Exception:
            continue
        max_level = max(max_level, lvl)
    return max_level


def _completion_action_windows_by_level(events: list[dict]) -> dict[int, list[str]]:
    """Return per-level action windows from reset/completion boundaries.

    Boundary rules:
    - `reset` starts a new window at level 0.
    - A step that increases `levels_completed` closes the current level window;
      subsequent actions begin a new window for the next level.
    """
    windows: dict[int, list[str]] = {}
    current_actions: list[str] = []
    prev_levels = 0

    for event in events:
        kind = str(event.get("kind", "")).strip()
        if kind == "reset":
            current_actions = []
            prev_levels = 0
            continue
        if kind != "step":
            continue

        action_name = str(event.get("action", "")).strip()
        if action_name:
            current_actions.append(action_name)

        levels_now = event.get("levels_completed")
        if not isinstance(levels_now, int):
            continue

        if levels_now < prev_levels:
            # Defensive boundary for unexpected campaign regression.
            current_actions = []
        elif levels_now > prev_levels:
            window = list(current_actions)
            for completed_level in range(prev_levels + 1, levels_now + 1):
                windows[completed_level] = window
            current_actions = []

        prev_levels = levels_now
    return windows


def _append_level_completion(
    *,
    path: Path,
    completed_level: int,
    actions: list[str],
    tool_turn: int,
    winning_script_relpath: str | None,
) -> None:
    actions_preview = ", ".join(actions) if actions else "(none)"
    block = [
        "",
        f"## Level {completed_level} Completion",
        f"- tool_turn: {tool_turn}",
        f"- winning_script: {winning_script_relpath or '(not available)'}",
        f"- action_count_in_level_window: {len(actions)}",
        f"- actions_in_level_window: {actions_preview}",
    ]
    with open(path, "a") as f:
        f.write("\n".join(block) + "\n")


def _default_game_id(cwd: Path) -> str:
    state = _arc_dir(cwd) / "state.json"
    if state.is_file():
        try:
            data = json.loads(state.read_text())
            if not isinstance(data, dict):
                raise RuntimeError("state.json must contain a JSON object")
            gid = str(data.get("game_id", "")).strip()
            if gid:
                return gid
        except Exception as exc:
            raise RuntimeError(f"failed reading default game_id from {state}: {exc}") from exc
    return ""


def _load_history(cwd: Path, game_id: str) -> dict:
    path = _history_path(cwd)
    if not path.is_file():
        return {"game_id": game_id, "events": [], "turn": 0}
    try:
        data = json.loads(path.read_text())
    except Exception as exc:
        raise RuntimeError(f"failed to parse history file {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"invalid history file {path}: expected JSON object")
    history_game_id = str(data.get("game_id", "")).strip()
    if history_game_id != game_id:
        # Accept base/resolved-id lineage continuity (e.g., ls20 vs ls20-cb3b57cc),
        # but fail fast for unrelated game switches in the same state dir.
        hist_candidates = set(_make_id_candidates(history_game_id))
        req_candidates = set(_make_id_candidates(game_id))
        if hist_candidates.isdisjoint(req_candidates):
            raise RuntimeError(
                "history game_id mismatch: "
                f"history has {history_game_id!r}, requested {game_id!r}"
            )
    events = data.get("events")
    if not isinstance(events, list):
        raise RuntimeError(f"invalid history file {path}: events must be a list")
    turn = data.get("turn")
    if not isinstance(turn, int):
        raise RuntimeError(f"invalid history file {path}: turn must be an int")
    return {"game_id": game_id, "events": events, "turn": turn}


def _save_history(cwd: Path, history: dict) -> None:
    _history_path(cwd).write_text(json.dumps(history, indent=2))


def _get_pixels(env, frame: FrameDataRaw | None = None) -> np.ndarray:
    """Return the canonical 64x64 frame used by the API response.

    `game.get_pixels(...)` omits certain HUD updates (notably move-budget bar
    depletion/refill), so diffs should prefer `FrameDataRaw.frame[0]`.
    """
    if frame is not None:
        data = getattr(frame, "frame", None)
        if isinstance(data, (list, tuple)) and data:
            pixels = data[0]
            if isinstance(pixels, np.ndarray):
                return pixels
        raise RuntimeError(
            "FrameDataRaw.frame[0] is unavailable; cannot compute authoritative diff/state grid."
        )

    game = env._game
    return game.get_pixels(
        game.camera.x,
        game.camera.y,
        game.camera.width,
        game.camera.height,
    )


def _make_env(game_id: str):
    mode = _resolve_operation_mode()
    kwargs: dict[str, object] = {"operation_mode": mode}
    env_value = os.getenv("ARC_ENVIRONMENTS_DIR", "").strip()
    if env_value:
        kwargs["environments_dir"] = str(Path(env_value).expanduser())
    elif mode == OperationMode.OFFLINE:
        # OFFLINE requires local environments; keep backward-compatible discovery.
        kwargs["environments_dir"] = str(_resolve_environments_dir())
    arcade = arc_agi.Arcade(**kwargs)
    tried: list[str] = []
    for candidate in _make_id_candidates(game_id):
        tried.append(candidate)
        env = arcade.make(candidate, render_mode=None)
        if env is not None:
            return env
    raise RuntimeError(f"failed to load game: {game_id} (tried: {', '.join(tried)})")


def _action_from_event_name(name: str) -> GameAction:
    normalized = str(name).strip()
    if not normalized:
        raise RuntimeError(f"unknown action name in history: {name}")

    # Canonical enum member names (e.g. ACTION1, RESET).
    if hasattr(GameAction, normalized):
        return getattr(GameAction, normalized)

    # Backward compatibility for lowercase/mixed-case names.
    upper = normalized.upper()
    if hasattr(GameAction, upper):
        return getattr(GameAction, upper)

    # Backward compatibility for older history entries that serialized as
    # numeric strings like "1" instead of ACTION1.
    if re.fullmatch(r"-?\d+", normalized):
        numeric = int(normalized)
        for member in GameAction:
            try:
                if int(member.value) == numeric:
                    return member
            except Exception:
                continue

    raise RuntimeError(f"unknown action name in history: {name}")


def _replay_history(env, events: list[dict]) -> FrameDataRaw:
    frame = env.reset()
    if frame is None:
        raise RuntimeError("env.reset() returned None")
    for event in events:
        kind = str(event.get("kind", "")).strip()
        if kind == "reset":
            frame = env.reset()
            if frame is None:
                raise RuntimeError("env.reset() returned None during replay")
            continue
        if kind != "step":
            continue
        action_name = str(event.get("action", "")).strip()
        data = event.get("data")
        frame = env.step(_action_from_event_name(action_name), data=data)
        if frame is None:
            raise RuntimeError("env.step() returned None during replay")
    return frame


def _script_worker_main(conn, script_source: str, agent_lib_source: str, script_label: str) -> None:
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
            # Surface all payload keys directly for script ergonomics.
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
    safe_builtins = {
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

    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()
    worker_error = ""
    script_globals = {
        "__builtins__": safe_builtins,
        "env": _ScriptEnv(),
        "GameAction": game_action,
    }

    try:
        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
            if agent_lib_source.strip():
                exec(compile(agent_lib_source, "agent_lib.py", "exec"), script_globals)
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


def _execute_script(
    script_source: str,
    env,
    *,
    script_label: str,
    initial_frame: FrameDataRaw,
    agent_lib_source: str = "",
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

    def _normalize_action(action) -> tuple[GameAction, str]:
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

    last_pixels = _get_pixels(env, initial_frame)

    def logging_step(action, data=None, reasoning=None):
        nonlocal last_frame, terminal_halt, last_pixels
        if terminal_halt:
            raise _TerminalStateReached()
        action_enum, action_name = _normalize_action(action)
        prev_state = str(last_frame.state.value if last_frame is not None else initial_frame.state.value)
        prev_levels = int(last_frame.levels_completed if last_frame is not None else initial_frame.levels_completed)
        frame = original_step(action_enum, data=data, reasoning=reasoning)
        if frame is not None:
            last_frame = frame
            current_pixels = _get_pixels(env, frame)
            changes = _iter_cell_changes(last_pixels, current_pixels)
            step_index = len(step_results) + 1
            step_record = {
                "step": step_index,
                "action": action_name,
                "changed_pixels": len(changes),
                "change_bbox": _change_bbox(changes),
                "changes_sample": _changes_sample(changes),
                "state": str(frame.state.value),
                "state_before_step": prev_state,
                "state_changed_in_step": prev_state != str(frame.state.value),
                "levels_completed": int(frame.levels_completed),
                "levels_before_step": prev_levels,
                "levels_gained_in_step": int(frame.levels_completed) - prev_levels,
                "is_terminal": str(frame.state.value) in {"WIN", "GAME_OVER"},
            }
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
        return frame, (step_results[-1] if step_results else None)

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
                    # Backward-compatible alias for older scripts that checked len(step_diffs).
                    "step_diffs": [
                        {
                            "changed_pixels": int(step_info.get("changed_pixels", 0)),
                            "changes_sample": step_info.get("changes_sample", []),
                        }
                    ],
                }
            )
        return payload

    ctx = multiprocessing.get_context("spawn")
    parent_conn, child_conn = ctx.Pipe()
    proc = ctx.Process(target=_script_worker_main, args=(child_conn, script_source, agent_lib_source, script_label))
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
    if pre_pixels is not None:
        parts.extend(["", "## Initial Grid", "```"])
        for row in pre_pixels:
            parts.append("".join(f"{int(v):X}" for v in row))
        parts.append("```")
    if pre_pixels is not None and step_snapshots:
        parts.append("")
        parts.append("## Per-Step Diffs")
        for index, (desc, snap) in enumerate(step_snapshots):
            prev = pre_pixels if index == 0 else step_snapshots[index - 1][1]
            parts.extend(["", f"### Step {index + 1}: {desc}", "```", format_diff_minimal(prev, snap), "```"])
        parts.extend(["", "## Aggregate Diff (Initial -> Final)", "```", format_diff_minimal(pre_pixels, final_pixels), "```"])
    parts.extend(["", "## Final Grid", "```"])
    for row in final_pixels:
        parts.append("".join(f"{int(v):X}" for v in row))
    parts.append("```")
    trace_path.write_text("\n".join(parts) + "\n")
    return trace_path


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

        agent_lib_file = _ensure_agent_lib_file(cwd)
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
        step_snapshots: list[tuple[str, np.ndarray]] = []
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

            agent_lib_source = agent_lib_file.read_text()
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
                agent_lib_source=agent_lib_source,
            )
            if last_frame is not None:
                frame = last_frame
            action_label = f"run_script({script_label})"

            scripts_dir = arc_dir / "script-history"
            scripts_dir.mkdir(parents=True, exist_ok=True)
            turn_hint = turn + 1
            winning_script_file = scripts_dir / f"turn_{turn_hint:03d}_script.py"
            winning_script_file.write_text(script_source)

            # Record level completion(s) with per-level action windows derived
            # from reset/completion boundaries across prior + current events.
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
            final_pixels=final_pixels,
            script_output=script_output,
            error=error,
        )

        step_diff_records = build_step_diff_records(pre_pixels if action == "run_script" else None, step_snapshots)
        aggregate_diff = build_aggregate_diff_record(pre_pixels if action == "run_script" else None, final_pixels)
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
