from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def extract_last_assistant_message(transcript: str) -> str:
    """Extract content of the last ```chat role=assistant``` block."""
    blocks: list[str] = []
    in_block = False
    current: list[str] = []
    for line in transcript.splitlines():
        if "```chat" in line and "role=assistant" in line:
            in_block = True
            current = []
        elif line.strip() == "```" and in_block:
            in_block = False
            blocks.append("\n".join(current))
        elif in_block:
            current.append(line)
    return blocks[-1].strip() if blocks else ""


def load_history_events(history_json: Path) -> list[dict[str, Any]]:
    """Load raw tool-engine events from history json."""
    if not history_json.exists():
        return []
    try:
        data = json.loads(history_json.read_text())
    except Exception as exc:
        raise RuntimeError(f"Failed to parse history JSON: {history_json}: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"Invalid history JSON shape in {history_json}: expected object")
    events = data.get("events")
    if not isinstance(events, list):
        raise RuntimeError(f"Invalid history JSON shape in {history_json}: expected events[]")
    out: list[dict[str, Any]] = []
    for e in events:
        if isinstance(e, dict):
            out.append(e)
    return out


def completion_action_windows_by_level(events: list[dict[str, Any]]) -> dict[int, list[str]]:
    """Return per-level action windows split by reset/completion boundaries."""
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


def append_level_completion_record(
    *,
    completions_file: Path,
    completed_level: int,
    actions: list[str],
    harness_turn: int,
    tool_turn: int,
    winning_script_relpath: str | None = None,
) -> None:
    """Append one level completion record to level_completions.md."""
    actions_preview = ", ".join(actions) if actions else "(none)"
    block = [
        "",
        f"## Level {completed_level} Completion",
        f"- timestamp_utc: {datetime.now(timezone.utc).isoformat()}",
        f"- harness_turn: {harness_turn}",
        f"- tool_turn: {tool_turn}",
        f"- winning_script: {winning_script_relpath or '(not available)'}",
        f"- action_count_in_level_window: {len(actions)}",
        f"- actions_in_level_window: {actions_preview}",
    ]
    with open(completions_file, "a") as f:
        f.write("\n".join(block) + "\n")


def read_max_recorded_completion_level(completions_file: Path) -> int:
    """Parse the highest `## Level N Completion` already recorded."""
    if not completions_file.exists():
        return 0
    pattern = re.compile(r"^## Level (\d+) Completion\s*$")
    max_level = 0
    for line in completions_file.read_text().splitlines():
        m = pattern.match(line.strip())
        if not m:
            continue
        try:
            level = int(m.group(1))
        except Exception:
            continue
        max_level = max(max_level, level)
    return max_level


def write_prompt_file(
    dest: Path,
    text: str,
    *,
    image_paths: list[str | Path] | None = None,
) -> None:
    """Write a super prompt-file (YAML) with text and optional image parts."""
    indented = "\n".join(f"      {line}" if line else "" for line in text.splitlines())
    lines = ["operation: append", "parts:", "  - literal: |", indented]
    for img in image_paths or []:
        lines.append(f"  - image: {img}")
    dest.write_text("\n".join(lines) + "\n")
