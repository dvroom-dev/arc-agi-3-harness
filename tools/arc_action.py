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
import os
import re
import sys
import traceback
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

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
    """Resolve shared environment store across current and legacy run layouts."""
    env_value = os.getenv("ARC_ENVIRONMENTS_DIR", "").strip()
    if env_value:
        from_env = Path(env_value).expanduser()
        if from_env.is_dir():
            return from_env

    candidates: list[Path] = []

    # Prefer cwd-relative discovery because tool cwd is run agent dir.
    cwd = Path.cwd().resolve()
    for base in [cwd, *cwd.parents]:
        candidates.append(base / "environment_files")

    # Back-compat for older layouts that inferred from script location.
    for base in [RUN_ROOT, *RUN_ROOT.parents]:
        candidates.append(base / "environment_files")

    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate.is_dir():
            return candidate

    # Last-resort fallback.
    return cwd / "environment_files"


def _resolve_operation_mode() -> OperationMode:
    value = os.getenv("ARC_OPERATION_MODE", "NORMAL").strip().upper()
    if value in OperationMode.__members__:
        return OperationMode[value]
    return OperationMode.NORMAL


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
    # Disabled by default: numeric diff/state artifacts are authoritative and
    # image generation adds cost/noise without improving tool-grounded reasoning.
    return


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
        return {}
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
    if state_dir_env:
        arc = Path(state_dir_env).expanduser()
    else:
        arc = cwd / ".ai-supervisor" / "arc"
    arc.mkdir(parents=True, exist_ok=True)
    return arc


def _history_path(cwd: Path) -> Path:
    return _arc_dir(cwd) / "tool-engine-history.json"


LEVEL_COMPLETIONS_TEMPLATE = """# Level Completions

Canonical record of completed levels and the exact action sequence
executed since the most recent reset at the time of completion.
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
    pattern = re.compile(r"^## Level (\d+) Completion\\s*$")
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


def _actions_since_last_reset(events: list[dict]) -> list[str]:
    last_reset_idx = -1
    for idx, event in enumerate(events):
        if str(event.get("kind", "")).strip() == "reset":
            last_reset_idx = idx
    actions: list[str] = []
    for event in events[last_reset_idx + 1 :]:
        if str(event.get("kind", "")).strip() != "step":
            continue
        name = str(event.get("action", "")).strip()
        if name:
            actions.append(name)
    return actions


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
        f"- action_count_since_last_reset: {len(actions)}",
        f"- actions_since_last_reset: {actions_preview}",
    ]
    with open(path, "a") as f:
        f.write("\n".join(block) + "\n")


def _default_game_id(cwd: Path) -> str:
    state = _arc_dir(cwd) / "state.json"
    if state.is_file():
        try:
            data = json.loads(state.read_text())
            gid = str(data.get("game_id", "")).strip()
            if gid:
                return gid
        except Exception:
            pass
    return ""


def _load_history(cwd: Path, game_id: str) -> dict:
    path = _history_path(cwd)
    if not path.is_file():
        return {"game_id": game_id, "events": [], "turn": 0}
    try:
        data = json.loads(path.read_text())
    except Exception:
        return {"game_id": game_id, "events": [], "turn": 0}
    if not isinstance(data, dict):
        return {"game_id": game_id, "events": [], "turn": 0}
    if str(data.get("game_id", "")).strip() != game_id:
        return {"game_id": game_id, "events": [], "turn": 0}
    events = data.get("events")
    if not isinstance(events, list):
        events = []
    turn = data.get("turn")
    if not isinstance(turn, int):
        turn = 0
    return {"game_id": game_id, "events": events, "turn": turn}


def _save_history(cwd: Path, history: dict) -> None:
    _history_path(cwd).write_text(json.dumps(history, indent=2))


def _get_pixels(env, frame: FrameDataRaw | None = None) -> np.ndarray:
    """Return the canonical 64x64 frame used by the API response.

    `game.get_pixels(...)` omits certain HUD updates (notably move-budget bar
    depletion/refill), so diffs should prefer `FrameDataRaw.frame[0]`.
    """
    if frame is not None:
        try:
            data = frame.frame
            if isinstance(data, list) and data:
                pixels = data[0]
                if isinstance(pixels, np.ndarray):
                    return pixels
        except Exception:
            pass

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


def _execute_script(
    script_source: str,
    env,
    *,
    script_label: str,
    agent_lib_source: str = "",
) -> tuple[FrameDataRaw | None, str, str, list[str], list[tuple[str, np.ndarray]], list[dict]]:
    transition_log: list[str] = []
    step_snapshots: list[tuple[str, np.ndarray]] = []
    executed_events: list[dict] = []
    last_frame: FrameDataRaw | None = None
    terminal_halt = False

    class _TerminalStateReached(Exception):
        pass

    original_step = env.step
    original_reset = env.reset

    def logging_step(action, data=None, reasoning=None):
        nonlocal last_frame, terminal_halt
        if terminal_halt:
            raise _TerminalStateReached()
        frame = original_step(action, data=data, reasoning=reasoning)
        if frame is not None:
            last_frame = frame
            # Persist canonical action names so replay is stable even when
            # scripts pass numeric ids to env.step(...).
            action_name = str(action)
            try:
                if isinstance(action, GameAction):
                    action_name = action.name
                elif isinstance(action, int):
                    for member in GameAction:
                        try:
                            if int(member.value) == int(action):
                                action_name = member.name
                                break
                        except Exception:
                            continue
                else:
                    candidate = str(action).strip()
                    if re.fullmatch(r"-?\d+", candidate):
                        for member in GameAction:
                            try:
                                if int(member.value) == int(candidate):
                                    action_name = member.name
                                    break
                            except Exception:
                                continue
                    elif hasattr(GameAction, candidate):
                        action_name = getattr(GameAction, candidate).name
                    elif hasattr(GameAction, candidate.upper()):
                        action_name = getattr(GameAction, candidate.upper()).name
            except Exception:
                action_name = str(action)
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
            try:
                step_snapshots.append((desc, _get_pixels(env, frame)))
            except Exception:
                pass
            if frame.state.value in {"WIN", "GAME_OVER"}:
                terminal_halt = True
                raise _TerminalStateReached()
        return frame

    def blocked_reset():
        raise RuntimeError("env.reset() cannot be called inside run_script; use action=reset_level")

    env.step = logging_step
    env.reset = blocked_reset

    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()
    error = ""
    script_globals = {"__builtins__": __builtins__, "env": env, "GameAction": GameAction, "np": np}

    try:
        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
            if agent_lib_source.strip():
                exec(compile(agent_lib_source, "agent_lib.py", "exec"), script_globals)
            exec(compile(script_source, script_label, "exec"), script_globals)
    except _TerminalStateReached:
        pass
    except BaseException:
        error = traceback.format_exc()
    finally:
        env.step = original_step
        env.reset = original_reset

    return last_frame, stdout_capture.getvalue(), error, transition_log, step_snapshots, executed_events


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
    action = str(args.get("action", "status")).strip() if isinstance(args, dict) else "status"
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
            last_frame, script_output, error, transition_log, step_snapshots, executed_events = _execute_script(
                script_source,
                env,
                script_label=script_label,
                agent_lib_source=agent_lib_source,
            )
            if last_frame is not None:
                frame = last_frame
            events.extend(executed_events)
            action_label = f"run_script({script_label})"

            scripts_dir = arc_dir / "script-history"
            scripts_dir.mkdir(parents=True, exist_ok=True)
            turn_hint = turn + 1
            winning_script_file = scripts_dir / f"turn_{turn_hint:03d}_script.py"
            winning_script_file.write_text(script_source)

            # Record level completion(s) at the exact step they occur, using action
            # history since the most recent reset. This avoids missing completions
            # when outer harness cycle timing and state file writes race.
            completions_path = _ensure_level_completions_file(cwd)
            max_recorded = _read_max_recorded_completion_level(completions_path)
            prev_levels = levels_before_script
            for idx, event in enumerate(executed_events):
                levels_now = event.get("levels_completed")
                if not isinstance(levels_now, int):
                    continue
                if levels_now <= prev_levels:
                    continue
                combined_events = events + executed_events[: idx + 1]
                actions = _actions_since_last_reset(combined_events)
                for completed_level in range(prev_levels + 1, levels_now + 1):
                    if completed_level <= max_recorded:
                        continue
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
                prev_levels = levels_now
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
            "step_diffs": step_diff_records,
            "aggregate_diff": aggregate_diff,
            "trace_file": trace_file_rel,
            "state_file": str((arc_dir / "state.json")),
            "transitions": transition_log,
            "script_stdout": script_output,
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
