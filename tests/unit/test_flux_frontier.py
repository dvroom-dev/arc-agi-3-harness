from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_module(name: str, relative_path: str):
    module_path = Path(__file__).resolve().parents[2] / relative_path
    spec = importlib.util.spec_from_file_location(name, module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _ready_evidence_bundle(tmp_path: Path, workspace_name: str) -> Path:
    bundle_root = tmp_path / "flux" / "evidence_bundles" / "bundle_x"
    bundle_workspace = bundle_root / "workspace" / workspace_name
    bundle_state_dir = bundle_root / "arc_state"
    bundle_workspace.mkdir(parents=True, exist_ok=True)
    bundle_state_dir.mkdir(parents=True, exist_ok=True)
    (bundle_root / "manifest.json").write_text(
        json.dumps(
            {
                "workspace_dir": str(bundle_workspace),
                "arc_state_dir": str(bundle_state_dir),
                "bundle_completeness": {
                    "frontier_level": 1,
                    "has_level_sequences": True,
                    "has_frontier_initial_state": True,
                    "has_frontier_sequences": True,
                    "has_compare_surface": True,
                    "status": "ready_for_compare",
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return bundle_root


def test_check_model_annotates_frontier_level_from_matched_sequences(tmp_path: Path, monkeypatch) -> None:
    _load_module("common", "scripts/flux/common.py")
    check_model = _load_module("flux_check_model_frontier_test", "scripts/flux/check_model.py")
    model_workspace = tmp_path / "agent" / "game_ls20"
    sequence_dir = model_workspace / "level_1" / "sequences"
    sequence_dir.mkdir(parents=True, exist_ok=True)
    sequence_path = sequence_dir / "seq_0007.json"
    sequence_path.write_text(
        json.dumps({
                "level": 1,
                "sequence_id": "seq_0007",
                "actions": [{
                    "action_index": 99,
                    "action_name": "ACTION1",
                    "level_before": 1,
                    "level_after": 2,
                    "levels_completed_before": 0,
                    "levels_completed_after": 1,
                    "level_complete_after": True,
                }],
            }, indent=2),
            encoding="utf-8",
        )
    payload = json.loads(sequence_path.read_text())
    assert check_model._sequence_frontier_level(payload) == 2


def test_check_model_compares_all_visible_sequence_levels_and_requires_all_to_match(tmp_path: Path, monkeypatch) -> None:
    _load_module("common", "scripts/flux/common.py")
    check_model = _load_module("flux_check_model_all_levels_test", "scripts/flux/check_model.py")
    model_workspace = tmp_path / "agent" / "game_ls20"
    for level in (1, 2):
        (model_workspace / f"level_{level}" / "sequences").mkdir(parents=True, exist_ok=True)
        (model_workspace / f"level_{level}" / "sequences" / "seq_0001.json").write_text(
            json.dumps({"level": level, "sequence_id": "seq_0001", "actions": []}, indent=2),
            encoding="utf-8",
        )
    (model_workspace / "level_current").mkdir(parents=True, exist_ok=True)
    (model_workspace / "level_current" / "meta.json").write_text(json.dumps({"level": 2}), encoding="utf-8")
    (model_workspace / "model.py").write_text("# stub\n", encoding="utf-8")

    calls: list[tuple[int | None, bool]] = []

    def fake_run_compare(_workspace, _meta, _env, frontier_level=None, *, include_reset_ended=False):
        calls.append((frontier_level, include_reset_ended))
        if frontier_level == 1:
            return 0, {
                "level": 1,
                "all_match": True,
                "requested_sequences": 1,
                "eligible_sequences": 1,
                "compared_sequences": 1,
                "diverged_sequences": 0,
                "reports": [{"level": 1, "sequence_id": "seq_0001", "matched": True}],
            }
        return 0, {
            "level": 2,
            "all_match": False,
            "requested_sequences": 1,
            "eligible_sequences": 1,
            "compared_sequences": 1,
            "diverged_sequences": 1,
            "reports": [{"level": 2, "sequence_id": "seq_0001", "matched": False, "divergence_step": 3, "divergence_reason": "after_state_mismatch"}],
        }

    bundle_root = _ready_evidence_bundle(tmp_path, "game_ls20")
    monkeypatch.setattr(check_model, "read_json_stdin", lambda: {"workspaceRoot": str(tmp_path), "modelOutput": {}, "evidenceBundlePath": str(bundle_root)})
    monkeypatch.setattr(check_model, "load_runtime_meta", lambda _workspace: {
        "model_workspace_dir": str(model_workspace),
        "run_config_dir": str(tmp_path / "config"),
        "run_bin_dir": str(tmp_path / "bin"),
        "game_id": "ls20",
    })
    monkeypatch.setattr(check_model, "_run_compare", fake_run_compare)
    payloads: list[dict] = []
    monkeypatch.setattr(check_model, "write_json_stdout", lambda payload: payloads.append(payload))

    check_model.main()

    assert calls == [(1, True), (2, True)]
    assert payloads
    assert payloads[0]["accepted"] is False
    assert payloads[0]["compare_payload"]["requested_sequences"] == 2
    assert len(payloads[0]["compare_payload"]["reports"]) == 2
    assert payloads[0]["compare_payload"]["covered_sequence_ids"] == ["level_1:seq_0001"]
    assert payloads[0]["message"] == "compare mismatch at level 2 sequence seq_0001 step 3: after_state_mismatch"


def test_observe_evidence_marks_artifact_handoff_incomplete_when_state_outpaces_visible_actions(tmp_path: Path, monkeypatch) -> None:
    _load_module("common", "scripts/flux/common.py")
    _load_module("bundles", "scripts/flux/bundles.py")
    observe = _load_module("flux_observe_evidence_incomplete_test", "scripts/flux/observe_evidence.py")
    workspace_root = tmp_path / "run"
    solver_dir = workspace_root / "flux_instances" / "attempt_x" / "agent" / "game_ls20" / "level_2" / "sequences" / "seq_0002"
    state_dir = workspace_root / "flux_instances" / "attempt_x" / "supervisor" / "arc"
    (solver_dir / "actions" / "step_0018_action_000056_action2").mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    (solver_dir.parent / "seq_0002.json").write_text(
        json.dumps({
            "level": 2,
            "sequence_id": "seq_0002",
            "actions": [{"action_index": 56, "files": {"meta_json": "sequences/seq_0002/actions/step_0018_action_000056_action2/meta.json"}}],
        }, indent=2),
        encoding="utf-8",
    )
    (solver_dir / "actions" / "step_0018_action_000056_action2" / "meta.json").write_text("{}", encoding="utf-8")
    (state_dir / "state.json").write_text(
        json.dumps({"current_level": 2, "levels_completed": 1, "state": "NOT_FINISHED", "total_steps": 125, "current_attempt_steps": 17}, indent=2),
        encoding="utf-8",
    )
    (state_dir / "tool-engine-history.json").write_text(json.dumps({"events": [1] * 130}) + "\n", encoding="utf-8")
    (state_dir / "action-history.json").write_text(json.dumps([{}] * 130) + "\n", encoding="utf-8")
    monkeypatch.setattr(observe, "read_json_stdin", lambda: {
        "workspaceRoot": str(workspace_root),
        "attemptId": "attempt_x",
        "instance": {"instance_id": "attempt_x", "metadata": {"state_dir": str(state_dir), "solver_dir": str(solver_dir.parent.parent.parent)}},
    })
    monkeypatch.setattr(observe, "load_runtime_meta", lambda _workspace: {"solver_template_dir": str(workspace_root / "templates" / "game_ls20")})
    monkeypatch.setattr(observe, "materialize_attempt_snapshot", lambda *args, **kwargs: {"snapshot_id": "snap_x", "snapshot_path": str(workspace_root / "flux" / "attempt_snapshots" / "snap_x"), "workspace_dir": str(Path(kwargs["solver_dir"])), "arc_state_dir": str(Path(kwargs["state_dir"])), "solver_dir_name": kwargs["workspace_dir_name"]})
    monkeypatch.setattr(observe, "materialize_evidence_bundle_from_snapshot", lambda *args, **kwargs: {"bundle_id": "bundle_x", "bundle_path": str(workspace_root / "flux" / "bundle_x"), "bundle_completeness": {"frontier_level": 2, "has_compare_surface": False, "status": "incomplete_artifacts"}})
    payloads: list[dict] = []
    monkeypatch.setattr(observe, "write_json_stdout", lambda payload: payloads.append(payload))

    observe.main()

    assert payloads
    evidence = payloads[0]["evidence"][0]
    assert evidence["artifact_handoff_incomplete"]["reported_action_count"] == 130
    assert evidence["artifact_handoff_incomplete"]["visible_action_count"] == 56
    assert "evidence_bundle_id" not in evidence


def test_observe_evidence_does_not_treat_reset_records_as_missing_visible_actions(tmp_path: Path, monkeypatch) -> None:
    _load_module("common", "scripts/flux/common.py")
    _load_module("bundles", "scripts/flux/bundles.py")
    observe = _load_module("flux_observe_evidence_reset_filter_test", "scripts/flux/observe_evidence.py")
    workspace_root = tmp_path / "run"
    solver_dir = workspace_root / "flux_instances" / "attempt_x" / "agent" / "game_ls20" / "level_1" / "sequences" / "seq_0001"
    state_dir = workspace_root / "flux_instances" / "attempt_x" / "supervisor" / "arc"
    (solver_dir / "actions" / "step_0008_action_000008_action3").mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    (solver_dir.parent / "seq_0001.json").write_text(
        json.dumps({
            "level": 1,
            "sequence_id": "seq_0001",
            "actions": [{"action_index": 8, "files": {"meta_json": "sequences/seq_0001/actions/step_0008_action_000008_action3/meta.json"}}],
        }, indent=2),
        encoding="utf-8",
    )
    (solver_dir / "actions" / "step_0008_action_000008_action3" / "meta.json").write_text("{}", encoding="utf-8")
    (state_dir / "state.json").write_text(
        json.dumps({"current_level": 1, "levels_completed": 0, "state": "NOT_FINISHED", "total_steps": 8, "current_attempt_steps": 0}, indent=2),
        encoding="utf-8",
    )
    (state_dir / "tool-engine-history.json").write_text(json.dumps({"events": [{"kind": "step"}] * 8 + [{"kind": "reset"}]}) + "\n", encoding="utf-8")
    records = [{"action_index": index + 1, "action_name": "ACTION1"} for index in range(8)]
    records.append({"action_index": 9, "action_name": "RESET_LEVEL", "call_action": "reset_level", "source": "reset_level"})
    (state_dir / "action-history.json").write_text(json.dumps({"records": records}) + "\n", encoding="utf-8")
    monkeypatch.setattr(observe, "read_json_stdin", lambda: {
        "workspaceRoot": str(workspace_root),
        "attemptId": "attempt_x",
        "instance": {"instance_id": "attempt_x", "metadata": {"state_dir": str(state_dir), "solver_dir": str(solver_dir.parent.parent.parent)}},
    })
    monkeypatch.setattr(observe, "load_runtime_meta", lambda _workspace: {"solver_template_dir": str(workspace_root / "templates" / "game_ls20")})
    monkeypatch.setattr(observe, "materialize_attempt_snapshot", lambda *args, **kwargs: {"snapshot_id": "snap_x", "snapshot_path": str(workspace_root / "flux" / "attempt_snapshots" / "snap_x"), "workspace_dir": str(Path(kwargs["solver_dir"])), "arc_state_dir": str(Path(kwargs["state_dir"])), "solver_dir_name": kwargs["workspace_dir_name"]})
    monkeypatch.setattr(observe, "materialize_evidence_bundle_from_snapshot", lambda *args, **kwargs: {"bundle_id": "bundle_x", "bundle_path": str(workspace_root / "flux" / "bundle_x"), "bundle_completeness": {"frontier_level": 1, "has_compare_surface": True, "status": "ready_for_compare"}})
    payloads: list[dict] = []
    monkeypatch.setattr(observe, "write_json_stdout", lambda payload: payloads.append(payload))

    observe.main()

    assert payloads
    evidence = payloads[0]["evidence"][0]
    assert evidence["action_count"] == 8
    assert evidence["reset_action_count"] == 1
    assert "artifact_handoff_incomplete" not in evidence


def test_observe_evidence_uses_canonical_game_artifacts_across_level_transition(tmp_path: Path, monkeypatch) -> None:
    _load_module("common", "scripts/flux/common.py")
    _load_module("bundles", "scripts/flux/bundles.py")
    observe = _load_module("flux_observe_evidence_transition_surface_test", "scripts/flux/observe_evidence.py")
    workspace_root = tmp_path / "run"
    solver_dir = workspace_root / "flux_instances" / "attempt_x" / "agent" / "game_ls20"
    state_dir = workspace_root / "flux_instances" / "attempt_x" / "supervisor" / "arc"
    canonical_dir = state_dir / "game_artifacts" / "game_ls20-abc123" / "level_1" / "sequences" / "seq_0001"
    (solver_dir / "level_current").mkdir(parents=True, exist_ok=True)
    (solver_dir / "level_current" / "meta.json").write_text(json.dumps({"level": 2}), encoding="utf-8")
    (solver_dir / "level_2").mkdir(parents=True, exist_ok=True)
    (solver_dir / "level_2" / "meta.json").write_text(json.dumps({"level": 2}), encoding="utf-8")
    canonical_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    (canonical_dir.parent / "seq_0001.json").write_text(
        json.dumps({
            "level": 1,
            "sequence_id": "seq_0001",
            "actions": [{"action_index": 21, "files": {"meta_json": "sequences/seq_0001/actions/step_0021_action_000021_action1/meta.json"}}],
        }, indent=2),
        encoding="utf-8",
    )
    (canonical_dir / "actions" / "step_0021_action_000021_action1").mkdir(parents=True, exist_ok=True)
    (canonical_dir / "actions" / "step_0021_action_000021_action1" / "meta.json").write_text("{}", encoding="utf-8")
    (state_dir / "state.json").write_text(
        json.dumps({"current_level": 2, "levels_completed": 1, "state": "NOT_FINISHED", "total_steps": 21, "current_attempt_steps": 1}, indent=2),
        encoding="utf-8",
    )
    (state_dir / "tool-engine-history.json").write_text(json.dumps({"events": [{"kind": "step"}] * 21}) + "\n", encoding="utf-8")
    (state_dir / "action-history.json").write_text(json.dumps({"records": [{"action_index": index + 1, "action_name": "ACTION1"} for index in range(21)]}) + "\n", encoding="utf-8")
    monkeypatch.setattr(observe, "read_json_stdin", lambda: {
        "workspaceRoot": str(workspace_root),
        "attemptId": "attempt_x",
        "instance": {"instance_id": "attempt_x", "metadata": {"state_dir": str(state_dir), "solver_dir": str(solver_dir)}},
    })
    monkeypatch.setattr(observe, "load_runtime_meta", lambda _workspace: {"solver_template_dir": str(workspace_root / "templates" / "game_ls20")})
    materialized: list[dict] = []
    monkeypatch.setattr(
        observe,
        "materialize_attempt_snapshot",
        lambda *args, **kwargs: materialized.append({"solver_dir": str(kwargs["solver_dir"]), "workspace_dir_name": kwargs["workspace_dir_name"]}) or {"snapshot_id": "snap_x", "snapshot_path": str(workspace_root / "flux" / "attempt_snapshots" / "snap_x"), "workspace_dir": str(Path(kwargs["solver_dir"])), "arc_state_dir": str(Path(kwargs["state_dir"])), "solver_dir_name": kwargs["workspace_dir_name"]},
    )
    monkeypatch.setattr(observe, "materialize_evidence_bundle_from_snapshot", lambda *args, **kwargs: {"bundle_id": "bundle_x", "bundle_path": str(workspace_root / "flux" / "bundle_x"), "bundle_completeness": {"frontier_level": 2, "has_compare_surface": True, "status": "ready_for_compare"}})
    payloads: list[dict] = []
    monkeypatch.setattr(observe, "write_json_stdout", lambda payload: payloads.append(payload))

    observe.main()

    assert payloads
    evidence = payloads[0]["evidence"][0]
    assert evidence["visible_action_count"] == 21
    assert evidence["latest_visible_action_dir"].endswith("step_0021_action_000021_action1")
    assert "artifact_handoff_incomplete" not in evidence
    assert materialized
    assert materialized[0]["solver_dir"].endswith("game_artifacts/game_ls20-abc123")
    assert materialized[0]["workspace_dir_name"] == "game_ls20"
