"""ARC-AGI-3 supervisor harness: drives the super CLI + game environment loop."""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import shutil
import subprocess
import sys
import textwrap
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

try:
    from game_state import (
        COLOR_NAMES,
        _connected_components_8,
        render_grid_to_image,
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
    # Level Knowledge (Persistent Across Levels)

    Keep this file cumulative for the whole game. Do not delete prior levels.
    Add/update one section per level as understanding improves.

    ## Level N Template
    ### Goal
    - [LOW/MED/HIGH] concise win condition

    ### Carryover Mechanics
    - [LOW/MED/HIGH] mechanic reused from previous levels

    ### New/Changed Mechanics
    - [LOW/MED/HIGH] mechanic introduced or modified in this level

    ### Canonical Level Completion Theory
    - [LOW/MED/HIGH][sat/unsat] backward completion statement

    ### Backward Causal Steps
    - [LOW/MED/HIGH][sat/unsat] 3) ...
    - [LOW/MED/HIGH][sat/unsat] 2) ...
    - [LOW/MED/HIGH][sat/unsat] 1) ...
    - [LOW/MED/HIGH][sat/unsat] 0) ...

    ### Evidence / Experiments
    - action-linked evidence only (probe, result, conclusion)
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
    \"\"\"Persistent helper library for ARC REPL exec turns.

    Put reusable game-agnostic helpers here.
    Every arc_repl exec call auto-loads this module before executing
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


def format_change_records(changes: list[dict]) -> str:
    """Format tool diff records (`changes`) as explicit cell transitions."""
    if not changes:
        return "(no changes)"
    lines = [
        f"changed_pixels={len(changes)}",
        "format: (row,col): before->after",
    ]
    skipped = 0
    for ch in changes:
        try:
            row = int(ch.get("row"))
            col = int(ch.get("col"))
            before = str(ch.get("before", "?"))
            after = str(ch.get("after", "?"))
        except Exception:
            skipped += 1
            continue
        lines.append(f"({row},{col}): {before}->{after}")
    if len(lines) <= 2:
        return "(invalid change records)"
    if skipped:
        lines.append(f"note: skipped_malformed_change_records={skipped}")
    return "\n".join(lines)


def diff_change_records(before: np.ndarray, after: np.ndarray) -> list[dict]:
    """Return per-cell before/after records between two 64x64 grids."""
    if before.shape != after.shape:
        raise RuntimeError(
            f"Grid shape mismatch for diff generation: before={before.shape} after={after.shape}"
        )
    changed = np.argwhere(before != after)
    records: list[dict] = []
    for row, col in changed:
        r = int(row)
        c = int(col)
        records.append(
            {
                "row": r,
                "col": c,
                "before": f"{int(before[r, c]):X}",
                "after": f"{int(after[r, c]):X}",
            }
        )
    return records


def collect_palette_from_change_records(changes: list[dict]) -> set[int]:
    """Collect numeric color IDs appearing in change records."""
    palette: set[int] = set()
    for ch in changes:
        before = _parse_color_id(ch.get("before"))
        after = _parse_color_id(ch.get("after"))
        if before is not None:
            palette.add(before)
        if after is not None:
            palette.add(after)
    return palette


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
    """Batch mode: capture stdout+stderr and print both to harness stderr.

    This keeps run logs self-contained for debugging even when `super` is not
    in streaming mode.
    """
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=cwd or str(PROJECT_ROOT),
        env=env,
    )
    if result.stdout.strip():
        for line in result.stdout.strip().splitlines():
            print(f"[super][stdout] {line}", file=sys.stderr, flush=True)
    if result.stderr.strip():
        for line in result.stderr.strip().splitlines():
            print(f"[super][stderr] {line}", file=sys.stderr, flush=True)
    if result.returncode != 0:
        raise RuntimeError(
            "super exited with code "
            f"{result.returncode} (stdout/stderr captured in harness log)"
        )
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


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _terminate_pid(pid: int, *, timeout_s: float = 1.5) -> bool:
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return True
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if not _pid_exists(pid):
            return True
        time.sleep(0.05)
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        return True
    time.sleep(0.05)
    return not _pid_exists(pid)


def _read_pid_cmdline(pid: int) -> str:
    cmdline_path = Path("/proc") / str(pid) / "cmdline"
    try:
        raw = cmdline_path.read_bytes()
    except Exception:
        return ""
    return raw.replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()


def _collect_active_run_ids(project_root: Path) -> set[str]:
    run_ids: set[str] = set()
    try:
        ps = subprocess.run(
            ["ps", "-eo", "args="],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return run_ids
    if ps.returncode != 0:
        return run_ids
    for line in ps.stdout.splitlines():
        if "harness.py" not in line and "run-config.ts" not in line:
            continue
        for m in re.finditer(r"/runs/([^/\s]+)/", line):
            run_ids.add(m.group(1))
        m = re.search(r"--session-name\s+([^\s]+)", line)
        if m:
            run_ids.add(m.group(1))
    return run_ids


def cleanup_orphan_repl_daemons(
    project_root: Path,
    *,
    preserve_run_ids: set[str] | None = None,
) -> dict[str, int]:
    """Best-effort cleanup for leaked arc_repl daemons from inactive runs."""
    preserve = set(preserve_run_ids or set())
    active_run_ids = _collect_active_run_ids(project_root).union(preserve)
    runs_root = project_root / "runs"
    if not runs_root.exists():
        return {"killed": 0, "stale_files_removed": 0, "skipped_active": 0}

    killed = 0
    stale_files_removed = 0
    skipped_active = 0

    for pid_file in runs_root.glob("*/supervisor/arc/repl-sessions/*/daemon.pid"):
        try:
            run_id = pid_file.relative_to(runs_root).parts[0]
        except Exception:
            continue
        if run_id in active_run_ids:
            skipped_active += 1
            continue
        try:
            pid_raw = pid_file.read_text().strip()
            pid = int(pid_raw)
        except Exception:
            try:
                pid_file.unlink()
                stale_files_removed += 1
            except Exception:
                pass
            continue

        cmdline = _read_pid_cmdline(pid)
        if not cmdline:
            try:
                pid_file.unlink()
                stale_files_removed += 1
            except Exception:
                pass
            continue
        if "arc_repl.py" not in cmdline or "--daemon" not in cmdline:
            # PID was reused by another process; do not touch it.
            continue
        if _terminate_pid(pid):
            killed += 1
            try:
                pid_file.unlink()
            except Exception:
                pass
    return {
        "killed": killed,
        "stale_files_removed": stale_files_removed,
        "skipped_active": skipped_active,
    }


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
        "--max-turns", type=int, default=None,
        help="Maximum harness turns before stopping (default: unlimited)",
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
    parser.add_argument(
        "--arc-backend",
        default="api",
        choices=["api", "server"],
        help=(
            "ARC HTTP backend target: `api` uses https://three.arcprize.org; "
            "`server` uses a local ARC server (default http://127.0.0.1:8000)."
        ),
    )
    parser.add_argument(
        "--arc-base-url",
        default=None,
        help=(
            "Override ARC base URL for Arcade API calls. "
            "If unset, derives from --arc-backend."
        ),
    )
    return parser.parse_args()


def setup_run_dir(run_dir: Path, agent_dir: Path, supervisor_dir: Path, log) -> None:
    """Set up an isolated run directory with split agent/supervisor dirs."""
    run_dir.mkdir(parents=True, exist_ok=True)
    agent_dir.mkdir(parents=True, exist_ok=True)
    supervisor_dir.mkdir(parents=True, exist_ok=True)

    # Do not copy environment source into run workspace.
    # arc_repl loads environments from shared project-level environment_files.

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
    prompts_dir = run_config_dir / "prompts"
    tools_dir.mkdir(parents=True, exist_ok=True)
    bin_dir.mkdir(parents=True, exist_ok=True)
    prompts_dir.mkdir(parents=True, exist_ok=True)

    for filename in (
        "arc_action.py",  # dependency module used by arc_repl.py helpers
        "arc_repl.py",
        "arc_repl_cli.py",
    ):
        src = PROJECT_ROOT / "tools" / filename
        dst = tools_dir / filename
        shutil.copyfile(src, dst)

    py = str(PROJECT_VENV_PYTHON)
    arc_repl_wrapper = f"""#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
CONFIG_DIR="$(cd "${{SCRIPT_DIR}}/.." && pwd)"
exec "{py}" "${{CONFIG_DIR}}/tools/arc_repl_cli.py" "$@"
"""
    arc_repl_path = bin_dir / "arc_repl"
    arc_repl_path.write_text(arc_repl_wrapper)
    arc_repl_path.chmod(0o755)

    # Super config_file references are resolved under --config-dir.
    # Stage prompt assets into per-run config dir so template includes remain valid.
    src_prompts_dir = PROJECT_ROOT / "prompts"
    if not src_prompts_dir.exists():
        raise RuntimeError(f"missing prompts directory: {src_prompts_dir}")
    for src in src_prompts_dir.rglob("*"):
        rel = src.relative_to(src_prompts_dir)
        dst = prompts_dir / rel
        if src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)

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
    operation_mode_name = str(args.operation_mode).strip().upper()
    if args.open_scorecard and args.scorecard_id:
        raise RuntimeError(
            "Use either --open-scorecard (create new) or --scorecard-id (reuse existing), not both."
        )

    def _resolve_arc_base_url() -> str:
        if args.arc_base_url and str(args.arc_base_url).strip():
            return str(args.arc_base_url).strip()
        if args.arc_backend == "server":
            return "http://127.0.0.1:8000"
        return "https://three.arcprize.org"

    arc_base_url = _resolve_arc_base_url()
    offline_mode = operation_mode_name == "OFFLINE"

    # Session and run directories
    session_name = args.session_name or datetime.now().strftime("%Y%m%d_%H%M%S")
    session_dir = CTXS / session_name
    session_dir.mkdir(parents=True, exist_ok=True)
    session_file = session_dir / "session.md"
    tmp_session = session_dir / "session.next.md"

    # Per-run isolation: each run gets its own working directory
    run_dir = PROJECT_ROOT / "runs" / session_name
    def log(msg: str) -> None:
        print(msg, file=sys.stderr, flush=True)
    cleanup_stats = cleanup_orphan_repl_daemons(
        PROJECT_ROOT,
        preserve_run_ids={session_name},
    )
    if cleanup_stats["killed"] or cleanup_stats["stale_files_removed"]:
        log(
            "[harness] cleaned stale repl daemons: "
            f"killed={cleanup_stats['killed']} "
            f"stale_pid_files_removed={cleanup_stats['stale_files_removed']} "
            f"skipped_active={cleanup_stats['skipped_active']}"
        )
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
    run_arc_repl_tool = run_tools_dir / "arc_repl.py"
    if not run_arc_repl_tool.exists():
        log(f"[harness] missing tool script: {run_arc_repl_tool}")
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
    scorecard_meta_path = session_dir / "scorecard.json"

    active_scorecard_id = str(args.scorecard_id or "").strip() or None
    scorecard_created_here = False
    scorecard_api_url: str | None = None
    scorecard_web_url: str | None = None
    scorecard_client: Any | None = None

    def _build_scorecard_client():
        import arc_agi
        from arc_agi import OperationMode

        mode = OperationMode[operation_mode_name]
        return arc_agi.Arcade(
            operation_mode=mode,
            arc_base_url=arc_base_url,
            environments_dir=str(arc_env_dir),
        )

    if args.open_scorecard or active_scorecard_id:
        if operation_mode_name != "ONLINE":
            raise RuntimeError(
                "Scorecards require ONLINE mode. Re-run with --operation-mode ONLINE."
            )
        scorecard_client = _build_scorecard_client()
        if active_scorecard_id:
            scorecard_client.get_scorecard(active_scorecard_id)
        else:
            tags = [
                "arc-agi-harness",
                "tool-driven",
                f"game:{args.game_id}",
            ]
            opaque = {
                "session_name": session_name,
                "game_id": str(args.game_id),
                "started_at": datetime.now(timezone.utc).isoformat(),
            }
            active_scorecard_id = str(
                scorecard_client.open_scorecard(tags=tags, opaque=opaque)
            )
            scorecard_created_here = True
        scorecard_api_url = f"{arc_base_url.rstrip('/')}/api/scorecard/{active_scorecard_id}"
        scorecard_web_url = f"{arc_base_url.rstrip('/')}/scorecards/{active_scorecard_id}"
        scorecard_meta_path.write_text(
            json.dumps(
                {
                    "scorecard_id": active_scorecard_id,
                    "api_url": scorecard_api_url,
                    "web_url": scorecard_web_url,
                    "created_here": scorecard_created_here,
                    "operation_mode": operation_mode_name,
                    "arc_base_url": arc_base_url,
                },
                indent=2,
            )
            + "\n"
        )

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
            if not isinstance(data, dict):
                raise RuntimeError("state.json must contain a JSON object")
            return data
        except Exception as exc:
            raise RuntimeError(f"Failed to parse state JSON: {state_json}: {exc}") from exc

    def load_engine_turn() -> int:
        if not history_json.exists():
            return 0
        try:
            data = json.loads(history_json.read_text())
            if not isinstance(data, dict):
                raise RuntimeError("tool-engine-history.json must contain a JSON object")
            turn = data.get("turn", 0)
            if not isinstance(turn, int):
                raise RuntimeError("tool-engine-history.json turn must be an integer")
            return int(turn)
        except Exception as exc:
            raise RuntimeError(f"Failed to parse engine history JSON: {history_json}: {exc}") from exc

    def load_conversation_id(doc_path: Path) -> str | None:
        if not doc_path.exists():
            return None
        try:
            text = doc_path.read_text()
        except Exception:
            return None
        lines = text.splitlines()
        if not lines or lines[0].strip() != "---":
            return None
        for line in lines[1:80]:
            if line.strip() == "---":
                break
            m = re.match(r"^\s*conversation_id\s*:\s*(.+?)\s*$", line)
            if m:
                return m.group(1).strip()
        return None

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
    active_conversation_id = "harness_bootstrap"
    active_actual_conversation_id: str | None = None
    conversation_aliases: dict[str, str] = {}

    def run_arc_repl(payload: dict) -> tuple[dict | None, str, int]:
        nonlocal active_game_id, active_conversation_id
        request = dict(payload)
        action_name = str(request.get("action", "")).strip()
        requested_game_id = str(request.get("game_id", "")).strip()
        # Keep all harness-side calls on one canonical game_id lineage.
        # After the first status call, arc_repl returns a resolved id
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
            str(run_arc_repl_tool),
        ]
        child_env = dict(os.environ)
        child_env["ARC_OPERATION_MODE"] = str(args.operation_mode).strip().upper()
        child_env["ARC_BASE_URL"] = arc_base_url
        child_env.setdefault("ARC_ENVIRONMENTS_DIR", str(arc_env_dir))
        child_env["ARC_STATE_DIR"] = str(arc_state_dir)
        child_env["ARC_CONVERSATION_ID"] = active_conversation_id
        if active_scorecard_id:
            child_env["ARC_SCORECARD_ID"] = active_scorecard_id
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
                log(f"[arc_repl] {line}")
        stdout = proc.stdout.strip()
        parsed: dict | None = None
        allow_raw_stdout = action_name == "exec"
        if allow_raw_stdout:
            return None, stdout, proc.returncode
        if stdout:
            try:
                maybe = json.loads(stdout)
            except Exception as exc:
                if proc.returncode == 0:
                    preview = stdout[:800].replace("\n", "\\n")
                    raise RuntimeError(
                        "arc_repl returned non-JSON stdout despite success status: "
                        f"{exc}. stdout_preview={preview}"
                    ) from exc
            else:
                if isinstance(maybe, dict):
                    parsed = maybe
                    if (
                        active_scorecard_id
                        and action_name == "status"
                        and proc.returncode == 0
                    ):
                        echoed_scorecard_id = str(parsed.get("scorecard_id", "") or "").strip()
                        if echoed_scorecard_id != active_scorecard_id:
                            raise RuntimeError(
                                "arc_repl status did not echo expected scorecard_id: "
                                f"expected={active_scorecard_id!r} "
                                f"got={echoed_scorecard_id!r}"
                            )
                    resolved_game_id = str(parsed.get("game_id", "")).strip()
                    if resolved_game_id:
                        active_game_id = resolved_game_id
                elif proc.returncode == 0:
                    raise RuntimeError(
                        "arc_repl returned JSON that is not an object on success."
                    )
        elif proc.returncode == 0:
            raise RuntimeError("arc_repl returned empty stdout on success.")
        return parsed, stdout, proc.returncode

    def sync_active_conversation_id_from_session() -> None:
        nonlocal active_conversation_id, active_actual_conversation_id
        parsed = load_conversation_id(session_file)
        if not parsed:
            return
        alias = conversation_aliases.get(parsed)
        if alias is None:
            if active_actual_conversation_id is None and active_conversation_id == "harness_bootstrap":
                # Preserve first-turn REPL state by aliasing the first real
                # conversation id to the bootstrap key used during `super new`.
                alias = active_conversation_id
            else:
                alias = parsed
            conversation_aliases[parsed] = alias
        if parsed != active_actual_conversation_id:
            log(
                "[harness] conversation update: "
                f"actual={parsed} repl_session={alias}"
            )
        active_actual_conversation_id = parsed
        active_conversation_id = alias

    def load_current_pixels() -> np.ndarray | None:
        grid_path = arc_state_dir / "current_grid.npy"
        if not grid_path.exists():
            return None
        try:
            return np.load(grid_path)
        except Exception as exc:
            raise RuntimeError(f"Failed to load current grid file: {grid_path}: {exc}") from exc

    def run_input_exploration_from_reset() -> str:
        """Auto-probe every available input from a reset baseline.

        Runs each action from level-start state, captures full diffs, and
        resets between attempts. For ACTION6, clicks every contiguous non-zero
        color component centroid.
        """
        # Force reset baseline before probing a level.
        run_arc_repl({"action": "reset_level", "game_id": args.game_id})
        status_result, status_stdout, status_rc = run_arc_repl(
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
                    before_pixels = load_current_pixels()
                    before_status, _, before_status_rc = run_arc_repl(
                        {"action": "status", "game_id": args.game_id}
                    )
                    _, stdout, rc = run_arc_repl(
                        {"action": "exec", "game_id": args.game_id, "script": script}
                    )
                    after_status, after_stdout, after_status_rc = run_arc_repl(
                        {"action": "status", "game_id": args.game_id}
                    )
                    after_pixels = load_current_pixels()
                    if rc == 0 and before_pixels is not None and after_pixels is not None:
                        before_level = (
                            int(before_status.get("levels_completed", 0))
                            if isinstance(before_status, dict)
                            else None
                        )
                        after_level = (
                            int(after_status.get("levels_completed", 0))
                            if isinstance(after_status, dict)
                            else None
                        )
                        if (
                            before_status_rc == 0
                            and after_status_rc == 0
                            and before_level is not None
                            and after_level is not None
                            and after_level > before_level
                        ):
                            no_effect.append(f"{label} (diff suppressed: level transition)")
                        else:
                            changes = diff_change_records(before_pixels, after_pixels)
                            changed_pixels = len(changes)
                            if changed_pixels > 0:
                                motion_palette.update(collect_palette_from_change_records(changes))
                                diff_text = format_change_records(changes)
                                diff_sections.append(f"### {label}\n```\n{diff_text}\n```")
                            else:
                                no_effect.append(label)
                    else:
                        status_detail = (
                            after_stdout.strip()
                            if after_status_rc != 0 and after_stdout.strip()
                            else ""
                        )
                        detail = status_detail or stdout.strip() or "exec failed"
                        error_text = detail
                        no_effect.append(f"{label} (error: {error_text})")
                    run_arc_repl({"action": "reset_level", "game_id": args.game_id})
                continue

            label = f"ACTION{action_id}"
            script = f"env.step({action_id})"
            before_pixels = load_current_pixels()
            before_status, _, before_status_rc = run_arc_repl(
                {"action": "status", "game_id": args.game_id}
            )
            _, stdout, rc = run_arc_repl(
                {"action": "exec", "game_id": args.game_id, "script": script}
            )
            after_status, after_stdout, after_status_rc = run_arc_repl(
                {"action": "status", "game_id": args.game_id}
            )
            after_pixels = load_current_pixels()
            if rc == 0 and before_pixels is not None and after_pixels is not None:
                before_level = (
                    int(before_status.get("levels_completed", 0))
                    if isinstance(before_status, dict)
                    else None
                )
                after_level = (
                    int(after_status.get("levels_completed", 0))
                    if isinstance(after_status, dict)
                    else None
                )
                if (
                    before_status_rc == 0
                    and after_status_rc == 0
                    and before_level is not None
                    and after_level is not None
                    and after_level > before_level
                ):
                    no_effect.append(f"{label} (diff suppressed: level transition)")
                else:
                    changes = diff_change_records(before_pixels, after_pixels)
                    changed_pixels = len(changes)
                    if changed_pixels > 0:
                        motion_palette.update(collect_palette_from_change_records(changes))
                        diff_text = format_change_records(changes)
                        diff_sections.append(f"### {label}\n```\n{diff_text}\n```")
                    else:
                        no_effect.append(label)
            else:
                status_detail = (
                    after_stdout.strip()
                    if after_status_rc != 0 and after_stdout.strip()
                    else ""
                )
                detail = status_detail or stdout.strip() or "exec failed"
                error_text = detail
                no_effect.append(f"{label} (error: {error_text})")
            run_arc_repl({"action": "reset_level", "game_id": args.game_id})

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
    enable_level_start_images = False
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
        if not enable_level_start_images:
            return []
        if not state:
            raise RuntimeError(
                "Cannot determine level-start prompt image: state is unavailable."
            )
        try:
            level = int(state.get("current_level", 0) or 0)
        except Exception:
            raise RuntimeError(
                "Cannot determine level-start prompt image: invalid current_level in state."
            )
        if level <= 0:
            raise RuntimeError(
                f"Cannot determine level-start prompt image: invalid current_level={level}."
            )

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
    super_env["ARC_OPERATION_MODE"] = operation_mode_name
    super_env["ARC_BASE_URL"] = arc_base_url
    super_env.setdefault("ARC_ENVIRONMENTS_DIR", str(arc_env_dir))
    super_env["ARC_STATE_DIR"] = str(arc_state_dir)
    if active_scorecard_id:
        super_env["ARC_SCORECARD_ID"] = active_scorecard_id
    super_env["PATH"] = f"{run_bin_dir}:{os.environ.get('PATH', '')}"

    def resume_super(prompt: str | None = None, *, image_paths: list[Path] | None = None) -> str:
        nonlocal active_conversation_id
        super_env["ARC_CONVERSATION_ID"] = active_conversation_id
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

    def _session_pid_file(conversation_id: str) -> Path:
        return arc_state_dir / "repl-sessions" / conversation_id / "daemon.pid"

    def _shutdown_repl_session(conversation_id: str) -> None:
        nonlocal active_conversation_id
        cid = str(conversation_id or "").strip()
        if not cid:
            return
        pid_file = _session_pid_file(cid)
        if not pid_file.exists():
            return
        prev_conversation_id = active_conversation_id
        try:
            active_conversation_id = cid
            result, stdout, rc = run_arc_repl({"action": "shutdown", "game_id": args.game_id})
            if rc == 0:
                log(f"[harness] arc_repl shutdown sent for conversation={cid}")
            else:
                detail = stdout.strip() if stdout.strip() else "no stdout"
                log(
                    "[harness] arc_repl shutdown failed for "
                    f"conversation={cid}: rc={rc} detail={detail}"
                )
            if result and isinstance(result, dict) and not bool(result.get("ok", False)):
                err = result.get("error")
                log(f"[harness] arc_repl shutdown response error conversation={cid}: {err}")
        except Exception as exc:
            log(f"[harness] arc_repl shutdown exception conversation={cid}: {exc}")
        finally:
            active_conversation_id = prev_conversation_id

    def _terminate_pid(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except OSError:
            return True
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            return True
        deadline = time.time() + 1.5
        while time.time() < deadline:
            try:
                os.kill(pid, 0)
            except OSError:
                return True
            time.sleep(0.05)
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            return True
        time.sleep(0.05)
        try:
            os.kill(pid, 0)
            return False
        except OSError:
            return True

    def cleanup_repl_daemons() -> None:
        # Best-effort graceful shutdown for known conversation ids.
        cids: set[str] = set()
        cids.update(k for k in conversation_aliases.keys() if k)
        cids.update(v for v in conversation_aliases.values() if v)
        if active_actual_conversation_id:
            cids.add(active_actual_conversation_id)
        if active_conversation_id:
            cids.add(active_conversation_id)
        sessions_root = arc_state_dir / "repl-sessions"
        if sessions_root.exists():
            for p in sessions_root.iterdir():
                if p.is_dir():
                    cids.add(p.name)
        for cid in sorted(cids):
            _shutdown_repl_session(cid)

        # Hard cleanup for any local session pid that survived shutdown.
        if not sessions_root.exists():
            return
        for pid_file in sessions_root.glob("*/daemon.pid"):
            try:
                raw = pid_file.read_text().strip()
                pid = int(raw)
            except Exception:
                continue
            if _terminate_pid(pid):
                log(f"[harness] cleaned repl daemon pid={pid} ({pid_file.parent.name})")
            else:
                log(f"[harness] WARNING: failed to terminate repl daemon pid={pid}")

    log(f"[harness] session: {session_dir}")
    log(f"[harness] run dir: {run_dir}")
    log(f"[harness] agent dir: {agent_dir}")
    log(f"[harness] supervisor dir: {supervisor_dir}")
    log(f"[harness] arc state dir: {arc_state_dir}")
    log(f"[harness] game: {args.game_id}")
    log(f"[harness] arc backend: {args.arc_backend}")
    log(f"[harness] arc base url: {arc_base_url}")
    if offline_mode:
        log(
            "[harness] NOTE: operation-mode OFFLINE ignores ARC backend/base-url "
            "and uses local environments only."
        )
    if active_scorecard_id:
        created_status = "created_new" if scorecard_created_here else "reusing_existing"
        log(f"[harness] scorecard: {active_scorecard_id} ({created_status})")
        if scorecard_web_url:
            log(f"[harness] scorecard web url: {scorecard_web_url}")
        if scorecard_api_url:
            log(f"[harness] scorecard api url: {scorecard_api_url}")
    if args.no_explore:
        log("[harness] auto input exploration is disabled (--no-explore).")
    else:
        log("[harness] auto input exploration is enabled.")
    log("[harness] level-start prompt image attachments are disabled.")
    try:
        # Initialize state artifacts before first agent turn.
        init_result, _, init_rc = run_arc_repl({"action": "status", "game_id": args.game_id})
        if init_rc != 0:
            log("[harness] failed to initialize state with arc_repl status")
            sys.exit(1)
        log(f"[harness] active game id: {active_game_id}")
        log(f"[harness] initialized: {format_state_summary(load_state())}")

        initial_prompt = (
            "Game state initialized. Use shell exactly once this turn to execute arc_repl "
            "(status, exec, or reset_level). "
            "For exec, pass Python via stdin heredoc, e.g. "
            "`cat <<'PY' | arc_repl exec` ... `PY`. "
            "Inside exec scripts, use `get_state()` and `env` for state inspection and actions. "
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
        super_env["ARC_CONVERSATION_ID"] = active_conversation_id
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
        sync_active_conversation_id_from_session()

        super_turn = 1
        stale_turns = 0
        game_over_resets = 0
        last_engine_turn = load_engine_turn()
        last_recorded_completed_level = read_max_recorded_completion_level(completions_md)
        pending_auto_explore_summary = ""

        while True:
            if args.max_turns is not None and super_turn > args.max_turns:
                log(f"[harness] max turns ({args.max_turns}) reached")
                break

            state = load_state()
            prev_completed = int(state.get("levels_completed", 0)) if state else 0
            log(f"[harness] turn {super_turn}: {format_state_summary(state)}")

            if state and state.get("state") == "WIN":
                log(f"[harness] GAME WON after {super_turn} turns")
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
                reset_result, reset_stdout, reset_rc = run_arc_repl(
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
                    "No arc_repl execution was detected in recent turns. "
                    "Execute exactly one shell command invoking arc_repl this turn."
                )
            if pending_auto_explore_summary.strip():
                prompt_lines.append(pending_auto_explore_summary.strip())
                pending_auto_explore_summary = ""

            prompt_lines.append(f"Current summary: {format_state_summary(state)}")
            prompt_lines.append("Continue solving the current level.")
            prompt = "\n".join(prompt_lines)

            prompt_images = _level_start_prompt_images(state)
            stdout = resume_super(prompt, image_paths=prompt_images)
            sync_active_conversation_id_from_session()
            if not stdout.strip():
                log(
                    "[harness] super returned empty assistant response; "
                    "continuing (likely supervisor fork/transition without assistant text)."
                )

            # Record level completions based on authoritative post-turn state.
            post_state = load_state()
            post_completed = int(post_state.get("levels_completed", 0)) if post_state else 0
            if post_completed > prev_completed:
                # If arc_repl already recorded completions directly, refresh and
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
                    # Do not auto-explore here: arc_repl reset_level resets campaign
                    # progress (levels_completed), so probing after a level completion
                    # would destroy run progress.
                    log(
                        "[harness] skipping post-completion auto exploration "
                        "(reset_level would reset campaign progress)"
                    )
            super_turn += 1

        log(f"[harness] session files: {session_dir}")
    finally:
        if scorecard_created_here and active_scorecard_id:
            try:
                if scorecard_client is None:
                    scorecard_client = _build_scorecard_client()
                final_scorecard = scorecard_client.close_scorecard(active_scorecard_id)
                if final_scorecard is not None:
                    score = getattr(final_scorecard, "score", None)
                    log(
                        "[harness] scorecard closed: "
                        f"id={active_scorecard_id} score={score}"
                    )
                    scorecard_meta_path.write_text(
                        json.dumps(
                            {
                                "scorecard_id": active_scorecard_id,
                                "api_url": scorecard_api_url,
                                "web_url": scorecard_web_url,
                                "created_here": True,
                                "closed": True,
                                "final_score": score,
                                "operation_mode": operation_mode_name,
                                "arc_base_url": arc_base_url,
                            },
                            indent=2,
                        )
                        + "\n"
                    )
                else:
                    log(
                        "[harness] WARNING: close_scorecard returned no data "
                        f"for id={active_scorecard_id}"
                    )
            except Exception as exc:
                status_code = getattr(getattr(exc, "response", None), "status_code", None)
                if status_code == 404:
                    # Current API behavior: close/get on an already-closed card returns 404.
                    # This commonly happens if the scorecard auto-closed due inactivity.
                    log(
                        "[harness] scorecard already closed before explicit close "
                        f"(id={active_scorecard_id}, status=404)"
                    )
                    try:
                        scorecard_meta_path.write_text(
                            json.dumps(
                                {
                                    "scorecard_id": active_scorecard_id,
                                    "api_url": scorecard_api_url,
                                    "web_url": scorecard_web_url,
                                    "created_here": True,
                                    "closed": True,
                                    "close_status": "already_closed",
                                    "operation_mode": operation_mode_name,
                                    "arc_base_url": arc_base_url,
                                },
                                indent=2,
                            )
                            + "\n"
                        )
                    except Exception:
                        pass
                else:
                    log(
                        "[harness] WARNING: failed to close scorecard "
                        f"id={active_scorecard_id}: {exc}"
                    )
        cleanup_repl_daemons()


if __name__ == "__main__":
    main()
