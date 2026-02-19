"""ARC-AGI-3 supervisor harness: drives the super CLI + game environment loop."""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
import threading
import traceback
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

try:
    from arcengine import GameAction
    from arcengine.enums import FrameDataRaw
except Exception:  # pragma: no cover - optional at harness import time
    GameAction = Any  # type: ignore[assignment]
    FrameDataRaw = Any  # type: ignore[assignment]

try:
    from game_state import (
        COLOR_NAMES,
        _connected_components_8,
        pixels_to_hex_grid,
        render_grid_to_image,
        write_game_state,
        write_machine_state,
        render_grid_to_terminal,
    )
except Exception as exc:  # pragma: no cover - fail fast
    raise RuntimeError(
        "Failed to import required game_state helpers. "
        "This harness now requires working game-state rendering/state helpers."
    ) from exc

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent
CTXS = PROJECT_ROOT / ".ctxs"
PROJECT_VENV_PYTHON = PROJECT_ROOT / ".venv" / "bin" / "python"

LEVEL_KNOWLEDGE_TEMPLATE = textwrap.dedent("""\
    # Level Knowledge (Current Level Only)

    Reset this file when advancing to the next level.

    ## Goal
    - [LOW] (unknown — determine win condition)

    ## Level Features

    List every visual element specific to this level with confidence-rated mechanics:
    - [HIGH/MED/LOW] feature_name @ (row,col): mechanic explanation
    (none identified yet)

    ## Experiments
    - (none)
""")

GAME_KNOWLEDGE_TEMPLATE = textwrap.dedent("""\
    # Game Knowledge (Persistent)

    Facts that should survive across levels.

    ## Features

    List every distinct visual/interactive element. For each, rate confidence:
    - [HIGH] feature_name: confirmed mechanic description
    - [MED] feature_name: likely mechanic, needs confirmation
    - [LOW] feature_name: speculative, needs testing

    (none identified yet)

    ## Confirmed Rules
    - (none)
""")

LEVEL_COMPLETIONS_TEMPLATE = textwrap.dedent("""\
    # Level Completions

    Canonical record of completed levels and the exact action sequence
    for each completed level window.
""")

AGENT_LIB_TEMPLATE = textwrap.dedent("""\
    \"\"\"Persistent helper library for ARC run_script turns.

    Put reusable game-agnostic helpers here.
    Every arc_action run_script call auto-loads this module before executing
    the turn script, so functions defined here are directly callable.
    \"\"\"

    # Example:
    # def step_many(env, action, count):
    #     for _ in range(count):
    #         env.step(action)
""")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_pixels(env) -> np.ndarray:
    """Extract the full pixel grid from the environment."""
    game = env._game
    return game.get_pixels(
        game.camera.x, game.camera.y,
        game.camera.width, game.camera.height,
    )


def format_cell_changes(before: np.ndarray, after: np.ndarray) -> str:
    """Format explicit grid changes as per-cell before->after transitions."""
    changed = np.argwhere(before != after)
    if changed.size == 0:
        return "(no changes)"
    lines = [
        f"changed_pixels={len(changed)}",
        "format: (row,col): before->after",
    ]
    for row, col in changed:
        lines.append(
            f"({int(row)},{int(col)}): {int(before[row, col]):X}->{int(after[row, col]):X}"
        )
    return "\n".join(lines)


def format_change_records(changes: list[dict]) -> str:
    """Format tool diff records (`changes`) as explicit cell transitions."""
    if not changes:
        return "(no changes)"
    lines = [
        f"changed_pixels={len(changes)}",
        "format: (row,col): before->after",
    ]
    for ch in changes:
        try:
            row = int(ch.get("row"))
            col = int(ch.get("col"))
            before = str(ch.get("before", "?"))
            after = str(ch.get("after", "?"))
        except Exception:
            continue
        lines.append(f"({row},{col}): {before}->{after}")
    return "\n".join(lines)


def find_click_targets(pixels: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Find contiguous color regions and return their centroids as click targets.

    Returns list of (x, y, color_id, size) sorted by size descending.
    x/y are centroid coordinates (col, row) for ACTION6 data format.
    Skips color 0 (background).
    """
    targets: list[tuple[int, int, int, int]] = []
    seen_pixels: set[tuple[int, int]] = set()

    for color_id in range(1, 16):
        mask = pixels == color_id
        if not np.any(mask):
            continue
        components = _connected_components_8(mask)
        for component in components:
            size = len(component)
            rows = [p[0] for p in component]
            cols = [p[1] for p in component]
            cy = int(round(sum(rows) / size))  # row = y
            cx = int(round(sum(cols) / size))  # col = x
            # Deduplicate targets landing on the same pixel
            if (cx, cy) not in seen_pixels:
                seen_pixels.add((cx, cy))
                targets.append((cx, cy, color_id, size))

    targets.sort(key=lambda t: t[3], reverse=True)
    return targets


def _parse_color_id(value: Any) -> int | None:
    """Parse a color token from tool diffs into an integer color id."""
    if value is None:
        return None
    try:
        if isinstance(value, int):
            return value
        s = str(value).strip()
        if not s:
            return None
        return int(s, 16)
    except Exception:
        return None


def _collect_diff_palette(result: dict | None) -> set[int]:
    """Collect color ids appearing in a tool diff payload."""
    palette: set[int] = set()
    if not result:
        return palette
    step_diffs = result.get("step_diffs")
    if not isinstance(step_diffs, list):
        return palette
    for step in step_diffs:
        if not isinstance(step, dict):
            continue
        changes = step.get("changes")
        if not isinstance(changes, list):
            continue
        for ch in changes:
            if not isinstance(ch, dict):
                continue
            before = _parse_color_id(ch.get("before"))
            after = _parse_color_id(ch.get("after"))
            if before is not None:
                palette.add(before)
            if after is not None:
                palette.add(after)
    return palette


def summarize_static_features(
    pixels: np.ndarray,
    *,
    excluded_colors: set[int],
    max_components: int = 24,
) -> list[str]:
    """Summarize connected components in the reset frame for probe targeting."""
    entries: list[tuple[int, int, int, int, int, int, int, str]] = []
    for color_id in range(16):
        if color_id in excluded_colors:
            continue
        mask = pixels == color_id
        if not np.any(mask):
            continue
        components = _connected_components_8(mask)
        for component in components:
            if not component:
                continue
            size = len(component)
            rows = [int(p[0]) for p in component]
            cols = [int(p[1]) for p in component]
            r0, r1 = min(rows), max(rows)
            c0, c1 = min(cols), max(cols)
            h = r1 - r0 + 1
            w = c1 - c0 + 1
            cy = int(round(sum(rows) / size))
            cx = int(round(sum(cols) / size))
            color_name = COLOR_NAMES.get(color_id, f"color-{color_id:X}")
            entries.append((size, h * w, color_id, cx, cy, r0, c0, color_name))

    # Prefer larger contiguous features. Tie-break by tighter bbox area.
    entries.sort(key=lambda t: (-t[0], t[1], t[2], t[4], t[3]))
    lines: list[str] = []
    for size, _, color_id, cx, cy, r0, c0, color_name in entries[:max_components]:
        lines.append(
            f"{color_name} (id={color_id:X}) size={size} origin=({r0},{c0}) center=({cy},{cx})"
        )
    return lines


def explore_inputs(env, frame: FrameDataRaw, pixels: np.ndarray) -> str:
    """Try every available action (with reset between each), capture diffs.

    For ACTION6, clicks on the centroid of each contiguous color region.
    Returns a formatted summary for the initial prompt.
    """
    base_pixels = pixels.copy()
    action_map = {a.value: a for a in GameAction}

    results_with_diff: list[str] = []
    no_effect: list[str] = []

    for action_id in sorted(frame.available_actions):
        if action_id == 0:  # RESET — skip
            continue
        action = action_map.get(action_id)
        if action is None:
            continue
        action_name = action.name

        if action_id == 6:  # ACTION6 — click on each color region
            targets = find_click_targets(base_pixels)
            for x, y, color_id, size in targets:
                color_name = COLOR_NAMES.get(color_id, f"color-{color_id}")
                label = f"{action_name} click ({x},{y}) on {color_name} (size={size})"
                try:
                    env.step(action, data={"x": x, "y": y})
                    new_pixels = get_pixels(env)
                    if np.any(base_pixels != new_pixels):
                        results_with_diff.append(
                            f"### {label}\n```\n{format_cell_changes(base_pixels, new_pixels)}\n```"
                        )
                    else:
                        no_effect.append(label)
                except Exception as e:
                    no_effect.append(f"{label} (error: {e})")
                env.reset()
        else:
            label = action_name
            try:
                env.step(action)
                new_pixels = get_pixels(env)
                if np.any(base_pixels != new_pixels):
                    results_with_diff.append(
                        f"### {label}\n```\n{format_cell_changes(base_pixels, new_pixels)}\n```"
                    )
                else:
                    no_effect.append(label)
            except Exception as e:
                no_effect.append(f"{label} (error: {e})")
            env.reset()

    parts = ["## Input Exploration Results\n"]
    parts.append("The following actions were tested from the initial state "
                 "(with reset between each):\n")
    parts.extend(results_with_diff)

    if no_effect:
        parts.append(f"\n### No effect\n{', '.join(no_effect)}")

    return "\n".join(parts)


def _drain_stderr(proc, prefix="[super] "):
    """Read proc.stderr line-by-line and print to our stderr. Runs in a thread."""
    assert proc.stderr is not None
    for line in proc.stderr:
        print(f"{prefix}{line}", end="", file=sys.stderr, flush=True)


def run_super(args: list[str], *, stream: bool = False,
              output_path: Path | None = None,
              cwd: Path | None = None,
              env: dict[str, str] | None = None) -> str:
    """Run a super CLI command and return the last assistant message.

    When stream=False (default):
        Uses --output to write transcript to output_path.
        Captures stdout (last assistant message) and stderr (status lines).

    When stream=True:
        Drops --output from args, lets super stream full transcript to stdout.
        Tees stdout to stderr for live display while capturing it.
        Writes captured transcript to output_path and extracts last assistant msg.
    """
    cmd = ["super"] + args

    if stream:
        # Strip --output <path> from cmd — we handle it ourselves
        filtered_cmd: list[str] = []
        i = 0
        while i < len(cmd):
            if cmd[i] == "--output" and i + 1 < len(cmd):
                if output_path is None:
                    output_path = Path(cmd[i + 1])
                i += 2  # skip --output and its value
            else:
                filtered_cmd.append(cmd[i])
                i += 1
        cmd = filtered_cmd

    print(f"[harness] running: {' '.join(cmd)}", file=sys.stderr, flush=True)

    run_cwd = str(cwd) if cwd else str(PROJECT_ROOT)
    if stream:
        return _run_super_streaming(cmd, output_path, cwd=run_cwd, env=env)
    else:
        return _run_super_batch(cmd, cwd=run_cwd, env=env)


def _run_super_batch(cmd: list[str], *, cwd: str = "", env: dict[str, str] | None = None) -> str:
    """Batch mode: capture stdout+stderr, print stderr after completion."""
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=cwd or str(PROJECT_ROOT),
        env=env,
    )
    if result.stderr.strip():
        for line in result.stderr.strip().splitlines():
            print(f"[super] {line}", file=sys.stderr, flush=True)
    if result.returncode != 0:
        raise RuntimeError(f"super exited with code {result.returncode}")
    return result.stdout.strip()


def _fix_streamed_transcript(text: str) -> str:
    """Normalize streamed transcript text without mutating markdown structure.

    NOTE:
    We intentionally avoid regex-based fence rewriting here. Rewriting backtick
    sequences can corrupt valid chat fences when assistant content contains
    literal markdown fences.
    """
    return text


def _run_super_streaming(cmd: list[str], output_path: Path | None,
                         *, cwd: str = "",
                         env: dict[str, str] | None = None) -> str:
    """Streaming mode: tee stdout to stderr for display, capture transcript."""
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=cwd or str(PROJECT_ROOT),
        env=env,
    )

    # Drain stderr in a background thread so it doesn't block
    stderr_thread = threading.Thread(target=_drain_stderr, args=(proc,), daemon=True)
    stderr_thread.start()

    # Read stdout in chunks, tee to stderr, accumulate
    chunks: list[str] = []
    assert proc.stdout is not None
    while True:
        chunk = proc.stdout.read(256)
        if not chunk:
            break
        chunks.append(chunk)
        sys.stderr.write(chunk)
        sys.stderr.flush()

    proc.wait()
    stderr_thread.join(timeout=2)

    transcript = _fix_streamed_transcript("".join(chunks))

    if proc.returncode != 0:
        raise RuntimeError(f"super exited with code {proc.returncode}")

    # Write transcript to session file
    if output_path is not None:
        output_path.write_text(transcript)

    # Extract last assistant message from transcript
    return extract_last_assistant_message(transcript)


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


def extract_json(text: str) -> str | None:
    """Try to extract JSON from assistant output that may be wrapped in markdown.

    Handles: bare JSON, ```json fenced blocks, JSON with surrounding prose.
    """
    text = text.strip()
    if not text:
        return None

    # Try bare JSON first
    if text.startswith("{"):
        depth = 0
        for i, ch in enumerate(text):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[: i + 1]

    # Try fenced code block: ```json ... ``` or ``` ... ```
    fence_match = re.search(r"```(?:json)?\s*\n(\{.*?\})\s*\n```", text, re.DOTALL)
    if fence_match:
        return fence_match.group(1).strip()

    # Try to find any JSON object in the text
    brace_start = text.find("{")
    if brace_start != -1:
        depth = 0
        for i in range(brace_start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    return text[brace_start : i + 1]

    return None


def execute_script(
    script_path: Path,
    env,
) -> tuple[FrameDataRaw | None, str, str, list[str], list[tuple[str, np.ndarray]]]:
    """Execute an agent-written script with env in its namespace.

    Returns (last_frame, stdout_capture, error_string, transition_log, step_snapshots).
    step_snapshots is a list of (description, pixels) captured after each env.step().
    """
    if not script_path.exists():
        return None, "", f"Script not found: {script_path}", [], []

    code = script_path.read_text()

    # Collect per-step transitions and pixel snapshots
    transition_log: list[str] = []
    step_snapshots: list[tuple[str, np.ndarray]] = []
    last_frame: FrameDataRaw | None = None

    # Wrap env.step to log transitions and capture snapshots
    original_step = env.step
    terminal_halt = False

    class _TerminalStateReached(Exception):
        """Internal sentinel used to stop script execution after terminal state."""
        pass

    def logging_step(action, data=None, reasoning=None):
        nonlocal last_frame, terminal_halt
        if terminal_halt:
            raise _TerminalStateReached()
        frame = original_step(action, data=data, reasoning=reasoning)
        if frame is not None:
            last_frame = frame
            action_name = action.name if hasattr(action, "name") else str(action)
            data_str = f" data={data}" if data else ""
            description = (
                f"{action_name}{data_str} -> state={frame.state.value} "
                f"levels={frame.levels_completed}/{frame.win_levels}"
            )
            transition_log.append(description)
            try:
                pixels = get_pixels(env)
                step_snapshots.append((description, pixels))
            except Exception:
                pass  # pixel capture failure shouldn't crash the script
            if frame.state.value in {"WIN", "GAME_OVER"}:
                terminal_halt = True
                raise _TerminalStateReached()
        return frame

    env.step = logging_step

    # Block env.reset — resets are only allowed via the reset_level action
    original_reset = env.reset

    def blocked_reset():
        raise RuntimeError(
            "env.reset() cannot be called from scripts. "
            'Return {"action": "reset_level"} to reset the level.'
        )

    env.reset = blocked_reset

    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()
    error = ""

    script_globals = {
        "__builtins__": __builtins__,
        "env": env,
        "GameAction": GameAction,
        "np": np,
    }

    try:
        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
            exec(compile(code, str(script_path), "exec"), script_globals)
    except _TerminalStateReached:
        # Expected early stop after reaching terminal state.
        pass
    except BaseException:
        # Catch BaseException to handle SystemExit, KeyboardInterrupt, etc.
        # from agent scripts without crashing the harness.
        error = traceback.format_exc()
    finally:
        # Restore original methods
        env.step = original_step
        env.reset = original_reset

    return last_frame, stdout_capture.getvalue(), error, transition_log, step_snapshots


def archive_script(script_path: Path, session_dir: Path, turn: int) -> None:
    """Copy an executed script to the session scripts archive."""
    scripts_dir = session_dir / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    dest = scripts_dir / f"turn_{turn:03d}_{script_path.name}"
    shutil.copy2(script_path, dest)


def archive_script_in_run_dir(script_path: Path, run_dir: Path, turn: int) -> Path:
    """Copy an executed script to a run-local script history directory."""
    scripts_dir = run_dir / ".ai-supervisor" / "arc" / "script-history"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    dest = scripts_dir / f"turn_{turn:03d}_{script_path.name}"
    shutil.copy2(script_path, dest)
    return dest


def log_action(session_dir: Path, turn: int, entry: dict) -> None:
    """Append a line to actions.jsonl."""
    log_file = session_dir / "actions.jsonl"
    entry["turn"] = turn
    entry["timestamp"] = datetime.now(timezone.utc).isoformat()
    with open(log_file, "a") as f:
        f.write(json.dumps(entry) + "\n")


def load_history_events(history_json: Path) -> list[dict[str, Any]]:
    """Load raw tool-engine events from history json."""
    if not history_json.exists():
        return []
    try:
        data = json.loads(history_json.read_text())
    except Exception:
        return []
    if not isinstance(data, dict):
        return []
    events = data.get("events")
    if not isinstance(events, list):
        return []
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


def write_turn_trace(
    *,
    trace_dir: Path,
    turn: int,
    script_path: Path,
    pre_turn_pixels: np.ndarray | None,
    step_snapshots: list[tuple[str, np.ndarray]],
    final_pixels: np.ndarray,
    script_output: str = "",
    error: str = "",
) -> Path:
    """Write a verbose per-turn execution trace for the executed script."""
    trace_dir.mkdir(parents=True, exist_ok=True)
    trace_path = trace_dir / f"turn_{turn:03d}_trace.md"

    parts: list[str] = [
        f"# Turn {turn:03d} Trace",
        "",
        f"- script: `{script_path.name}`",
        f"- steps: {len(step_snapshots)}",
        f"- script_error: {bool(error)}",
    ]

    if script_output:
        parts.extend(
            [
                "",
                "## Script Output",
                "```",
                script_output,
                "```",
            ]
        )

    if error:
        parts.extend(
            [
                "",
                "## Script Error",
                "```",
                error,
                "```",
            ]
        )

    if pre_turn_pixels is not None:
        parts.extend(
            [
                "",
                "## Initial Grid (Full 64x64 Hex)",
                "```",
                pixels_to_hex_grid(pre_turn_pixels),
                "```",
            ]
        )

    if step_snapshots and pre_turn_pixels is not None:
        parts.append("")
        parts.append("## Per-Step Actions And Diffs")
        for i, (desc, snap_pixels) in enumerate(step_snapshots):
            prev = pre_turn_pixels if i == 0 else step_snapshots[i - 1][1]
            parts.extend(
                [
                    "",
                    f"### Step {i + 1}: {desc}",
                    "",
                    "Cell diff:",
                    "```",
                    format_cell_changes(prev, snap_pixels),
                    "```",
                ]
            )

    if pre_turn_pixels is not None:
        parts.extend(
            [
                "",
                "## Aggregate Diff (Initial -> Final)",
                "```",
                format_cell_changes(pre_turn_pixels, final_pixels),
                "```",
            ]
        )

    parts.extend(
        [
            "",
            "## Final Grid (Full 64x64 Hex)",
            "```",
            pixels_to_hex_grid(final_pixels),
            "```",
            "",
        ]
    )

    trace_path.write_text("\n".join(parts))
    return trace_path


def build_resume_prompt(
    *,
    action_type: str,
    frame: FrameDataRaw,
    game_id: str = "",
    step_snapshots: list[tuple[str, np.ndarray]] | None = None,
    pre_turn_pixels: np.ndarray | None = None,
    script_output: str = "",
    error: str = "",
    reset_notice: str = "",
    telemetry: dict | None = None,
) -> str:
    """Build a rich prompt for super resume with action results, diffs, and state.

    For run_script actions with step data, includes:
    - Per-step explicit cell diffs (before->after transitions)
    - Aggregate explicit cell diff (initial->final)
    - Full current hex grid
    """
    parts: list[str] = []

    # What happened
    if action_type == "run_script":
        if error:
            parts.append(f"Script execution FAILED.\n\nError:\n```\n{error}\n```")
        else:
            parts.append("Script executed successfully.")
        if script_output:
            parts.append(f"\nScript output:\n```\n{script_output}\n```")
        if step_snapshots and pre_turn_pixels is not None:
            parts.append(f"\nActions taken ({len(step_snapshots)} steps):")
            no_change_steps = 0
            for i, (desc, snap_pixels) in enumerate(step_snapshots):
                prev = pre_turn_pixels if i == 0 else step_snapshots[i - 1][1]
                if not np.any(prev != snap_pixels):
                    no_change_steps += 1
                parts.append(f"\nStep {i + 1}: {desc}")
                parts.append(f"```\n{format_cell_changes(prev, snap_pixels)}\n```")

            # Aggregate diff
            parts.append(f"\nAggregate diff ({len(step_snapshots)} steps):")
            parts.append(f"```\n{format_cell_changes(pre_turn_pixels, step_snapshots[-1][1])}\n```")

            # Full current grid
            parts.append("\nCurrent grid:")
            parts.append(f"```\n{pixels_to_hex_grid(step_snapshots[-1][1])}\n```")

            # Generic action-efficiency signals to reduce repeated ineffective probing.
            changed_steps = len(step_snapshots) - no_change_steps
            parts.append(
                f"\nAction efficiency: {changed_steps}/{len(step_snapshots)} steps changed state; "
                f"{no_change_steps}/{len(step_snapshots)} had no observable change."
            )
            if no_change_steps > 0:
                parts.append(
                    "If many steps had no effect, prefer a shorter, targeted script that changes one "
                    "condition at a time instead of repeating similar moves."
                )
        elif not error:
            parts.append(
                "\nWARNING: Script executed 0 steps. Your script must call "
                "env.step() at the TOP LEVEL — not inside a function definition. "
                "Scripts are run via exec(); only top-level code executes."
            )
    elif action_type == "reset_level":
        parts.append("Level has been reset.")
    elif action_type == "next_level":
        parts.append("Level knowledge reset. Game knowledge updated. New level started.")

    # Current state metadata
    actions_str = ", ".join(str(a) for a in frame.available_actions)
    level = frame.levels_completed + 1
    parts.append(
        f"\nCurrent state: {frame.state.value} | "
        f"game: {game_id} | level: {level}/{frame.win_levels} | "
        f"available_actions: [{actions_str}]"
    )
    if telemetry:
        parts.append(
            "Runtime telemetry: "
            f"steps_since_last_reset={telemetry.get('steps_since_last_reset', 0)}, "
            f"reset_epoch={telemetry.get('reset_epoch', 0)}, "
            f"manual_resets={telemetry.get('manual_resets', 0)}, "
            f"auto_game_over_resets={telemetry.get('auto_game_over_resets', 0)}, "
            f"game_over_events={telemetry.get('game_over_events', 0)}, "
            f"last_reset_reason={telemetry.get('last_reset_reason', 'none')}, "
            f"full_reset_signal={telemetry.get('full_reset_signal', False)}"
        )

    if reset_notice.strip():
        parts.append(f"\n{reset_notice.strip()}")
    parts.append("\nGrid files updated. Return your next action as JSON.")

    return "\n".join(parts)


def write_prompt_file(
    dest: Path,
    text: str,
    *,
    image_paths: list[str | Path] | None = None,
) -> None:
    """Write a super prompt-file (YAML) with text and optional image parts.

    Format:
        operation: append
        parts:
          - literal: |
              <text>
          - image: <path>
    """
    # Escape the text for YAML block scalar: indent every line by 6 spaces
    indented = "\n".join(f"      {line}" if line else "" for line in text.splitlines())
    lines = ["operation: append", "parts:", "  - literal: |", indented]
    for img in image_paths or []:
        lines.append(f"  - image: {img}")
    dest.write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ARC-AGI-3 supervisor harness")
    parser.add_argument("--game-id", default="ls20", help="Game ID to load")
    parser.add_argument(
        "--max-turns", type=int, default=50,
        help="Maximum harness turns before stopping",
    )
    parser.add_argument(
        "--operation-mode", default="NORMAL",
        choices=["NORMAL", "ONLINE", "OFFLINE"],
        help="Arcade operation mode",
    )
    parser.add_argument(
        "--session-name", default=None,
        help="Session directory name (default: timestamp)",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Print colored game grid to terminal after each state change",
    )
    parser.add_argument(
        "--open-scorecard", action="store_true",
        help="Open a new scorecard at start and close at end (requires ONLINE mode)",
    )
    parser.add_argument(
        "--scorecard-id", default=None,
        help="Use an existing scorecard ID",
    )
    parser.add_argument(
        "--provider", default=None,
        choices=["claude", "codex", "mock"],
        help="LLM provider for super CLI (default: from super.yaml runtime_defaults)",
    )
    parser.add_argument(
        "--no-supervisor", action="store_true",
        help="Disable supervision (pass --no-supervisor to super CLI)",
    )
    parser.add_argument(
        "--no-explore", action="store_true",
        help="Skip automated input exploration at game start",
    )
    parser.add_argument(
        "--max-game-over-resets", type=int, default=8,
        help="Maximum automatic level resets after GAME_OVER before stopping",
    )
    return parser.parse_args()


def setup_run_dir(run_dir: Path, agent_dir: Path, supervisor_dir: Path, log) -> None:
    """Set up an isolated run directory with split agent/supervisor dirs."""
    run_dir.mkdir(parents=True, exist_ok=True)
    agent_dir.mkdir(parents=True, exist_ok=True)
    supervisor_dir.mkdir(parents=True, exist_ok=True)

    # Do not copy environment source into run workspace.
    # arc_action loads environments from shared project-level environment_files.

    # Seed supervisor-side knowledge files. Supervisor can reference these via
    # supervisor_file scope without exposing them to the agent filesystem.
    supervisor_arc = supervisor_dir / "arc"
    supervisor_arc.mkdir(parents=True, exist_ok=True)

    gk = supervisor_arc / "game-knowledge.md"
    if not gk.exists():
        gk.write_text(GAME_KNOWLEDGE_TEMPLATE)

    lk = supervisor_arc / "level-knowledge.md"
    if not lk.exists():
        lk.write_text(LEVEL_KNOWLEDGE_TEMPLATE)

    lc = supervisor_arc / "level_completions.md"
    if not lc.exists():
        lc.write_text(LEVEL_COMPLETIONS_TEMPLATE)

    agent_lib = agent_dir / "agent_lib.py"
    if not agent_lib.exists():
        agent_lib.write_text(AGENT_LIB_TEMPLATE)


def setup_run_config_dir(run_config_dir: Path) -> tuple[Path, Path]:
    """Create run-local config/bin/tools so agent shell stays in run workspace."""
    run_config_dir.mkdir(parents=True, exist_ok=True)
    tools_dir = run_config_dir / "tools"
    bin_dir = run_config_dir / "bin"
    tools_dir.mkdir(parents=True, exist_ok=True)
    bin_dir.mkdir(parents=True, exist_ok=True)

    for filename in ("arc_action.py", "arc_action_cli.py", "arc_get_state.py"):
        src = PROJECT_ROOT / "tools" / filename
        dst = tools_dir / filename
        shutil.copyfile(src, dst)

    py = str(PROJECT_VENV_PYTHON)
    arc_action_wrapper = f"""#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
CONFIG_DIR="$(cd "${{SCRIPT_DIR}}/.." && pwd)"
exec "{py}" "${{CONFIG_DIR}}/tools/arc_action_cli.py" "$@"
"""
    arc_get_state_wrapper = f"""#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
CONFIG_DIR="$(cd "${{SCRIPT_DIR}}/.." && pwd)"
exec "{py}" "${{CONFIG_DIR}}/tools/arc_get_state.py" "$@"
"""
    arc_action_path = bin_dir / "arc_action"
    arc_action_path.write_text(arc_action_wrapper)
    arc_action_path.chmod(0o755)
    arc_get_state_path = bin_dir / "arc_get_state"
    arc_get_state_path.write_text(arc_get_state_wrapper)
    arc_get_state_path.chmod(0o755)
    return bin_dir, tools_dir


def assert_no_game_files_in_agent_dir(agent_dir: Path) -> None:
    """Fail fast if game/environment source appears in the agent filesystem."""
    forbidden: list[Path] = []
    for path in agent_dir.rglob("*"):
        rel = path.relative_to(agent_dir)
        if "environment_files" in rel.parts:
            forbidden.append(rel)
            continue
        if path.name in {"game_state.py", "ls20.py"}:
            forbidden.append(rel)
            continue
        if path.suffix == ".zip" and "environment" in path.name.lower():
            forbidden.append(rel)
            continue
    if forbidden:
        preview = ", ".join(str(p) for p in sorted(set(forbidden))[:8])
        raise RuntimeError(
            "agent filesystem contains forbidden game/environment artifacts: "
            f"{preview}"
        )


def main() -> None:
    args = parse_args()

    # Session and run directories
    session_name = args.session_name or datetime.now().strftime("%Y%m%d_%H%M%S")
    session_dir = CTXS / session_name
    session_dir.mkdir(parents=True, exist_ok=True)
    session_file = session_dir / "session.md"
    tmp_session = session_dir / "session.next.md"

    # Per-run isolation: each run gets its own working directory
    run_dir = PROJECT_ROOT / "runs" / session_name
    log = lambda msg: print(msg, file=sys.stderr, flush=True)
    agent_dir = run_dir / "agent"
    supervisor_dir = run_dir / "supervisor"
    run_config_dir = run_dir / "config"
    setup_run_dir(run_dir, agent_dir, supervisor_dir, log)
    run_bin_dir, run_tools_dir = setup_run_config_dir(run_config_dir)
    assert_no_game_files_in_agent_dir(agent_dir)
    run_super_config = run_dir / "super.yaml"
    run_super_config.write_text((PROJECT_ROOT / "super.yaml").read_text())
    super_config = run_super_config
    if not PROJECT_VENV_PYTHON.exists():
        log(f"[harness] missing python runtime: {PROJECT_VENV_PYTHON}")
        log("[harness] run `uv sync` in project root and retry")
        sys.exit(1)
    run_arc_action_tool = run_tools_dir / "arc_action.py"
    if not run_arc_action_tool.exists():
        log(f"[harness] missing tool script: {run_arc_action_tool}")
        sys.exit(1)

    arc_state_dir = supervisor_dir / "arc"
    # Keep environment source/cache outside BOTH agent and supervisor filesystems.
    # This prevents benchmark solution leakage through either role's file access.
    arc_env_dir = Path("/tmp/arc-agi-env-cache") / session_name
    arc_env_dir.mkdir(parents=True, exist_ok=True)
    state_json = arc_state_dir / "state.json"
    history_json = arc_state_dir / "tool-engine-history.json"
    completions_md = arc_state_dir / "level_completions.md"
    auto_explore_once_marker = arc_state_dir / "auto_explore_once.done"
    cycle_limit = 1

    def _provider_args() -> list[str]:
        if args.provider:
            return ["--provider", args.provider]
        return []

    def _supervisor_args() -> list[str]:
        if args.no_supervisor:
            return ["--no-supervisor"]
        return []

    def load_state() -> dict | None:
        if not state_json.exists():
            return None
        try:
            data = json.loads(state_json.read_text())
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def load_engine_turn() -> int:
        if not history_json.exists():
            return 0
        try:
            data = json.loads(history_json.read_text())
            turn = data.get("turn", 0)
            return int(turn) if isinstance(turn, int) else 0
        except Exception:
            return 0

    def format_state_summary(state: dict | None) -> str:
        if not state:
            return "State unavailable."
        telemetry = state.get("telemetry") if isinstance(state.get("telemetry"), dict) else {}
        steps_since_reset = telemetry.get("steps_since_last_reset", "n/a")
        action_input = state.get("action_input_name", "?")
        full_reset = state.get("full_reset", False)
        return (
            f"state={state.get('state','?')} level={state.get('current_level','?')} "
            f"levels={state.get('levels_completed','?')}/{state.get('win_levels','?')} "
            f"last_action={state.get('last_action','?')} "
            f"action_input={action_input} full_reset={full_reset} "
            f"tool_turn={load_engine_turn()} steps_since_last_reset={steps_since_reset}"
        )

    active_game_id = str(args.game_id).strip()

    def run_arc_action(payload: dict) -> tuple[dict | None, str, int]:
        nonlocal active_game_id
        request = dict(payload)
        requested_game_id = str(request.get("game_id", "")).strip()
        # Keep all harness-side calls on one canonical game_id lineage.
        # After the first status call, arc_action returns a resolved id
        # (e.g. ls20-<hash>). Reusing that id avoids replay-history forks.
        if requested_game_id:
            if (
                active_game_id
                and requested_game_id == str(args.game_id).strip()
                and active_game_id != requested_game_id
            ):
                request["game_id"] = active_game_id
        elif active_game_id:
            request["game_id"] = active_game_id
        cmd = [
            str(PROJECT_VENV_PYTHON),
            str(run_arc_action_tool),
        ]
        child_env = dict(os.environ)
        child_env["ARC_OPERATION_MODE"] = str(args.operation_mode).strip().upper()
        child_env.setdefault("ARC_ENVIRONMENTS_DIR", str(arc_env_dir))
        child_env["ARC_STATE_DIR"] = str(arc_state_dir)
        proc = subprocess.run(
            cmd,
            input=json.dumps(request),
            text=True,
            capture_output=True,
            cwd=str(agent_dir),
            env=child_env,
        )
        if proc.stderr.strip():
            for line in proc.stderr.strip().splitlines():
                log(f"[arc_action] {line}")
        stdout = proc.stdout.strip()
        parsed: dict | None = None
        json_blob = extract_json(stdout) if stdout else None
        if json_blob:
            try:
                maybe = json.loads(json_blob)
                if isinstance(maybe, dict):
                    parsed = maybe
                    resolved_game_id = str(parsed.get("game_id", "")).strip()
                    if resolved_game_id:
                        active_game_id = resolved_game_id
            except Exception:
                pass
        return parsed, stdout, proc.returncode

    def load_current_pixels() -> np.ndarray | None:
        grid_path = arc_state_dir / "current_grid.npy"
        if not grid_path.exists():
            return None
        try:
            return np.load(grid_path)
        except Exception:
            return None

    def summarize_tool_diff(result: dict | None) -> tuple[int, str]:
        if not result:
            return 0, "(no result)"
        step_diffs = result.get("step_diffs")
        if isinstance(step_diffs, list) and step_diffs:
            first = step_diffs[0] if isinstance(step_diffs[0], dict) else {}
            changes = first.get("changes")
            if isinstance(changes, list):
                changed = first.get("changed_pixels")
                try:
                    changed_pixels = int(changed) if changed is not None else len(changes)
                except Exception:
                    changed_pixels = len(changes)
                return changed_pixels, format_change_records(changes)
        agg = result.get("aggregate_diff")
        if isinstance(agg, dict):
            changes = agg.get("changes")
            if isinstance(changes, list):
                changed = agg.get("changed_pixels")
                try:
                    changed_pixels = int(changed) if changed is not None else len(changes)
                except Exception:
                    changed_pixels = len(changes)
                return changed_pixels, format_change_records(changes)
        return 0, "(no changes)"

    def run_input_exploration_from_reset() -> str:
        """Auto-probe every available input from a reset baseline.

        Runs each action from level-start state, captures full diffs, and
        resets between attempts. For ACTION6, clicks every contiguous non-zero
        color component centroid.
        """
        # Force reset baseline before probing a level.
        run_arc_action({"action": "reset_level", "game_id": args.game_id})
        status_result, status_stdout, status_rc = run_arc_action(
            {"action": "status", "game_id": args.game_id}
        )
        if status_rc != 0 or not status_result:
            detail = status_stdout.strip() if status_stdout.strip() else "status unavailable"
            return (
                "## Input Exploration Results (auto)\n\n"
                "Auto exploration failed before probes.\n\n"
                f"Detail: {detail}\n"
            )

        available = status_result.get("available_actions", [])
        action_ids: list[int] = []
        if isinstance(available, list):
            for a in available:
                try:
                    action_ids.append(int(a))
                except Exception:
                    continue
        action_ids = sorted(set(a for a in action_ids if a != 0))

        base_pixels = load_current_pixels()
        motion_palette: set[int] = set()
        diff_sections: list[str] = []
        no_effect: list[str] = []

        for action_id in action_ids:
            if action_id == 6 and base_pixels is not None:
                targets = find_click_targets(base_pixels)
                for x, y, color_id, size in targets:
                    color_name = COLOR_NAMES.get(color_id, f"color-{color_id}")
                    label = (
                        f"ACTION6 click ({x},{y}) on {color_name} "
                        f"(id={color_id:X}, size={size})"
                    )
                    script = f"env.step(6, data={{'x': {x}, 'y': {y}}})"
                    result, stdout, rc = run_arc_action(
                        {"action": "run_script", "game_id": args.game_id, "script": script}
                    )
                    if rc == 0 and result:
                        motion_palette.update(_collect_diff_palette(result))
                        changed_pixels, diff_text = summarize_tool_diff(result)
                        if changed_pixels > 0:
                            diff_sections.append(f"### {label}\n```\n{diff_text}\n```")
                        else:
                            no_effect.append(label)
                    else:
                        error_text = stdout.strip() if stdout.strip() else "run_script failed"
                        no_effect.append(f"{label} (error: {error_text})")
                    run_arc_action({"action": "reset_level", "game_id": args.game_id})
                continue

            label = f"ACTION{action_id}"
            script = f"env.step({action_id})"
            result, stdout, rc = run_arc_action(
                {"action": "run_script", "game_id": args.game_id, "script": script}
            )
            if rc == 0 and result:
                motion_palette.update(_collect_diff_palette(result))
                changed_pixels, diff_text = summarize_tool_diff(result)
                if changed_pixels > 0:
                    diff_sections.append(f"### {label}\n```\n{diff_text}\n```")
                else:
                    no_effect.append(label)
            else:
                error_text = stdout.strip() if stdout.strip() else "run_script failed"
                no_effect.append(f"{label} (error: {error_text})")
            run_arc_action({"action": "reset_level", "game_id": args.game_id})

        parts = [
            "## Input Exploration Results (auto)",
            "",
            "Harness auto-tested each available input from reset baseline and reset between attempts.",
            "Interpretation note: these are control-baseline diffs; do not treat them as proof of win-condition mechanics.",
        ]
        if base_pixels is not None:
            values, counts = np.unique(base_pixels, return_counts=True)
            background_color = int(values[int(np.argmax(counts))]) if len(values) else 0
            excluded = set(motion_palette)
            excluded.add(background_color)
            feature_lines = summarize_static_features(
                base_pixels,
                excluded_colors=excluded,
            )
            parts.append("")
            parts.append("### Static feature inventory (reset frame)")
            parts.append(
                "Use this inventory for direct feature-contact probes; avoid treating actor trail colors as objective features."
            )
            parts.append(
                "Excluded colors (background + motion palette): "
                + ", ".join(f"{c:X}" for c in sorted(excluded))
            )
            if feature_lines:
                for line in feature_lines:
                    parts.append(f"- {line}")
            else:
                parts.append("- (no static components found after exclusions)")
        if diff_sections:
            parts.append("")
            parts.extend(diff_sections)
        if no_effect:
            parts.append("")
            parts.append("### No effect / failed probes")
            parts.append(", ".join(no_effect))
        return "\n".join(parts)

    prompt_file_counter = 0
    last_prompted_image_level: int | None = None
    level_start_images_dir = supervisor_dir / "arc" / "level-start-images"
    level_start_images_dir.mkdir(parents=True, exist_ok=True)
    current_level_start_image = supervisor_dir / "arc" / "current-level-start.png"

    def _prompt_args(
        prompt_text: str,
        *,
        prompt_kind: str,
        image_paths: list[Path] | None = None,
    ) -> list[str]:
        nonlocal prompt_file_counter
        if image_paths:
            prompt_file_counter += 1
            prompt_file = session_dir / f"{prompt_kind}.prompt.{prompt_file_counter:04d}.yaml"
            write_prompt_file(prompt_file, prompt_text, image_paths=image_paths)
            return ["--prompt-file", str(prompt_file)]
        return ["--prompt", prompt_text]

    def _level_start_prompt_images(state: dict | None, *, initial: bool = False) -> list[Path]:
        nonlocal last_prompted_image_level
        if not state:
            return []
        try:
            level = int(state.get("current_level", 0) or 0)
        except Exception:
            return []
        if level <= 0:
            return []

        per_level_image = level_start_images_dir / f"level_{level:02d}-start.png"
        if not per_level_image.exists():
            pixels = load_current_pixels()
            if pixels is None:
                raise RuntimeError(
                    "Unable to generate level-start image: missing current grid "
                    f"at {arc_state_dir / 'current_grid.npy'}."
                )
            try:
                render_grid_to_image(pixels, per_level_image, scale=8, grid_lines=False)
            except Exception as exc:
                raise RuntimeError(
                    f"Failed to render level-start image for level {level}: {exc}"
                ) from exc
            if not per_level_image.exists():
                raise RuntimeError(
                    f"Level-start image generation failed for level {level}: "
                    f"{per_level_image} was not created."
                )

        if (
            (not current_level_start_image.exists())
            or current_level_start_image.read_bytes() != per_level_image.read_bytes()
        ):
            shutil.copyfile(per_level_image, current_level_start_image)

        # Attach once on initial conversation and on any level transitions
        # (including regressions after reset/full_reset).
        should_attach = initial or (last_prompted_image_level != level)
        last_prompted_image_level = level
        return [current_level_start_image] if should_attach else []

    super_env = dict(os.environ)
    super_env["ARC_OPERATION_MODE"] = str(args.operation_mode).strip().upper()
    super_env.setdefault("ARC_ENVIRONMENTS_DIR", str(arc_env_dir))
    super_env["ARC_STATE_DIR"] = str(arc_state_dir)
    super_env["PATH"] = f"{run_bin_dir}:{os.environ.get('PATH', '')}"

    def resume_super(prompt: str | None = None, *, image_paths: list[Path] | None = None) -> str:
        resume_args: list[str] = [
            "resume",
            str(session_file),
            "--config", str(super_config),
            "--workspace", str(run_dir),
            "--config-dir", str(run_config_dir),
            "--agent-dir", str(agent_dir),
            "--supervisor-dir", str(supervisor_dir),
            *_provider_args(),
            *_supervisor_args(),
            "--cycle-limit", str(cycle_limit),
        ]
        if prompt:
            resume_args += _prompt_args(prompt, prompt_kind="resume", image_paths=image_paths)
        if args.verbose:
            resume_args += ["--output", str(session_file)]
            return run_super(resume_args, stream=True, cwd=run_dir, env=super_env)
        resume_args += ["--output", str(tmp_session)]
        stdout = run_super(resume_args, cwd=run_dir, env=super_env)
        shutil.move(str(tmp_session), str(session_file))
        return stdout

    log(f"[harness] session: {session_dir}")
    log(f"[harness] run dir: {run_dir}")
    log(f"[harness] agent dir: {agent_dir}")
    log(f"[harness] supervisor dir: {supervisor_dir}")
    log(f"[harness] arc state dir: {arc_state_dir}")
    log(f"[harness] game: {args.game_id}")
    if args.open_scorecard or args.scorecard_id:
        log("[harness] NOTE: scorecard integration is disabled in tool-driven mode.")
    if args.no_explore:
        log("[harness] auto input exploration is disabled (--no-explore).")
    else:
        log("[harness] auto input exploration is enabled.")

    # Initialize state artifacts before first agent turn.
    init_result, _, init_rc = run_arc_action({"action": "status", "game_id": args.game_id})
    if init_rc != 0:
        log("[harness] failed to initialize state with arc_action status")
        sys.exit(1)
    log(f"[harness] active game id: {active_game_id}")
    log(f"[harness] initialized: {format_state_summary(load_state())}")

    initial_prompt = (
        "Game state initialized. Use shell exactly once this turn to execute arc_action "
        "(status, run_script, or reset_level). "
        "For run_script, pass script via stdin heredoc (do not use --script), e.g. "
        "`cat <<'PY' | arc_action run_script` ... `PY`. "
        "Use arc_get_state to read current machine state, then continue solving. "
        "Use agent_lib.py for persistent reusable helper functions."
    )
    if init_result and isinstance(init_result.get("state"), str):
        initial_prompt += f"\nCurrent state: {init_result.get('state')}"
    init_state = load_state() or {}
    at_fresh_game_start = (
        int(init_state.get("current_level", 0) or 0) == 1
        and int(init_state.get("levels_completed", 0) or 0) == 0
    )
    should_auto_explore_once = (
        (not args.no_explore)
        and at_fresh_game_start
        and (not auto_explore_once_marker.exists())
    )
    if should_auto_explore_once:
        auto_explore_summary = run_input_exploration_from_reset()
        if auto_explore_summary.strip():
            initial_prompt += "\n\n" + auto_explore_summary
        auto_explore_once_marker.parent.mkdir(parents=True, exist_ok=True)
        auto_explore_once_marker.write_text(datetime.now(timezone.utc).isoformat() + "\n")
        log("[harness] auto input exploration completed (one-time at game start).")
    elif not args.no_explore:
        if not at_fresh_game_start:
            log("[harness] skipping auto input exploration (not fresh game start).")
        else:
            log("[harness] skipping auto input exploration (already ran once).")

    log("[harness] starting super new...")
    init_images = _level_start_prompt_images(init_state, initial=True)
    run_super([
        "new",
        "--config", str(super_config),
        "--workspace", str(run_dir),
        "--config-dir", str(run_config_dir),
        "--agent-dir", str(agent_dir),
        "--supervisor-dir", str(supervisor_dir),
        *_provider_args(),
        *_supervisor_args(),
        "--cycle-limit", str(cycle_limit),
        *_prompt_args(initial_prompt, prompt_kind="new", image_paths=init_images),
        "--output", str(session_file),
    ], stream=args.verbose, cwd=run_dir, env=super_env)

    super_turn = 1
    stale_turns = 0
    game_over_resets = 0
    last_engine_turn = load_engine_turn()
    last_recorded_completed_level = read_max_recorded_completion_level(completions_md)
    pending_auto_explore_summary = ""

    while super_turn <= args.max_turns:
        state = load_state()
        prev_completed = int(state.get("levels_completed", 0)) if state else 0
        log(f"[harness] turn {super_turn}: {format_state_summary(state)}")

        if state and state.get("state") == "WIN":
            log(f"[harness] GAME WON after {super_turn} turns")
            break

        if super_turn >= args.max_turns:
            log(f"[harness] max turns ({args.max_turns}) reached")
            break

        prompt_lines: list[str] = []
        current_engine_turn = load_engine_turn()
        if current_engine_turn <= last_engine_turn:
            stale_turns += 1
        else:
            stale_turns = 0
            last_engine_turn = current_engine_turn

        if state and state.get("state") == "GAME_OVER":
            game_over_resets += 1
            log(
                f"[harness] GAME_OVER detected "
                f"(auto-reset {game_over_resets}/{args.max_game_over_resets})"
            )
            if game_over_resets > args.max_game_over_resets:
                log("[harness] max GAME_OVER auto-resets reached, stopping")
                break
            reset_result, reset_stdout, reset_rc = run_arc_action(
                {"action": "reset_level", "game_id": args.game_id}
            )
            if reset_rc != 0:
                log("[harness] auto-reset failed")
                if reset_stdout:
                    log(f"[harness] reset output: {reset_stdout}")
                break
            state = load_state()
            prompt_lines.append(
                "Previous script ended in GAME_OVER. Harness auto-reset the level. "
                "Continue from the new post-reset state."
            )
            if reset_result:
                prompt_lines.append(f"Reset result: {json.dumps(reset_result)}")

        if stale_turns >= 2:
            prompt_lines.append(
                "No arc_action execution was detected in recent turns. "
                "Execute exactly one shell command invoking arc_action this turn."
            )
        if pending_auto_explore_summary.strip():
            prompt_lines.append(pending_auto_explore_summary.strip())
            pending_auto_explore_summary = ""

        prompt_lines.append(f"Current summary: {format_state_summary(state)}")
        prompt_lines.append("Continue solving the current level.")
        prompt = "\n".join(prompt_lines)

        prompt_images = _level_start_prompt_images(state)
        stdout = resume_super(prompt, image_paths=prompt_images)
        if not stdout.strip():
            log("[harness] warning: empty super response")

        # Record level completions based on authoritative post-turn state.
        post_state = load_state()
        post_completed = int(post_state.get("levels_completed", 0)) if post_state else 0
        if post_completed > prev_completed:
            # If arc_action already recorded completions directly, refresh and
            # avoid duplicate append blocks in harness.
            last_recorded_completed_level = max(
                last_recorded_completed_level,
                read_max_recorded_completion_level(completions_md),
            )
            events = load_history_events(history_json)
            completion_windows = completion_action_windows_by_level(events)
            tool_turn = load_engine_turn()
            win_script = (
                arc_state_dir / "script-history" / f"turn_{tool_turn:03d}_script.py"
            )
            win_script_rel = None
            if win_script.exists():
                try:
                    win_script_rel = str(win_script.relative_to(run_dir))
                except Exception:
                    win_script_rel = str(win_script)
            for completed_level in range(prev_completed + 1, post_completed + 1):
                # Avoid duplicate writes if loop restarts or state is re-read.
                if completed_level <= last_recorded_completed_level:
                    continue
                level_actions = completion_windows.get(completed_level, [])
                append_level_completion_record(
                    completions_file=completions_md,
                    completed_level=completed_level,
                    actions=level_actions,
                    harness_turn=super_turn,
                    tool_turn=tool_turn,
                    winning_script_relpath=win_script_rel,
                )
                last_recorded_completed_level = completed_level
                log(
                    "[harness] level completion recorded: "
                    f"level={completed_level} actions_in_level_window={len(level_actions)}"
                )
            if not args.no_explore and (post_state and post_state.get("state") != "WIN"):
                # Do not auto-explore here: arc_action reset_level resets campaign
                # progress (levels_completed), so probing after a level completion
                # would destroy run progress.
                log(
                    "[harness] skipping post-completion auto exploration "
                    "(reset_level would reset campaign progress)"
                )
        super_turn += 1

    log(f"[harness] session files: {session_dir}")


if __name__ == "__main__":
    main()
