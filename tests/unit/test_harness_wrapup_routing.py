from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import harness_wrapup


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


def _write_level_artifacts(level_dir: Path, *, rows: str, compare_level: int | None = None) -> None:
    level_dir.mkdir(parents=True, exist_ok=True)
    (level_dir / "initial_state.hex").write_text(rows, encoding="utf-8")
    (level_dir / "current_state.hex").write_text(rows, encoding="utf-8")
    if compare_level is not None:
        compare_dir = level_dir / "sequence_compare"
        compare_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": "arc.compare.current.v1",
            "status": "ok",
            "level": int(compare_level),
            "all_match": False,
            "compared_sequences": 1,
            "diverged_sequences": 1,
            "reports": [{"sequence_id": "seq_0001", "matched": False, "report_file": "analysis_level/sequence_compare/seq_0001.md"}],
        }
        (compare_dir / "current_compare.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        (compare_dir / "current_compare.md").write_text("# Current Compare\n", encoding="utf-8")
        (compare_dir / "seq_0001.md").write_text("# seq_0001\n", encoding="utf-8")


def test_wrapup_transition_materializes_explicit_analysis_level_surface(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "wrapup-hold"
    game_dir = run_dir / "agent" / "game_ls20"
    arc_state_dir = run_dir / "supervisor" / "arc"
    super_dir = run_dir / "super"
    level1 = arc_state_dir / "game_artifacts" / "game_ls20" / "level_1"
    level2 = arc_state_dir / "game_artifacts" / "game_ls20" / "level_2"
    game_dir.mkdir(parents=True, exist_ok=True)
    arc_state_dir.mkdir(parents=True, exist_ok=True)
    super_dir.mkdir(parents=True, exist_ok=True)
    _write_level_artifacts(level1, rows="0000\n", compare_level=1)
    _write_level_artifacts(level2, rows="1111\n")
    (arc_state_dir / "state.json").write_text(json.dumps({"current_level": 2}, indent=2) + "\n")
    (super_dir / "state.json").write_text(
        json.dumps(
            {
                "activeMode": "theory",
                "activeProcessStage": "post_completion_cleanup",
                "activeTaskProfile": "level_1_wrapup",
                "activeTransitionPayload": {
                    "analysis_scope": "wrapup",
                    "analysis_level": "1",
                    "frontier_level": "2",
                },
            },
            indent=2,
        )
        + "\n"
    )

    runtime = _make_runtime(run_dir, arc_state_dir, game_dir)

    harness_wrapup.certify_or_block_wrapup_transition_impl(runtime)

    analysis_state = json.loads((game_dir / "analysis_state.json").read_text())
    assert analysis_state["analysis_scope"] == "wrapup"
    assert analysis_state["analysis_level"] == 1
    assert analysis_state["frontier_level"] == 2
    level_current_meta = json.loads((game_dir / "level_current" / "meta.json").read_text())
    assert level_current_meta["level"] == 2
    analysis_meta = json.loads((game_dir / "analysis_level" / "meta.json").read_text())
    assert analysis_meta["level"] == 1
    root_compare = json.loads((game_dir / "current_compare.json").read_text())
    assert root_compare["level"] == 1


def test_wrapup_transition_clears_explicit_analysis_level_surface_when_supervisor_routes_out(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "runs" / "wrapup-release-on-route"
    game_dir = run_dir / "agent" / "game_ls20"
    arc_state_dir = run_dir / "supervisor" / "arc"
    super_dir = run_dir / "super"
    level1 = arc_state_dir / "game_artifacts" / "game_ls20" / "level_1"
    level2 = arc_state_dir / "game_artifacts" / "game_ls20" / "level_2"
    game_dir.mkdir(parents=True, exist_ok=True)
    arc_state_dir.mkdir(parents=True, exist_ok=True)
    super_dir.mkdir(parents=True, exist_ok=True)
    _write_level_artifacts(level1, rows="0000\n", compare_level=1)
    _write_level_artifacts(level2, rows="1111\n")
    (arc_state_dir / "state.json").write_text(json.dumps({"current_level": 2}, indent=2) + "\n")
    (super_dir / "state.json").write_text(
        json.dumps(
            {
                "activeMode": "explore_only",
                "activeProcessStage": "frontier_probe",
                "activeTransitionPayload": {
                    "analysis_scope": "frontier",
                    "analysis_level": "2",
                    "frontier_level": "2",
                },
            },
            indent=2,
        )
        + "\n"
    )
    (game_dir / ".analysis_level_pin.json").write_text(json.dumps({"level": 1}, indent=2) + "\n")

    runtime = _make_runtime(run_dir, arc_state_dir, game_dir)

    harness_wrapup.certify_or_block_wrapup_transition_impl(runtime)

    analysis_state = json.loads((game_dir / "analysis_state.json").read_text())
    assert analysis_state["analysis_level"] == 2
    assert not (game_dir / ".analysis_level_pin.json").exists()
    assert not (game_dir / "analysis_level").exists()
    level_current_meta = json.loads((game_dir / "level_current" / "meta.json").read_text())
    assert level_current_meta["level"] == 2
