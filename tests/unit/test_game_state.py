from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np

import game_state


def _frame(**overrides):
    base = dict(
        game_id="ls20",
        guid="guid-1",
        state=SimpleNamespace(value="NOT_FINISHED"),
        levels_completed=1,
        win_levels=7,
        available_actions=[1, 2, 3, 4],
        action_input=SimpleNamespace(id="ACTION1"),
        full_reset=False,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_diff_and_format_helpers() -> None:
    before = np.array([[0, 1], [2, 3]], dtype=np.int8)
    after = np.array([[0, 2], [2, 1]], dtype=np.int8)
    diff = game_state.diff_grids(before, after)
    assert diff.dtype == np.int16
    full = game_state.format_diff_full(diff)
    assert "..+1" in full
    minimal = game_state.format_diff_minimal(diff)
    assert "@(" in minimal


def test_pixels_to_hex_and_legend() -> None:
    pixels = np.array([[0, 10], [15, 1]], dtype=np.int8)
    assert game_state.pixels_to_hex_grid(pixels) == "0A\nF1"
    legend = game_state.color_legend(pixels)
    assert "0=white" in legend
    assert "F=purple" in legend


def test_format_game_state_includes_sections() -> None:
    frame = _frame()
    pre = np.zeros((2, 2), dtype=np.int8)
    step = np.array([[0, 1], [0, 0]], dtype=np.int8)
    text = game_state.format_game_state(
        frame,
        step,
        game_id="ls20-cb3b57cc",
        last_action="exec",
        script_output="hello",
        error="boom",
        step_snapshots=[("ACTION1", step)],
        pre_turn_pixels=pre,
    )
    assert "# Game State" in text
    assert "## Script Error" in text
    assert "## Script Output" in text
    assert "## Step-by-Step Execution" in text
    assert "## Current State" in text


def test_write_machine_state_and_write_game_state(tmp_path: Path) -> None:
    frame = _frame()
    pixels = np.zeros((64, 64), dtype=np.int8)
    step = np.ones((64, 64), dtype=np.int8)

    state_dir = tmp_path / "arc"
    game_state.write_machine_state(
        state_dir,
        frame,
        pixels,
        game_id="ls20",
        last_action="status",
        step_snapshots=[("ACTION1", step)],
        telemetry={"steps_since_last_reset": 3},
    )
    assert (state_dir / "state.json").exists()
    assert (state_dir / "current_grid.npy").exists()
    assert (state_dir / "all_grids.npy").exists()

    md_path = tmp_path / "game-state.md"
    game_state.write_game_state(
        md_path,
        frame,
        pixels,
        game_id="ls20",
        last_action="status",
        script_output="",
        error="",
        step_snapshots=[("ACTION1", step)],
        pre_turn_pixels=pixels,
    )
    assert "## Current State" in md_path.read_text()

