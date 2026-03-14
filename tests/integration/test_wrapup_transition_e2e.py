from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np

import harness_wrapup
from arc_model_runtime.utils import sync_workspace_level_view, write_analysis_level_pin
from tools.arc_repl_session_artifacts import _write_level_turn_files


def _rows(grid: np.ndarray) -> list[str]:
    return ["".join(f"{int(v):X}" for v in row) for row in grid]


def test_level_transition_end_to_end_release_path(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "wrapup-e2e"
    agent_game_dir = run_dir / "agent" / "game_ls20"
    arc_state_dir = run_dir / "supervisor" / "arc"
    super_dir = run_dir / "super"
    agent_game_dir.mkdir(parents=True, exist_ok=True)
    arc_state_dir.mkdir(parents=True, exist_ok=True)
    super_dir.mkdir(parents=True, exist_ok=True)
    (agent_game_dir / "play_lib.py").write_text("# stub\n")

    before_grid = np.array([[0, 0, 0, 0], [0, 0, 0, 0]], dtype=np.int8)
    after_grid = np.array([[2, 2, 2, 2], [2, 2, 2, 2]], dtype=np.int8)
    action_record = {
        "action_index": 1,
        "tool_turn": 7,
        "step_in_call": 1,
        "call_action": "exec",
        "action_name": "ACTION1",
        "action_data": {},
        "recorded_at_utc": "2026-03-13T20:00:00Z",
        "state_before": {"state": "NOT_FINISHED", "grid_hex_rows": _rows(before_grid)},
        "state_after": {"state": "NOT_FINISHED", "grid_hex_rows": _rows(after_grid)},
        "level_before": 1,
        "level_after": 2,
        "levels_completed_before": 0,
        "levels_completed_after": 1,
    }
    session = SimpleNamespace(
        play_lib_file=agent_game_dir / "play_lib.py",
        arc_dir=arc_state_dir,
        game_id="ls20",
        turn=7,
        frame=SimpleNamespace(levels_completed=1, state=SimpleNamespace(value="NOT_FINISHED")),
        cwd=run_dir,
        deps=SimpleNamespace(
            build_aggregate_diff_record=lambda **_kwargs: {
                "changed_pixels": 8,
                "suppressed_cross_level_diff": False,
                "aggregate_baseline_step": None,
            }
        ),
        action_history=SimpleNamespace(records=[action_record]),
        latest_turn_artifacts=None,
    )

    _write_level_turn_files(
        session=session,
        action_label="ACTION1",
        state_before_action="NOT_FINISHED",
        levels_before_action=0,
        pre_pixels=before_grid,
        step_snapshots=[],
        step_results=[],
        final_pixels=after_grid,
        trace_path=run_dir / "trace.json",
    )

    artifacts_root = arc_state_dir / "game_artifacts" / "game_ls20"
    level_2 = artifacts_root / "level_2"
    level_2.mkdir(parents=True, exist_ok=True)
    (level_2 / "initial_state.hex").write_text("2222\n2222\n", encoding="utf-8")
    (level_2 / "current_state.hex").write_text("2222\n2222\n", encoding="utf-8")

    (arc_state_dir / "state.json").write_text(
        json.dumps({"current_level": 2, "levels_completed": 1}, indent=2) + "\n",
        encoding="utf-8",
    )

    previous_arc_state_dir = os.environ.get("ARC_STATE_DIR")
    os.environ["ARC_STATE_DIR"] = str(arc_state_dir)
    try:
        write_analysis_level_pin(agent_game_dir, level=1, phase="pending_theory", reason="level_complete")
        visible = sync_workspace_level_view(agent_game_dir, game_id="ls20", frontier_level=2)
    finally:
        if previous_arc_state_dir is None:
            os.environ.pop("ARC_STATE_DIR", None)
        else:
            os.environ["ARC_STATE_DIR"] = previous_arc_state_dir

    assert visible == 1
    assert json.loads((agent_game_dir / "level_current" / "meta.json").read_text())["level"] == 1
    assert (agent_game_dir / "level_current" / "current_state.hex").read_text().splitlines() == _rows(before_grid)
    status_before = json.loads((agent_game_dir / "level_current" / "analysis_level_status.json").read_text())
    assert status_before["analysis_level_pinned"] is True
    assert status_before["frontier_hidden_by_pin"] is True
    transition_before = json.loads((agent_game_dir / "level_current" / "level_transition.json").read_text())
    assert transition_before["analysis_level_boundary_redacted"] is True

    (agent_game_dir / "component_coverage.json").write_text(
        json.dumps({"status": "pass"}, indent=2) + "\n",
        encoding="utf-8",
    )
    (agent_game_dir / "current_compare.json").write_text(
        json.dumps({"all_match": True, "level": 1}, indent=2) + "\n",
        encoding="utf-8",
    )
    (agent_game_dir / "model_status.json").write_text(
        json.dumps(
            {
                "state": {
                    "current_level": 1,
                    "levels_completed": 0,
                    "available_model_levels": [1],
                }
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (super_dir / "state.json").write_text(
        json.dumps(
            {
                "activeMode": "theory",
                "activeTransitionPayload": {"wrapup_certified": "true", "wrapup_level": "1"},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    runtime = SimpleNamespace(
        run_dir=run_dir,
        arc_state_dir=arc_state_dir,
        active_game_id="ls20",
        args=SimpleNamespace(game_id="ls20"),
        active_agent_dir=lambda: agent_game_dir,
        load_state=lambda: json.loads((arc_state_dir / "state.json").read_text()),
        refresh_dynamic_super_env=lambda: None,
        log=lambda _msg: None,
    )

    harness_wrapup.certify_or_block_wrapup_transition_impl(runtime)

    assert not (agent_game_dir / ".analysis_level_pin.json").exists()
    meta_after = json.loads((agent_game_dir / "level_current" / "meta.json").read_text())
    assert meta_after["level"] == 2
    assert meta_after["analysis_level_pinned"] is False
    status_after = json.loads((agent_game_dir / "level_current" / "analysis_level_status.json").read_text())
    assert status_after["analysis_level_pinned"] is False
    assert status_after["frontier_hidden_by_pin"] is False
    assert status_after["next_allowed_operation"] == "continue_visible_level"
    assert (agent_game_dir / "level_current" / "current_state.hex").read_text().splitlines() == [
        "2222",
        "2222",
    ]
