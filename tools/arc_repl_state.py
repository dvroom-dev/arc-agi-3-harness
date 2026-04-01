from __future__ import annotations

import io
import json
import os
import re
import sys
import time
from pathlib import Path


LEVEL_COMPLETIONS_TEMPLATE = """# Level Completions

Canonical record of completed levels and the exact action sequence
for each completed level window.
"""

PLAY_LIB_TEMPLATE = """\"\"\"Persistent helper library for ARC scripts.

Define reusable functions here. `arc_repl exec` and simulator exec calls auto-load this file,
so inline scripts can call helpers directly without imports or boilerplate.
\"\"\"

# Example:
# def step_many(env, action, count):
#     for _ in range(count):
#         env.step(action)
"""


def _read_args() -> dict:
    raw = io.TextIOWrapper(
        buffer=getattr(__import__("sys"), "stdin").buffer,
        encoding="utf-8",
    ).read().strip()
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
        "schema_version": "arc_repl.v1",
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


def _level_completions_path(cwd: Path) -> Path:
    return _arc_dir(cwd) / "level_completions.md"


def _ensure_level_completions_file(cwd: Path) -> Path:
    path = _level_completions_path(cwd)
    if not path.exists():
        path.write_text(LEVEL_COMPLETIONS_TEMPLATE)
    return path


def _play_lib_path(cwd: Path) -> Path:
    return cwd / "play_lib.py"


def _ensure_play_lib_file(cwd: Path) -> Path:
    path = _play_lib_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(PLAY_LIB_TEMPLATE)
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


def _load_history(cwd: Path, game_id: str, make_id_candidates) -> dict:
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
        hist_candidates = set(make_id_candidates(history_game_id))
        req_candidates = set(make_id_candidates(game_id))
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
    path = _history_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp-{os.getpid()}-{time.time_ns()}")
    tmp.write_text(json.dumps(history, indent=2))
    tmp.replace(path)
