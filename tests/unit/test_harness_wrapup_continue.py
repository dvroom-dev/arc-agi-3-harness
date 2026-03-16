from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import harness_wrapup


def _write_level_current_surface(game_dir: Path, *, level: int) -> None:
    level_current = game_dir / "level_current"
    level_current.mkdir(parents=True, exist_ok=True)
    (level_current / "meta.json").write_text(
        json.dumps({"level": level, "analysis_level_pinned": True}, indent=2) + "\n"
    )
    (level_current / "analysis_level_status.json").write_text(
        json.dumps(
            {
                "visible_level": level,
                "analysis_level_pinned": True,
                "frontier_hidden_by_pin": True,
                "next_allowed_operation": "finalize_pinned_level",
            },
            indent=2,
        )
        + "\n"
    )
    (level_current / "level_transition.json").write_text(
        json.dumps({"analysis_level_boundary_redacted": True}, indent=2) + "\n"
    )


def _make_runtime(run_dir: Path, arc_state_dir: Path, game_dir: Path):
    return SimpleNamespace(
        run_dir=run_dir,
        arc_state_dir=arc_state_dir,
        active_game_id="ls20",
        args=SimpleNamespace(game_id="ls20"),
        active_agent_dir=lambda: game_dir,
        load_state=lambda: json.loads((arc_state_dir / "state.json").read_text()),
        refresh_dynamic_super_env=lambda: None,
        log=lambda _msg: None,
    )


def test_repair_stale_wrapup_mode_rewrites_pre_pin_frontier_mode(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "wrapup-repair"
    game_dir = run_dir / "agent" / "game_ls20"
    arc_state_dir = run_dir / "supervisor" / "arc"
    super_dir = run_dir / "super"
    game_dir.mkdir(parents=True, exist_ok=True)
    arc_state_dir.mkdir(parents=True, exist_ok=True)
    super_dir.mkdir(parents=True, exist_ok=True)
    (arc_state_dir / "state.json").write_text(json.dumps({"current_level": 2}, indent=2) + "\n")
    (super_dir / "state.json").write_text(
        json.dumps(
            {
                "activeMode": "explore_and_solve",
                "activeModePayload": {"user_message": "old frontier probe"},
                "activeTransitionPayload": {},
                "updatedAt": "2026-03-16T00:07:54.604Z",
            },
            indent=2,
        )
        + "\n"
    )
    (game_dir / ".analysis_level_pin.json").write_text(
        json.dumps(
            {
                "level": 1,
                "phase": "pending_theory",
                "updated_at_utc": "2026-03-16T00:08:15.499448+00:00",
            },
            indent=2,
        )
        + "\n"
    )
    (game_dir / "component_coverage.json").write_text(json.dumps({"status": "fail"}, indent=2) + "\n")
    (game_dir / "current_compare.json").write_text(json.dumps({"all_match": False, "level": 1}, indent=2) + "\n")
    (game_dir / "model_status.json").write_text(
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
        + "\n"
    )
    _write_level_current_surface(game_dir, level=1)

    runtime = _make_runtime(run_dir, arc_state_dir, game_dir)

    repaired = harness_wrapup.repair_stale_wrapup_mode_impl(runtime)

    assert repaired == "explore_and_solve"
    repaired_state = json.loads((super_dir / "state.json").read_text())
    assert repaired_state["activeMode"] == "theory"
    assert repaired_state["activeModePayload"] == {}
    assert repaired_state["activeTransitionPayload"] == {}
