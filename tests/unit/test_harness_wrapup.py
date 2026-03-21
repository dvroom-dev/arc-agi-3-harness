from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import harness_wrapup


def _write_level_current_surface(
    game_dir: Path,
    *,
    level: int,
    pinned: bool,
    initial_rows: str | None = None,
) -> None:
    level_current = game_dir / "level_current"
    level_current.mkdir(parents=True, exist_ok=True)
    (level_current / "meta.json").write_text(
        json.dumps({"level": level, "analysis_level_pinned": pinned}, indent=2) + "\n"
    )
    if initial_rows is not None:
        (level_current / "initial_state.hex").write_text(initial_rows)
    if pinned:
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


def test_wrapup_transition_blocks_frontier_modes_until_ready(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "wrapup-block"
    game_dir = run_dir / "agent" / "game_ls20"
    arc_state_dir = run_dir / "supervisor" / "arc"
    super_dir = run_dir / "super"
    artifacts_level2 = arc_state_dir / "game_artifacts" / "game_ls20" / "level_2"
    game_dir.mkdir(parents=True, exist_ok=True)
    arc_state_dir.mkdir(parents=True, exist_ok=True)
    super_dir.mkdir(parents=True, exist_ok=True)
    artifacts_level2.mkdir(parents=True, exist_ok=True)
    (arc_state_dir / "state.json").write_text(json.dumps({"current_level": 2}, indent=2) + "\n")
    (super_dir / "state.json").write_text(json.dumps({"activeMode": "solve_model"}, indent=2) + "\n")
    (game_dir / ".analysis_level_pin.json").write_text(
        json.dumps({"level": 1, "phase": "pending_theory"}, indent=2) + "\n"
    )
    (game_dir / "component_coverage.json").write_text(json.dumps({"status": "fail"}, indent=2) + "\n")
    (game_dir / "current_compare.json").write_text(json.dumps({"all_match": False, "level": 1}, indent=2) + "\n")
    _write_level_current_surface(game_dir, level=1, pinned=True)
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

    runtime = _make_runtime(run_dir, arc_state_dir, game_dir)

    with pytest.raises(RuntimeError, match="cannot leave solved-level wrap-up"):
        harness_wrapup.certify_or_block_wrapup_transition_impl(runtime)




def test_wrapup_transition_clears_pin_and_restores_frontier_view_when_ready(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "wrapup-certify"
    game_dir = run_dir / "agent" / "game_ls20"
    arc_state_dir = run_dir / "supervisor" / "arc"
    super_dir = run_dir / "super"
    level1 = arc_state_dir / "game_artifacts" / "game_ls20" / "level_1"
    level2 = arc_state_dir / "game_artifacts" / "game_ls20" / "level_2"
    game_dir.mkdir(parents=True, exist_ok=True)
    arc_state_dir.mkdir(parents=True, exist_ok=True)
    super_dir.mkdir(parents=True, exist_ok=True)
    level1.mkdir(parents=True, exist_ok=True)
    level2.mkdir(parents=True, exist_ok=True)
    (level1 / "initial_state.hex").write_text("0000\n")
    (level2 / "initial_state.hex").write_text("1111\n")
    (arc_state_dir / "state.json").write_text(json.dumps({"current_level": 2}, indent=2) + "\n")
    (super_dir / "state.json").write_text(json.dumps({"activeMode": "solve_model"}, indent=2) + "\n")
    (game_dir / ".analysis_level_pin.json").write_text(
        json.dumps({"level": 1, "phase": "pending_theory"}, indent=2) + "\n"
    )
    (game_dir / "component_coverage.json").write_text(json.dumps({"status": "pass"}, indent=2) + "\n")
    (game_dir / "current_compare.json").write_text(
        json.dumps(
            {
                "all_match": True,
                "level": 1,
                "compare_payload": {
                    "analysis_level_pinned": True,
                    "analysis_level_pin": {"level": 1, "phase": "pending_theory"},
                },
            },
            indent=2,
        )
        + "\n"
    )
    (game_dir / "current_compare.md").write_text("# stale pinned compare\n", encoding="utf-8")
    _write_level_current_surface(game_dir, level=1, pinned=True, initial_rows="0000\n")
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

    refreshed: list[str] = []
    runtime = _make_runtime(run_dir, arc_state_dir, game_dir)
    runtime.refresh_dynamic_super_env = lambda: refreshed.append("yes")

    harness_wrapup.certify_or_block_wrapup_transition_impl(runtime)

    assert not (game_dir / ".analysis_level_pin.json").exists()
    meta = json.loads((game_dir / "level_current" / "meta.json").read_text())
    assert meta["level"] == 2
    assert meta["analysis_level_pinned"] is False
    compare_after = json.loads((game_dir / "current_compare.json").read_text())
    assert compare_after["status"] == "no_sequences_yet"
    assert compare_after["level"] == 2
    assert refreshed == ["yes"]


def test_wrapup_transition_can_release_directly_into_theory_when_ready(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "wrapup-certify-theory"
    game_dir = run_dir / "agent" / "game_ls20"
    arc_state_dir = run_dir / "supervisor" / "arc"
    super_dir = run_dir / "super"
    level1 = arc_state_dir / "game_artifacts" / "game_ls20" / "level_1"
    level2 = arc_state_dir / "game_artifacts" / "game_ls20" / "level_2"
    game_dir.mkdir(parents=True, exist_ok=True)
    arc_state_dir.mkdir(parents=True, exist_ok=True)
    super_dir.mkdir(parents=True, exist_ok=True)
    level1.mkdir(parents=True, exist_ok=True)
    level2.mkdir(parents=True, exist_ok=True)
    (level1 / "initial_state.hex").write_text("0000\n")
    (level2 / "initial_state.hex").write_text("1111\n")
    (arc_state_dir / "state.json").write_text(json.dumps({"current_level": 2}, indent=2) + "\n")
    (super_dir / "state.json").write_text(json.dumps({"activeMode": "theory"}, indent=2) + "\n")
    (game_dir / ".analysis_level_pin.json").write_text(
        json.dumps({"level": 1, "phase": "pending_theory"}, indent=2) + "\n"
    )
    (game_dir / "component_coverage.json").write_text(json.dumps({"status": "pass"}, indent=2) + "\n")
    (game_dir / "current_compare.json").write_text(
        json.dumps({"all_match": True, "level": 1}, indent=2) + "\n"
    )
    _write_level_current_surface(game_dir, level=1, pinned=True, initial_rows="0000\n")
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

    refreshed: list[str] = []
    runtime = _make_runtime(run_dir, arc_state_dir, game_dir)
    runtime.refresh_dynamic_super_env = lambda: refreshed.append("yes")

    harness_wrapup.certify_or_block_wrapup_transition_impl(runtime)

    assert not (game_dir / ".analysis_level_pin.json").exists()
    meta = json.loads((game_dir / "level_current" / "meta.json").read_text())
    assert meta["level"] == 2
    assert meta["analysis_level_pinned"] is False
    assert refreshed == ["yes"]


def test_wrapup_transition_blocks_when_compare_level_does_not_match_pin(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "wrapup-compare-level-mismatch"
    game_dir = run_dir / "agent" / "game_ls20"
    arc_state_dir = run_dir / "supervisor" / "arc"
    super_dir = run_dir / "super"
    game_dir.mkdir(parents=True, exist_ok=True)
    arc_state_dir.mkdir(parents=True, exist_ok=True)
    super_dir.mkdir(parents=True, exist_ok=True)
    (arc_state_dir / "state.json").write_text(json.dumps({"current_level": 2}, indent=2) + "\n")
    (super_dir / "state.json").write_text(json.dumps({"activeMode": "solve_model"}, indent=2) + "\n")
    (game_dir / ".analysis_level_pin.json").write_text(
        json.dumps({"level": 1, "phase": "pending_theory"}, indent=2) + "\n"
    )
    (game_dir / "component_coverage.json").write_text(json.dumps({"status": "pass"}, indent=2) + "\n")
    (game_dir / "current_compare.json").write_text(
        json.dumps({"all_match": True, "level": 2}, indent=2) + "\n"
    )
    _write_level_current_surface(game_dir, level=1, pinned=True)
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

    runtime = _make_runtime(run_dir, arc_state_dir, game_dir)

    with pytest.raises(RuntimeError, match="wrap-up surface validation failed"):
        harness_wrapup.certify_or_block_wrapup_transition_impl(runtime)


def test_wrapup_surface_validation_blocks_frontier_leakage_while_pin_is_active(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "wrapup-surface-leak"
    game_dir = run_dir / "agent" / "game_ls20"
    arc_state_dir = run_dir / "supervisor" / "arc"
    super_dir = run_dir / "super"
    game_dir.mkdir(parents=True, exist_ok=True)
    arc_state_dir.mkdir(parents=True, exist_ok=True)
    super_dir.mkdir(parents=True, exist_ok=True)
    (arc_state_dir / "state.json").write_text(json.dumps({"current_level": 2}, indent=2) + "\n")
    (super_dir / "state.json").write_text(json.dumps({"activeMode": "code_model"}, indent=2) + "\n")
    (game_dir / ".analysis_level_pin.json").write_text(
        json.dumps({"level": 1, "phase": "pending_theory"}, indent=2) + "\n"
    )
    (game_dir / "component_coverage.json").write_text(json.dumps({"status": "pass"}, indent=2) + "\n")
    (game_dir / "current_compare.json").write_text(
        json.dumps({"all_match": False, "level": 1}, indent=2) + "\n"
    )
    (game_dir / "level_current").mkdir(parents=True, exist_ok=True)
    (game_dir / "level_current" / "meta.json").write_text(
        json.dumps({"level": 1, "frontier_level": 2, "analysis_level_pinned": True}, indent=2) + "\n"
    )
    (game_dir / "model_status.json").write_text(
        json.dumps(
            {
                "state": {
                    "current_level": 2,
                    "levels_completed": 1,
                    "available_model_levels": [1, 2],
                }
            },
            indent=2,
        )
        + "\n"
    )

    runtime = SimpleNamespace(
        run_dir=run_dir,
        arc_state_dir=arc_state_dir,
        active_game_id="ls20",
        args=SimpleNamespace(game_id="ls20"),
        active_agent_dir=lambda: game_dir,
        load_state=lambda: json.loads((arc_state_dir / "state.json").read_text()),
        refresh_dynamic_super_env=lambda: None,
        log=lambda _msg: None,
    )

    with pytest.raises(RuntimeError, match="wrap-up surface validation failed"):
        harness_wrapup.validate_wrapup_surfaces_impl(runtime)


def test_wrapup_surface_validation_accepts_pinned_level_consistency(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "wrapup-surface-ok"
    game_dir = run_dir / "agent" / "game_ls20"
    arc_state_dir = run_dir / "supervisor" / "arc"
    super_dir = run_dir / "super"
    game_dir.mkdir(parents=True, exist_ok=True)
    arc_state_dir.mkdir(parents=True, exist_ok=True)
    super_dir.mkdir(parents=True, exist_ok=True)
    (arc_state_dir / "state.json").write_text(json.dumps({"current_level": 2}, indent=2) + "\n")
    (super_dir / "state.json").write_text(json.dumps({"activeMode": "code_model"}, indent=2) + "\n")
    (game_dir / ".analysis_level_pin.json").write_text(
        json.dumps({"level": 1, "phase": "pending_theory"}, indent=2) + "\n"
    )
    (game_dir / "component_coverage.json").write_text(json.dumps({"status": "pass"}, indent=2) + "\n")
    (game_dir / "current_compare.json").write_text(
        json.dumps({"all_match": False, "level": 1}, indent=2) + "\n"
    )
    _write_level_current_surface(game_dir, level=1, pinned=True)
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

    runtime = _make_runtime(run_dir, arc_state_dir, game_dir)

    harness_wrapup.validate_wrapup_surfaces_impl(runtime)


def test_wrapup_surface_validation_rejects_stale_visible_compare_surface(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "wrapup-stale-visible-compare"
    game_dir = run_dir / "agent" / "game_ls20"
    arc_state_dir = run_dir / "supervisor" / "arc"
    super_dir = run_dir / "super"
    game_dir.mkdir(parents=True, exist_ok=True)
    arc_state_dir.mkdir(parents=True, exist_ok=True)
    super_dir.mkdir(parents=True, exist_ok=True)
    (arc_state_dir / "state.json").write_text(json.dumps({"current_level": 2}, indent=2) + "\n")
    (super_dir / "state.json").write_text(json.dumps({"activeMode": "code_model"}, indent=2) + "\n")
    (game_dir / ".analysis_level_pin.json").write_text(
        json.dumps({"level": 1, "phase": "pending_code_model"}, indent=2) + "\n"
    )
    (game_dir / "component_coverage.json").write_text(json.dumps({"status": "pass"}, indent=2) + "\n")
    (game_dir / "current_compare.json").write_text(
        json.dumps(
            {
                "all_match": True,
                "level": 1,
                "compared_sequences": 1,
                "diverged_sequences": 0,
                "reports": [
                    {"sequence_id": "seq_0001", "matched": True, "actions_compared": 26, "divergence_step": None}
                ],
            },
            indent=2,
        )
        + "\n"
    )
    _write_level_current_surface(game_dir, level=1, pinned=True)
    visible_compare_dir = game_dir / "level_current" / "sequence_compare"
    visible_compare_dir.mkdir(parents=True, exist_ok=True)
    (visible_compare_dir / "current_compare.json").write_text(
        json.dumps(
            {
                "all_match": False,
                "level": 1,
                "compared_sequences": 1,
                "diverged_sequences": 1,
                "reports": [
                    {"sequence_id": "seq_0001", "matched": False, "actions_compared": 1, "divergence_step": 1}
                ],
            },
            indent=2,
        )
        + "\n"
    )
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

    runtime = _make_runtime(run_dir, arc_state_dir, game_dir)

    with pytest.raises(RuntimeError, match="current_compare mismatch|reports diverged"):
        harness_wrapup.validate_wrapup_surfaces_impl(runtime)


def test_wrapup_transition_releases_frontier_when_pinned_evidence_is_accounted_for(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "wrapup-certify-missing-payload"
    game_dir = run_dir / "agent" / "game_ls20"
    arc_state_dir = run_dir / "supervisor" / "arc"
    super_dir = run_dir / "super"
    level1 = arc_state_dir / "game_artifacts" / "game_ls20" / "level_1"
    level2 = arc_state_dir / "game_artifacts" / "game_ls20" / "level_2"
    game_dir.mkdir(parents=True, exist_ok=True)
    arc_state_dir.mkdir(parents=True, exist_ok=True)
    super_dir.mkdir(parents=True, exist_ok=True)
    level1.mkdir(parents=True, exist_ok=True)
    level2.mkdir(parents=True, exist_ok=True)
    (level1 / "initial_state.hex").write_text("0000\n")
    (level2 / "initial_state.hex").write_text("1111\n")
    (arc_state_dir / "state.json").write_text(json.dumps({"current_level": 2}, indent=2) + "\n")
    (super_dir / "state.json").write_text(json.dumps({"activeMode": "solve_model"}, indent=2) + "\n")
    (game_dir / ".analysis_level_pin.json").write_text(
        json.dumps({"level": 1, "phase": "pending_theory"}, indent=2) + "\n"
    )
    (game_dir / "component_coverage.json").write_text(json.dumps({"status": "pass"}, indent=2) + "\n")
    (game_dir / "current_compare.json").write_text(
        json.dumps({"all_match": True, "level": 1}, indent=2) + "\n"
    )
    _write_level_current_surface(game_dir, level=1, pinned=True, initial_rows="0000\n")
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

    runtime = _make_runtime(run_dir, arc_state_dir, game_dir)

    harness_wrapup.certify_or_block_wrapup_transition_impl(runtime)

    assert not (game_dir / ".analysis_level_pin.json").exists()
    meta = json.loads((game_dir / "level_current" / "meta.json").read_text())
    assert meta["level"] == 2
    assert meta["analysis_level_pinned"] is False
