from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
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


def test_observe_evidence_script_runs_as_real_subprocess_and_materializes_bundle(tmp_path: Path) -> None:
    workspace_root = tmp_path / "run"
    solver_dir = workspace_root / "flux_instances" / "attempt_x" / "agent" / "game_ls20"
    state_dir = workspace_root / "flux_instances" / "attempt_x" / "supervisor" / "arc"
    solver_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    (workspace_root / "flux").mkdir(parents=True, exist_ok=True)
    (solver_dir / "level_current").mkdir(parents=True, exist_ok=True)
    (solver_dir / "level_current" / "meta.json").write_text(
        json.dumps({"schema_version": "arc_repl.level_current.v1", "level": 1}, indent=2) + "\n",
        encoding="utf-8",
    )
    (solver_dir / "level_current" / "initial_state.hex").write_text("0\n", encoding="utf-8")
    (state_dir / "state.json").write_text(
        json.dumps({"current_level": 1, "levels_completed": 0, "state": "NOT_FINISHED"}, indent=2) + "\n",
        encoding="utf-8",
    )
    (state_dir / "tool-engine-history.json").write_text(json.dumps({"events": []}) + "\n", encoding="utf-8")
    (state_dir / "action-history.json").write_text(json.dumps([]) + "\n", encoding="utf-8")
    (workspace_root / "flux_runtime.json").write_text(
        json.dumps(
            {
                "solver_template_dir": str(workspace_root / "flux_seed" / "agent" / "game_ls20"),
                "model_workspace_dir": str(workspace_root / "agent" / "game_ls20"),
                "game_id": "ls20",
                "run_config_dir": str(workspace_root / "config"),
                "run_bin_dir": str(workspace_root / "config" / "bin"),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "flux" / "observe_evidence.py"
    proc = subprocess.run(
        [str(Path(__file__).resolve().parents[2] / ".venv" / "bin" / "python"), str(script_path)],
        input=json.dumps(
            {
                "workspaceRoot": str(workspace_root),
                "attemptId": "attempt_x",
                "instance": {
                    "instance_id": "attempt_x",
                    "metadata": {
                        "state_dir": str(state_dir),
                        "solver_dir": str(solver_dir),
                    },
                },
            }
        ),
        text=True,
        capture_output=True,
        env={
            **os.environ,
            "ARC_FLUX_META_PATH": str(workspace_root / "flux_runtime.json"),
        },
        cwd=str(workspace_root),
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    payload = json.loads(proc.stdout)
    bundle_path = Path(str(payload["evidence_bundle_path"]))
    assert payload["attempt_snapshot_id"]
    assert payload["attempt_snapshot_path"]
    assert payload["evidence_bundle_id"]
    assert bundle_path.exists()
    assert (bundle_path / "manifest.json").exists()
    manifest = json.loads((bundle_path / "manifest.json").read_text())
    assert payload["bundle_completeness"]["status"] == "incomplete_artifacts"
    assert manifest["bundle_path"] == str(bundle_path)
    assert manifest["manifest_path"] == str(bundle_path / "manifest.json")
    assert manifest["workspace_dir"] == str(bundle_path / "workspace" / "game_ls20")
    assert "/.evidence_" not in manifest["workspace_dir"]


def test_observe_evidence_copies_solver_handoff_notes_into_snapshot_and_bundle(tmp_path: Path) -> None:
    workspace_root = tmp_path / "run"
    solver_dir = workspace_root / "flux_instances" / "attempt_x" / "agent" / "game_ls20"
    canonical_surface = workspace_root / "flux_instances" / "attempt_x" / "supervisor" / "arc" / "game_artifacts" / "game_ls20-live"
    state_dir = workspace_root / "flux_instances" / "attempt_x" / "supervisor" / "arc"
    solver_handoff = solver_dir / "solver_handoff"
    solver_handoff.mkdir(parents=True, exist_ok=True)
    canonical_surface.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    (workspace_root / "flux").mkdir(parents=True, exist_ok=True)
    (canonical_surface / "level_current").mkdir(parents=True, exist_ok=True)
    (canonical_surface / "level_current" / "meta.json").write_text(
        json.dumps({"schema_version": "arc_repl.level_current.v1", "level": 2}, indent=2) + "\n",
        encoding="utf-8",
    )
    (canonical_surface / "level_current" / "initial_state.hex").write_text("0\n", encoding="utf-8")
    (solver_handoff / "untrusted_theories.md").write_text("# Solver handoff\nValidated level 1 mechanic.\n", encoding="utf-8")
    (state_dir / "state.json").write_text(
        json.dumps({"current_level": 2, "levels_completed": 1, "state": "NOT_FINISHED"}, indent=2) + "\n",
        encoding="utf-8",
    )
    (state_dir / "tool-engine-history.json").write_text(json.dumps({"events": []}) + "\n", encoding="utf-8")
    (state_dir / "action-history.json").write_text(json.dumps([]) + "\n", encoding="utf-8")
    (workspace_root / "flux_runtime.json").write_text(
        json.dumps(
            {
                "solver_template_dir": str(workspace_root / "flux_seed" / "agent" / "game_ls20"),
                "model_workspace_dir": str(workspace_root / "agent" / "game_ls20"),
                "game_id": "ls20",
                "run_config_dir": str(workspace_root / "config"),
                "run_bin_dir": str(workspace_root / "config" / "bin"),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "flux" / "observe_evidence.py"
    proc = subprocess.run(
        [str(Path(__file__).resolve().parents[2] / ".venv" / "bin" / "python"), str(script_path)],
        input=json.dumps(
            {
                "workspaceRoot": str(workspace_root),
                "attemptId": "attempt_x",
                "instance": {
                    "instance_id": "attempt_x",
                    "metadata": {
                        "state_dir": str(state_dir),
                        "solver_dir": str(solver_dir),
                    },
                },
            }
        ),
        text=True,
        capture_output=True,
        env={**os.environ, "ARC_FLUX_META_PATH": str(workspace_root / "flux_runtime.json")},
        cwd=str(workspace_root),
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    payload = json.loads(proc.stdout)
    bundle_path = Path(str(payload["evidence_bundle_path"]))
    assert (bundle_path / "workspace" / "game_ls20" / "solver_handoff" / "untrusted_theories.md").exists()




def test_sync_solver_artifacts_to_model_workspace_retries_transient_copy_errors(
    tmp_path: Path,
    monkeypatch,
) -> None:
    common = _load_module("flux_common_test", "scripts/flux/common.py")
    solver_dir = tmp_path / "solver"
    model_workspace = tmp_path / "model"
    level_current = solver_dir / "level_current"
    level_current.mkdir(parents=True, exist_ok=True)
    (level_current / "meta.json").write_text(
        json.dumps({"schema_version": "arc_repl.level_current.v1", "level": 1}, indent=2) + "\n",
        encoding="utf-8",
    )
    (level_current / "initial_state.hex").write_text("0123\n", encoding="utf-8")
    (level_current / "initial_state.meta.json").write_text("{}\n", encoding="utf-8")
    stale_dir = model_workspace / "level_current"
    stale_dir.mkdir(parents=True, exist_ok=True)
    (stale_dir / "stale.txt").write_text("keep-until-replaced\n", encoding="utf-8")
    meta = {"model_workspace_dir": str(model_workspace), "game_id": "ls20"}

    original_copytree = shutil.copytree
    call_count = {"count": 0}

    def flaky_copytree(src, dst, *args, **kwargs):
        call_count["count"] += 1
        if call_count["count"] == 1:
            raise shutil.Error([(str(src), str(dst), "[Errno 2] No such file or directory")])
        return original_copytree(src, dst, *args, **kwargs)

    monkeypatch.setattr(common.shutil, "copytree", flaky_copytree)
    synced = common.sync_solver_artifacts_to_model_workspace(meta, solver_dir, state_dir=None)

    assert str(model_workspace / "level_current") in synced
    assert call_count["count"] >= 2
    assert (model_workspace / "level_current" / "initial_state.hex").exists()
    assert not (model_workspace / "level_current" / "stale.txt").exists()


def test_sync_evidence_bundle_to_model_workspace_replaces_level_tree_atomically(
    tmp_path: Path,
    monkeypatch,
) -> None:
    common = _load_module("flux_common_evidence_atomic_test", "scripts/flux/common.py")
    model_workspace = tmp_path / "agent" / "game_ls20"
    old_sequences = model_workspace / "level_1" / "sequences"
    old_sequences.mkdir(parents=True, exist_ok=True)
    (old_sequences / "seq_0001.json").write_text(json.dumps({"level": 1, "sequence_id": "seq_0001"}) + "\n", encoding="utf-8")
    (old_sequences / "stale.txt").write_text("stale\n", encoding="utf-8")

    bundle_root = _ready_evidence_bundle(tmp_path, "game_ls20")
    bundle_workspace = bundle_root / "workspace" / "game_ls20"
    bundle_sequences = bundle_workspace / "level_1" / "sequences"
    bundle_sequences.mkdir(parents=True, exist_ok=True)
    (bundle_sequences / "seq_0001.json").write_text(json.dumps({"level": 1, "sequence_id": "seq_0001"}) + "\n", encoding="utf-8")
    (bundle_sequences / "seq_0002.json").write_text(json.dumps({"level": 1, "sequence_id": "seq_0002"}) + "\n", encoding="utf-8")

    meta = {"model_workspace_dir": str(model_workspace), "game_id": "ls20"}
    observed: dict[str, object] = {}
    original_copytree_stable = common.copytree_stable

    def spy_copytree(src, dst, *args, **kwargs):
        if Path(src) == bundle_workspace / "level_1":
            observed["during_copy_exists"] = (model_workspace / "level_1").exists()
            observed["during_copy_files"] = sorted(path.name for path in (model_workspace / "level_1" / "sequences").glob("*"))
            observed["copy_target_name"] = Path(dst).name
        return original_copytree_stable(src, dst, *args, **kwargs)

    monkeypatch.setattr(common, "copytree_stable", spy_copytree)

    synced = common.sync_evidence_bundle_to_model_workspace(meta, bundle_root)

    assert str(model_workspace / "level_1") in synced
    assert observed["during_copy_exists"] is True
    assert observed["during_copy_files"] == ["seq_0001.json", "stale.txt"]
    assert str(observed["copy_target_name"]).startswith(".level_1.flux-sync-")
    assert sorted(path.name for path in (model_workspace / "level_1" / "sequences").glob("seq_*.json")) == [
        "seq_0001.json",
        "seq_0002.json",
    ]
    assert not (model_workspace / "level_1" / "sequences" / "stale.txt").exists()


def test_sync_evidence_bundle_to_model_workspace_materializes_solver_theory_metadata(tmp_path: Path) -> None:
    common = _load_module("flux_common_solver_theory_sync_test", "scripts/flux/common.py")
    model_workspace = tmp_path / "agent" / "game_ls20"
    bundle_root = _ready_evidence_bundle(tmp_path, "game_ls20")
    manifest_path = bundle_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["bundle_id"] = "bundle_solver_theory"
    manifest["attempt_id"] = "attempt_solver"
    manifest["instance_id"] = "instance_solver"
    manifest["bundle_completeness"]["frontier_level"] = 2
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    bundle_workspace = bundle_root / "workspace" / "game_ls20"
    (bundle_workspace / "solver_handoff").mkdir(parents=True, exist_ok=True)
    (bundle_workspace / "solver_handoff" / "untrusted_theories.md").write_text(
        "# Solver theory\nCross changes the icon.\n",
        encoding="utf-8",
    )

    meta = {"model_workspace_dir": str(model_workspace), "game_id": "ls20"}
    synced = common.sync_evidence_bundle_to_model_workspace(meta, bundle_root)

    assert str(model_workspace / "solver_handoff") in synced
    theory_json = json.loads((model_workspace / "untrusted_theories_level_1.json").read_text())
    assert theory_json["schema_version"] == "flux.solver_untrusted_theory_handoff.v1"
    assert theory_json["level"] == 1
    assert theory_json["frontier_level"] == 2
    assert theory_json["solver_handoff_markdown_path"] == "solver_handoff/untrusted_theories.md"


def test_check_model_skips_frontier_compare_until_frontier_level_is_ready(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _load_module("common", "scripts/flux/common.py")
    check_model = _load_module("flux_check_model_test", "scripts/flux/check_model.py")
    model_workspace = tmp_path / "agent" / "game_ls20"
    (model_workspace / "model.py").parent.mkdir(parents=True, exist_ok=True)
    (model_workspace / "model.py").write_text("# stub\n", encoding="utf-8")
    (model_workspace / "level_current").mkdir(parents=True, exist_ok=True)
    (model_workspace / "level_current" / "meta.json").write_text(
        json.dumps({"schema_version": "arc_repl.level_current.v1", "level": 2}, indent=2) + "\n",
        encoding="utf-8",
    )

    bundle_root = _ready_evidence_bundle(tmp_path, "game_ls20")
    monkeypatch.setattr(check_model, "read_json_stdin", lambda: {"workspaceRoot": str(tmp_path), "modelOutput": {}, "evidenceBundlePath": str(bundle_root)})
    monkeypatch.setattr(check_model, "load_runtime_meta", lambda _workspace: {
        "model_workspace_dir": str(model_workspace),
        "run_config_dir": str(tmp_path / "config"),
        "run_bin_dir": str(tmp_path / "bin"),
        "game_id": "ls20",
    })

    calls: list[int | None] = []

    def fake_run_compare(_workspace, _meta, _env, frontier_level=None, *, include_reset_ended=False):
        calls.append(frontier_level)
        return 0, {
            "level": 1,
            "all_match": False,
            "eligible_sequences": 1,
            "reports": [{"sequence_id": "seq_0001", "matched": False}],
        }

    payloads: list[dict] = []
    monkeypatch.setattr(check_model, "_run_compare", fake_run_compare)
    monkeypatch.setattr(check_model, "write_json_stdout", lambda payload: payloads.append(payload))

    check_model.main()

    assert calls == [None]
    assert payloads
    assert payloads[0]["accepted"] is False


def test_check_model_classifies_missing_sequences_as_infrastructure_failure(tmp_path: Path, monkeypatch) -> None:
    _load_module("common", "scripts/flux/common.py")
    check_model = _load_module("flux_check_model_missing_sequences_test", "scripts/flux/check_model.py")
    model_workspace = tmp_path / "agent" / "game_ls20"
    model_workspace.mkdir(parents=True, exist_ok=True)
    (model_workspace / "model.py").write_text("# stub\n", encoding="utf-8")

    bundle_root = _ready_evidence_bundle(tmp_path, "game_ls20")
    monkeypatch.setattr(check_model, "read_json_stdin", lambda: {"workspaceRoot": str(tmp_path), "modelOutput": {}, "evidenceBundlePath": str(bundle_root)})
    monkeypatch.setattr(check_model, "load_runtime_meta", lambda _workspace: {
        "model_workspace_dir": str(model_workspace),
        "run_config_dir": str(tmp_path / "config"),
        "run_bin_dir": str(tmp_path / "bin"),
        "game_id": "ls20",
    })
    monkeypatch.setattr(
        check_model,
        "_run_compare",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError('{"ok": false, "action": "compare_sequences", "error": {"type": "missing_sequences", "message": "missing sequences dir: /tmp/level_1/sequences"}}')
        ),
    )

    payloads: list[dict] = []
    monkeypatch.setattr(check_model, "write_json_stdout", lambda payload: payloads.append(payload))

    check_model.main()

    assert payloads
    assert payloads[0]["accepted"] is False
    assert payloads[0]["infrastructure_failure"]["type"] == "missing_sequence_surface"


def test_check_model_uses_evidence_bundle_state_dir_for_compare_env(tmp_path: Path, monkeypatch) -> None:
    _load_module("common", "scripts/flux/common.py")
    check_model = _load_module("flux_check_model_state_dir_test", "scripts/flux/check_model.py")
    model_workspace = tmp_path / "agent" / "game_ls20"
    model_workspace.mkdir(parents=True, exist_ok=True)
    (model_workspace / "model.py").write_text("# stub\n", encoding="utf-8")
    bundle_state_dir = tmp_path / "flux" / "evidence_bundles" / "bundle_x" / "arc_state"
    bundle_state_dir.mkdir(parents=True, exist_ok=True)
    bundle_workspace = bundle_state_dir.parent / "workspace" / "game_ls20"
    bundle_workspace.mkdir(parents=True, exist_ok=True)
    (bundle_state_dir.parent / "manifest.json").write_text(
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

    monkeypatch.setattr(check_model, "read_json_stdin", lambda: {
        "workspaceRoot": str(tmp_path),
        "modelOutput": {},
        "evidenceBundlePath": str(bundle_state_dir.parent),
    })
    monkeypatch.setattr(check_model, "load_runtime_meta", lambda _workspace: {
        "model_workspace_dir": str(model_workspace),
        "run_config_dir": str(tmp_path / "config"),
        "run_bin_dir": str(tmp_path / "bin"),
        "game_id": "ls20",
        "solver_template_dir": str(tmp_path / "flux_seed" / "agent" / "game_ls20"),
    })

    seen_envs: list[dict] = []

    def fake_run_compare(_workspace, _meta, child_env, frontier_level=None, *, include_reset_ended=False):
        seen_envs.append(dict(child_env))
        return 0, {
            "level": 1,
            "all_match": True,
            "eligible_sequences": 1,
            "reports": [{"sequence_id": "seq_0001", "matched": True}],
        }

    payloads: list[dict] = []
    monkeypatch.setattr(check_model, "_run_compare", fake_run_compare)
    monkeypatch.setattr(check_model, "write_json_stdout", lambda payload: payloads.append(payload))

    check_model.main()

    assert seen_envs
    assert seen_envs[0]["ARC_STATE_DIR"] == str(bundle_state_dir)


def test_inspect_current_mismatch_falls_back_to_first_report(tmp_path: Path) -> None:
    artifact_helpers = _load_module("artifact_helpers_fallback_test", "templates/agent_workspace/artifact_helpers.py")
    game_dir = tmp_path / "game_ls20"
    (game_dir / "level_1" / "sequences").mkdir(parents=True, exist_ok=True)
    sequence = {
        "schema_version": "arc_repl.level_sequence.v1",
        "game_id": "ls20",
        "level": 1,
        "sequence_id": "seq_0001",
        "sequence_number": 1,
        "start_action_index": 1,
        "end_action_index": 1,
        "start_recorded_at_utc": "",
        "end_recorded_at_utc": "",
        "end_reason": "open",
        "action_count": 1,
        "actions": [
            {
                "local_step": 1,
                "action_index": 1,
                "tool_turn": 1,
                "step_in_call": 1,
                "call_action": "exec",
                "action_name": "ACTION1",
                "action_data": {},
                "state_before": "NOT_FINISHED",
                "state_after": "NOT_FINISHED",
                "level_before": 1,
                "level_after": 1,
                "levels_completed_before": 0,
                "levels_completed_after": 0,
                "recorded_at_utc": "",
                "files": {
                    "before_state_hex": "sequences/seq_0001/actions/step_0001_action_000001_action1/before_state.hex",
                    "after_state_hex": "sequences/seq_0001/actions/step_0001_action_000001_action1/after_state.hex",
                    "meta_json": "sequences/seq_0001/actions/step_0001_action_000001_action1/meta.json",
                },
            }
        ],
    }
    step_dir = game_dir / "level_1" / "sequences" / "seq_0001" / "actions" / "step_0001_action_000001_action1"
    step_dir.mkdir(parents=True, exist_ok=True)
    (step_dir / "before_state.hex").write_text("0\n", encoding="utf-8")
    (step_dir / "after_state.hex").write_text("1\n", encoding="utf-8")
    (step_dir / "meta.json").write_text("{}\n", encoding="utf-8")
    (game_dir / "level_1" / "sequences" / "seq_0001.json").write_text(json.dumps(sequence, indent=2), encoding="utf-8")
    compare_payload = {
        "status": "mismatch",
        "all_match": False,
        "level": 1,
        "reports": [
            {
                "level": 1,
                "sequence_id": "seq_0001",
                "divergence_step": 1,
                "divergence_reason": "intermediate_frame_mismatch",
                "report_file": "level_1/sequence_compare/seq_0001.md",
            }
        ],
    }
    (game_dir / "current_compare.json").write_text(json.dumps(compare_payload, indent=2), encoding="utf-8")
    (game_dir / "current_compare.md").write_text("# Current Compare\n", encoding="utf-8")

    payload = artifact_helpers.inspect_current_mismatch(game_dir)

    assert payload["sequence_id"] == "seq_0001"
    assert payload["compare"]["warning"] == "fell back to first report because no explicit mismatched report was marked"
