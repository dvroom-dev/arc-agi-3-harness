"""Pretty-print ARC-AGI-3 game state for humans and LLMs."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

try:
    from rich.console import Console
    from rich.style import Style
    from rich.text import Text

    RICH_AVAILABLE = True
except Exception:
    Console = None  # type: ignore[assignment]
    Style = None  # type: ignore[assignment]
    Text = None  # type: ignore[assignment]
    RICH_AVAILABLE = False

if TYPE_CHECKING:
    from arcengine.enums import FrameDataRaw

# ARC palette labels (aligned to ARC web preview renderer)
COLOR_NAMES = {
    0: "white",
    1: "light-grey",
    2: "grey",
    3: "dark-grey",
    4: "charcoal",
    5: "black",
    6: "magenta",
    7: "pink",
    8: "red",
    9: "blue",
    10: "light-cyan",
    11: "yellow",
    12: "orange",
    13: "maroon",
    14: "green",
    15: "purple",
}

# ARC palette -> RGB (matches ARC web preview renderer)
ARC_COLORS_RGB = {
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


def diff_grids(before: np.ndarray, after: np.ndarray) -> np.ndarray:
    """Subtract before from after. Returns signed int16 array (values -15 to +15)."""
    return after.astype(np.int16) - before.astype(np.int16)


def format_diff_full(diff: np.ndarray) -> str:
    """Format a diff grid as 2-char-per-pixel text. All rows/cols shown.

    .. = unchanged (0), +1 to +F = positive, -1 to -F = negative (hex).
    """
    lines = []
    for row in diff:
        chars = []
        for v in row:
            v = int(v)
            if v == 0:
                chars.append("..")
            elif v > 0:
                chars.append(f"+{v:X}")
            else:
                chars.append(f"-{-v:X}")
        lines.append("".join(chars))
    return "\n".join(lines)


def _connected_components_8(mask: np.ndarray) -> list[list[tuple[int, int]]]:
    """Find connected components in a boolean mask using 8-connectivity."""
    rows, cols = mask.shape
    visited = np.zeros_like(mask, dtype=bool)
    components: list[list[tuple[int, int]]] = []

    for r in range(rows):
        for c in range(cols):
            if mask[r, c] and not visited[r, c]:
                component: list[tuple[int, int]] = []
                queue = [(r, c)]
                visited[r, c] = True
                while queue:
                    cr, cc = queue.pop(0)
                    component.append((cr, cc))
                    for dr in (-1, 0, 1):
                        for dc in (-1, 0, 1):
                            if dr == 0 and dc == 0:
                                continue
                            nr, nc = cr + dr, cc + dc
                            if (
                                0 <= nr < rows
                                and 0 <= nc < cols
                                and mask[nr, nc]
                                and not visited[nr, nc]
                            ):
                                visited[nr, nc] = True
                                queue.append((nr, nc))
                components.append(component)

    return components


def format_diff_minimal(diff: np.ndarray) -> str:
    """Format a diff showing only non-zero bounding boxes.

    For each contiguous (8-connected) non-zero region, prints:
      @(row,col) HxW:
      +1  +3
         -2
    Zeros within the bounding box are shown as spaces.
    Returns '(no changes)' if the diff is all zeros.
    """
    nonzero = diff != 0
    if not np.any(nonzero):
        return "(no changes)"

    components = _connected_components_8(nonzero)
    parts: list[str] = []

    for component in components:
        rows = [p[0] for p in component]
        cols = [p[1] for p in component]
        r_min, r_max = min(rows), max(rows)
        c_min, c_max = min(cols), max(cols)
        h = r_max - r_min + 1
        w = c_max - c_min + 1

        parts.append(f"@({r_min},{c_min}) {h}x{w}:")
        box = diff[r_min : r_max + 1, c_min : c_max + 1]
        for row in box:
            chars = []
            for v in row:
                v = int(v)
                if v == 0:
                    chars.append("  ")
                elif v > 0:
                    chars.append(f"+{v:X}")
                else:
                    chars.append(f"-{-v:X}")
            parts.append("".join(chars))

    return "\n".join(parts)


def pixels_to_hex_grid(pixels: np.ndarray) -> str:
    """Convert a 2D numpy array of color IDs (0-15) to a hex grid string.

    Each cell becomes a single hex character (0-F). One line per row.
    """
    lines = []
    for row in pixels:
        lines.append("".join(f"{int(v):X}" for v in row))
    return "\n".join(lines)


def color_legend(pixels: np.ndarray) -> str:
    """Generate a legend for only the colors present in the grid."""
    unique = sorted(set(int(v) for v in np.unique(pixels)))
    parts = []
    for c in unique:
        name = COLOR_NAMES.get(c, f"color-{c}")
        parts.append(f"{c:X}={name}")
    return " | ".join(parts)


def format_game_state(
    frame: FrameDataRaw,
    pixels: np.ndarray,
    *,
    game_id: str = "",
    last_action: str = "",
    script_output: str = "",
    error: str = "",
    step_snapshots: list[tuple[str, np.ndarray]] | None = None,
    pre_turn_pixels: np.ndarray | None = None,
) -> str:
    """Format a complete game-state.md file.

    When step_snapshots and pre_turn_pixels are provided, renders per-step
    minimal diffs and a full aggregate diff. The Current State section always
    shows the final hex grid.
    """
    lines = ["# Game State\n"]

    # Metadata
    lines.append("## Metadata\n")
    lines.append(f"- game_id: {game_id or frame.game_id}")
    lines.append(f"- guid: {frame.guid}")
    lines.append(f"- state: {frame.state.value}")
    lines.append(f"- levels_completed: {frame.levels_completed}")
    lines.append(f"- win_levels: {frame.win_levels}")
    actions = ", ".join(str(a) for a in frame.available_actions)
    lines.append(f"- available_actions: [{actions}]")
    if last_action:
        lines.append(f"- last_action: {last_action}")
    lines.append("")

    # Error from script execution
    if error:
        lines.append("## Script Error\n")
        lines.append(f"```\n{error}\n```\n")

    # Script stdout
    if script_output:
        lines.append("## Script Output\n")
        lines.append(f"```\n{script_output}\n```\n")

    # Step-by-step execution with per-step minimal diffs
    if step_snapshots and pre_turn_pixels is not None:
        lines.append("## Step-by-Step Execution\n")
        for step_num, (description, step_pixels) in enumerate(step_snapshots, 1):
            prev = pre_turn_pixels if step_num == 1 else step_snapshots[step_num - 2][1]
            step_diff = diff_grids(prev, step_pixels)
            lines.append(f"**Step {step_num}:** {description}")
            lines.append(f"```\n{format_diff_minimal(step_diff)}\n```")

        # Full aggregate diff
        aggregate = diff_grids(pre_turn_pixels, step_snapshots[-1][1])
        lines.append(f"\n## Full Diff ({len(step_snapshots)} steps)\n")
        lines.append(f"```\n{format_diff_full(aggregate)}\n```\n")

    # Current state (final grid — always shown)
    lines.append("## Current State\n")
    lines.append(f"Legend: {color_legend(pixels)}\n")
    lines.append("```")
    lines.append(pixels_to_hex_grid(pixels))
    lines.append("```")

    return "\n".join(lines) + "\n"


def write_game_state(
    path: Path,
    frame: FrameDataRaw,
    pixels: np.ndarray,
    **kwargs,
) -> None:
    """Write game-state.md to disk.

    Accepts the same keyword arguments as format_game_state(), including
    pre_turn_pixels for diff-based step rendering.
    """
    content = format_game_state(frame, pixels, **kwargs)
    path.write_text(content)


def write_machine_state(
    directory: Path,
    frame: FrameDataRaw,
    pixels: np.ndarray,
    *,
    game_id: str = "",
    last_action: str = "",
    step_snapshots: list[tuple[str, np.ndarray]] | None = None,
    telemetry: dict | None = None,
) -> None:
    """Write machine-readable game state files for programmatic access.

    Writes three files to `directory`:
      - current_grid.npy: current pixel grid, shape (64, 64), values 0-15
      - all_grids.npy: all step grids since last reset, shape (N, 64, 64)
      - state.json: metadata dict with game state and step descriptions
    """
    directory.mkdir(parents=True, exist_ok=True)

    # Current grid
    np.save(directory / "current_grid.npy", pixels.astype(np.int8))

    # All step grids stacked
    if step_snapshots:
        grids = np.stack([g for _, g in step_snapshots], axis=0).astype(np.int8)
    else:
        grids = np.empty((0, 64, 64), dtype=np.int8)
    np.save(directory / "all_grids.npy", grids)

    # Metadata JSON
    steps = [desc for desc, _ in step_snapshots] if step_snapshots else []
    state = {
        "game_id": game_id or getattr(frame, "game_id", ""),
        "current_level": frame.levels_completed + 1,
        "state": frame.state.value,
        "levels_completed": frame.levels_completed,
        "win_levels": frame.win_levels,
        "available_actions": [int(a) for a in frame.available_actions],
        "last_action": last_action,
        "full_reset": bool(getattr(frame, "full_reset", False)),
        "action_input": str(getattr(getattr(frame, "action_input", None), "id", "")),
        "total_steps": len(steps),
        "steps": steps,
    }
    if telemetry:
        state["telemetry"] = telemetry
    (directory / "state.json").write_text(json.dumps(state, indent=2))

    # Image rendering disabled by default; numeric grid/diff artifacts are primary.


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    """Convert '#RRGGBB' to (R, G, B) tuple."""
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


# Pre-computed RGB tuples for the ARC palette (index 0-15).
ARC_COLORS_RGB_TUPLES: dict[int, tuple[int, int, int]] = {
    k: _hex_to_rgb(v) for k, v in ARC_COLORS_RGB.items()
}


def render_grid_to_terminal(
    pixels: np.ndarray,
    frame: FrameDataRaw,
    *,
    label: str = "",
    last_action: str = "",
    transition_log: list[str] | None = None,
    error: str = "",
    file=None,
) -> None:
    """Render the game state as a colored grid to the terminal via Rich.

    Uses half-block characters (▀) to pack 2 pixel rows per terminal row.
    Prints metadata header, the grid, and optional transition log.
    """
    if file is None:
        file = sys.stderr
    if not RICH_AVAILABLE:
        # Keep this utility available even when rich is not installed.
        header_parts = []
        if label:
            header_parts.append(label)
        header_parts.append(f"state={frame.state.value}")
        header_parts.append(f"levels={frame.levels_completed}/{frame.win_levels}")
        actions_str = ",".join(str(a) for a in frame.available_actions)
        header_parts.append(f"actions=[{actions_str}]")
        if last_action:
            header_parts.append(f"last={last_action}")
        print("  ".join(header_parts), file=file)
        print(pixels_to_hex_grid(pixels), file=file)
        if transition_log:
            print(f"transitions: {len(transition_log)} steps", file=file)
            for entry in transition_log:
                print(f"  {entry}", file=file)
        if error:
            print(f"ERROR: {error.splitlines()[0]}", file=file)
        return
    console = Console(file=file, highlight=False)

    # Header
    header_parts = []
    if label:
        header_parts.append(label)
    header_parts.append(f"state={frame.state.value}")
    header_parts.append(f"levels={frame.levels_completed}/{frame.win_levels}")
    actions_str = ",".join(str(a) for a in frame.available_actions)
    header_parts.append(f"actions=[{actions_str}]")
    if last_action:
        header_parts.append(f"last={last_action}")
    console.print(f"[bold]{'  '.join(header_parts)}[/bold]")

    # Colored grid using half-block characters
    height, width = pixels.shape
    grid_text = Text()
    for y in range(0, height, 2):
        for x in range(width):
            top = int(pixels[y][x])
            bot = int(pixels[y + 1][x]) if y + 1 < height else 0
            grid_text.append(
                "▀",
                Style(
                    color=ARC_COLORS_RGB.get(top, "#000000"),
                    bgcolor=ARC_COLORS_RGB.get(bot, "#000000"),
                ),
            )
        if y + 2 < height:
            grid_text.append("\n")
    console.print(grid_text)

    # Transition log
    if transition_log:
        console.print(f"[dim]transitions: {len(transition_log)} steps[/dim]")
        for entry in transition_log:
            console.print(f"  [dim]{entry}[/dim]")

    # Error
    if error:
        console.print(f"[bold red]ERROR:[/bold red] {error.splitlines()[0]}")
