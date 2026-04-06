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


def test_check_model_annotates_frontier_level_from_matched_sequences(tmp_path: Path, monkeypatch) -> None:
    _load_module("common", "scripts/flux/common.py")
    check_model = _load_module("flux_check_model_frontier_test", "scripts/flux/check_model.py")
    model_workspace = tmp_path / "agent" / "game_ls20"
    sequence_dir = model_workspace / "level_2" / "sequences"
    sequence_dir.mkdir(parents=True, exist_ok=True)
    (model_workspace / "model.py").write_text("# stub\n", encoding="utf-8")
    (sequence_dir / "seq_0007.json").write_text(
        json.dumps({
            "level": 2,
            "sequence_id": "seq_0007",
            "actions": [{
                "action_index": 99,
                "action_name": "ACTION1",
                "level_before": 2,
                "level_after": 2,
                "levels_completed_before": 1,
                "levels_completed_after": 2,
                "level_complete_after": True,
            }],
        }, indent=2),
        encoding="utf-8",
    )

    monkeypatch.setattr(check_model, "read_json_stdin", lambda: {"workspaceRoot": str(tmp_path), "modelOutput": {}})
    monkeypatch.setattr(check_model, "load_runtime_meta", lambda _workspace: {
        "model_workspace_dir": str(model_workspace),
        "run_config_dir": str(tmp_path / "config"),
        "run_bin_dir": str(tmp_path / "bin"),
        "game_id": "ls20",
    })
    monkeypatch.setattr(check_model, "_run_compare", lambda *_args, **_kwargs: (0, {
        "level": 2,
        "all_match": True,
        "eligible_sequences": 1,
        "reports": [{"level": 2, "sequence_id": "seq_0007", "matched": True}],
    }))
    payloads: list[dict] = []
    monkeypatch.setattr(check_model, "write_json_stdout", lambda payload: payloads.append(payload))

    check_model.main()

    assert payloads
    compare_payload = payloads[0]["compare_payload"]
    assert compare_payload["frontier_level"] == 3
    assert compare_payload["reports"][0]["frontier_level_after_sequence"] == 3


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

    monkeypatch.setattr(check_model, "read_json_stdin", lambda: {"workspaceRoot": str(tmp_path), "modelOutput": {}})
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


def test_sync_latest_attempt_to_model_workspace_merges_sequences_from_all_attempts_same_level(tmp_path: Path) -> None:
    common = _load_module("flux_common_all_attempts_sync_test", "scripts/flux/common.py")
    workspace_root = tmp_path / "run"
    attempts_root = workspace_root / "flux_instances"
    solver_name = "game_ls20"
    primary = attempts_root / "attempt_primary" / "agent" / solver_name / "level_1" / "sequences"
    extra = attempts_root / "attempt_extra" / "agent" / solver_name / "level_1" / "sequences"
    (attempts_root / "attempt_primary" / "supervisor" / "arc").mkdir(parents=True, exist_ok=True)
    (attempts_root / "attempt_extra" / "supervisor" / "arc").mkdir(parents=True, exist_ok=True)
    primary.mkdir(parents=True, exist_ok=True)
    extra.mkdir(parents=True, exist_ok=True)
    for root, name in [(primary, "ACTION1"), (extra, "ACTION2")]:
        seq_id = "seq_0001"
        (root / seq_id).mkdir(parents=True, exist_ok=True)
        payload = {
            "level": 1,
            "sequence_id": seq_id,
            "sequence_number": 1,
            "end_reason": "open",
            "action_count": 1,
            "actions": [{
                "local_step": 1,
                "action_name": name,
                "state_before": "NOT_FINISHED",
                "state_after": "NOT_FINISHED",
                "level_before": 1,
                "level_after": 1,
                "levels_completed_before": 0,
                "levels_completed_after": 0,
                "files": {
                    "before_state_hex": f"sequences/{seq_id}/before_state.hex",
                    "after_state_hex": f"sequences/{seq_id}/after_state.hex",
                    "meta_json": f"sequences/{seq_id}/meta.json",
                },
            }],
        }
        (root / f"{seq_id}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        (root / seq_id / "before_state.hex").write_text("0\n", encoding="utf-8")
        (root / seq_id / "after_state.hex").write_text("1\n", encoding="utf-8")
        (root / seq_id / "meta.json").write_text("{}", encoding="utf-8")

    (workspace_root / "flux").mkdir(parents=True, exist_ok=True)
    (workspace_root / "flux" / "state.json").write_text(
        json.dumps({"active": {"solver": {"instanceId": "attempt_primary", "status": "running"}}}) + "\n",
        encoding="utf-8",
    )
    model_workspace = workspace_root / "agent" / solver_name
    meta = {
        "model_workspace_dir": str(model_workspace),
        "solver_template_dir": str(workspace_root / "templates" / solver_name),
        "game_id": "ls20",
    }

    common.sync_latest_attempt_to_model_workspace(str(workspace_root), meta)

    merged_sequences = sorted((model_workspace / "level_1" / "sequences").glob("seq_*.json"))
    assert len(merged_sequences) == 2
    merged_payloads = [json.loads(path.read_text()) for path in merged_sequences]
    assert {payload["actions"][0]["action_name"] for payload in merged_payloads} == {"ACTION1", "ACTION2"}


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
    monkeypatch.setattr(observe, "materialize_evidence_bundle", lambda *args, **kwargs: {"bundle_id": "bundle_x", "bundle_path": str(workspace_root / "flux" / "bundle_x")})
    payloads: list[dict] = []
    monkeypatch.setattr(observe, "write_json_stdout", lambda payload: payloads.append(payload))

    observe.main()

    assert payloads
    evidence = payloads[0]["evidence"][0]
    assert evidence["artifact_handoff_incomplete"]["reported_action_count"] == 130
    assert evidence["artifact_handoff_incomplete"]["visible_action_count"] == 56
    assert "evidence_bundle_id" not in evidence
