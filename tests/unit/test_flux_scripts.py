from __future__ import annotations

import importlib.util
import json
import os
import shutil
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

    monkeypatch.setattr(check_model, "read_json_stdin", lambda: {"workspaceRoot": str(tmp_path), "modelOutput": {}})
    monkeypatch.setattr(check_model, "load_runtime_meta", lambda _workspace: {
        "model_workspace_dir": str(model_workspace),
        "run_config_dir": str(tmp_path / "config"),
        "run_bin_dir": str(tmp_path / "bin"),
        "game_id": "ls20",
    })
    monkeypatch.setattr(check_model, "sync_latest_attempt_to_model_workspace", lambda _workspace, _meta: [])

    calls: list[int | None] = []

    def fake_run_compare(_workspace, _meta, _env, frontier_level=None):
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
    assert payloads[0]["compare_payload"]["frontier_sync_pending"] is True


def test_check_model_classifies_missing_sequences_as_infrastructure_failure(tmp_path: Path, monkeypatch) -> None:
    _load_module("common", "scripts/flux/common.py")
    check_model = _load_module("flux_check_model_missing_sequences_test", "scripts/flux/check_model.py")
    model_workspace = tmp_path / "agent" / "game_ls20"
    model_workspace.mkdir(parents=True, exist_ok=True)
    (model_workspace / "model.py").write_text("# stub\n", encoding="utf-8")

    monkeypatch.setattr(check_model, "read_json_stdin", lambda: {"workspaceRoot": str(tmp_path), "modelOutput": {}})
    monkeypatch.setattr(check_model, "load_runtime_meta", lambda _workspace: {
        "model_workspace_dir": str(model_workspace),
        "run_config_dir": str(tmp_path / "config"),
        "run_bin_dir": str(tmp_path / "bin"),
        "game_id": "ls20",
    })
    monkeypatch.setattr(check_model, "sync_latest_attempt_to_model_workspace", lambda _workspace, _meta: [])
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


def test_check_model_uses_latest_flux_instance_state_dir_for_compare_env(tmp_path: Path, monkeypatch) -> None:
    _load_module("common", "scripts/flux/common.py")
    check_model = _load_module("flux_check_model_state_dir_test", "scripts/flux/check_model.py")
    model_workspace = tmp_path / "agent" / "game_ls20"
    model_workspace.mkdir(parents=True, exist_ok=True)
    (model_workspace / "model.py").write_text("# stub\n", encoding="utf-8")
    active_state_dir = tmp_path / "flux_instances" / "seed_rev_x" / "supervisor" / "arc"
    active_state_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(check_model, "read_json_stdin", lambda: {"workspaceRoot": str(tmp_path), "modelOutput": {}})
    monkeypatch.setattr(check_model, "load_runtime_meta", lambda _workspace: {
        "model_workspace_dir": str(model_workspace),
        "run_config_dir": str(tmp_path / "config"),
        "run_bin_dir": str(tmp_path / "bin"),
        "game_id": "ls20",
        "solver_template_dir": str(tmp_path / "flux_seed" / "agent" / "game_ls20"),
    })
    monkeypatch.setattr(check_model, "sync_latest_attempt_to_model_workspace", lambda _workspace, _meta: [])
    monkeypatch.setattr(check_model, "latest_flux_instance_state_dir", lambda _workspace, _meta: active_state_dir)

    seen_envs: list[dict] = []

    def fake_run_compare(_workspace, _meta, child_env, frontier_level=None):
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
    assert seen_envs[0]["ARC_STATE_DIR"] == str(active_state_dir)


def test_latest_flux_instance_state_dir_prefers_active_solver_instance(tmp_path: Path) -> None:
    common = _load_module("flux_common_active_instance_test", "scripts/flux/common.py")
    workspace_root = tmp_path
    solver_template_dir = workspace_root / "templates" / "game_ls20"
    solver_template_dir.mkdir(parents=True, exist_ok=True)

    stale = workspace_root / "flux_instances" / "attempt_stale"
    active = workspace_root / "flux_instances" / "seed_rev_live"
    (stale / "agent" / "game_ls20" / "level_1" / "sequences").mkdir(parents=True, exist_ok=True)
    (stale / "agent" / "game_ls20" / "level_1" / "sequences" / "seq_0001.json").write_text("{}\n", encoding="utf-8")
    (stale / "supervisor" / "arc").mkdir(parents=True, exist_ok=True)
    (active / "agent" / "game_ls20").mkdir(parents=True, exist_ok=True)
    (active / "supervisor" / "arc").mkdir(parents=True, exist_ok=True)
    (workspace_root / "flux").mkdir(parents=True, exist_ok=True)
    (workspace_root / "flux" / "state.json").write_text(
        json.dumps(
            {
                "active": {
                    "solver": {
                        "instanceId": "seed_rev_live",
                        "status": "running",
                    }
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )

    resolved = common.latest_flux_instance_state_dir(
        str(workspace_root),
        {"solver_template_dir": str(solver_template_dir)},
    )

    assert resolved == (active / "supervisor" / "arc")


def test_sync_latest_attempt_to_model_workspace_prefers_active_instance_before_richest_merge(tmp_path: Path, monkeypatch) -> None:
    common = _load_module("flux_common_active_sync_test", "scripts/flux/common.py")
    workspace_root = tmp_path
    solver_template_dir = workspace_root / "templates" / "game_ls20"
    solver_template_dir.mkdir(parents=True, exist_ok=True)

    stale = workspace_root / "flux_instances" / "attempt_stale"
    active = workspace_root / "flux_instances" / "seed_rev_live"
    (stale / "agent" / "game_ls20" / "level_1" / "sequences").mkdir(parents=True, exist_ok=True)
    (stale / "agent" / "game_ls20" / "level_1" / "sequences" / "seq_0001.json").write_text("{}\n", encoding="utf-8")
    (stale / "agent" / "game_ls20" / "level_1" / "sequences" / "seq_0002.json").write_text("{}\n", encoding="utf-8")
    (stale / "supervisor" / "arc").mkdir(parents=True, exist_ok=True)
    (active / "agent" / "game_ls20" / "level_2").mkdir(parents=True, exist_ok=True)
    (active / "supervisor" / "arc").mkdir(parents=True, exist_ok=True)
    (workspace_root / "flux").mkdir(parents=True, exist_ok=True)
    (workspace_root / "flux" / "state.json").write_text(
        json.dumps(
            {
                "active": {
                    "solver": {
                        "instanceId": "seed_rev_live",
                        "status": "running",
                    }
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )

    calls: list[tuple[Path, Path | None]] = []

    def fake_sync_solver_artifacts_to_model_workspace(meta: dict, solver_dir: Path, state_dir: Path | None = None) -> list[str]:
        calls.append((solver_dir, state_dir))
        return []

    monkeypatch.setattr(common, "sync_solver_artifacts_to_model_workspace", fake_sync_solver_artifacts_to_model_workspace)

    common.sync_latest_attempt_to_model_workspace(
        str(workspace_root),
        {
            "solver_template_dir": str(solver_template_dir),
            "model_workspace_dir": str(workspace_root / "agent" / "game_ls20"),
        },
    )

    assert calls
    assert calls[0] == (active / "agent" / "game_ls20", active / "supervisor" / "arc")
    assert calls[1] == (stale / "agent" / "game_ls20", None)


def test_sync_latest_attempt_to_model_workspace_does_not_merge_stale_extra_sequences_into_active_level(tmp_path: Path, monkeypatch) -> None:
    common = _load_module("flux_common_active_level_merge_test", "scripts/flux/common.py")
    workspace_root = tmp_path / "run"
    attempts_root = workspace_root / "flux_instances"
    solver_name = "game_ls20"

    active = attempts_root / "seed_rev_live"
    stale = attempts_root / "attempt_stale"
    active_solver = active / "agent" / solver_name
    stale_solver = stale / "agent" / solver_name

    active_sequences = active_solver / "level_1" / "sequences"
    active_sequences.mkdir(parents=True, exist_ok=True)
    (active_sequences / "seq_0001.json").write_text("{}\n", encoding="utf-8")
    (active_sequences / "seq_0002.json").write_text("{}\n", encoding="utf-8")
    (active / "supervisor" / "arc").mkdir(parents=True, exist_ok=True)

    stale_sequences = stale_solver / "level_1" / "sequences"
    stale_sequences.mkdir(parents=True, exist_ok=True)
    (stale_sequences / "seq_0001.json").write_text("{}\n", encoding="utf-8")
    (stale_sequences / "seq_0002.json").write_text("{}\n", encoding="utf-8")
    (stale_sequences / "seq_0003.json").write_text("{}\n", encoding="utf-8")
    (stale_sequences / "seq_0004.json").write_text("{}\n", encoding="utf-8")
    (stale / "supervisor" / "arc").mkdir(parents=True, exist_ok=True)

    (workspace_root / "flux").mkdir(parents=True, exist_ok=True)
    (workspace_root / "flux" / "state.json").write_text(
        json.dumps({"active": {"solver": {"instanceId": "seed_rev_live", "status": "running"}}}) + "\n",
        encoding="utf-8",
    )

    calls: list[tuple[Path, Path | None]] = []

    def fake_sync_solver_artifacts_to_model_workspace(meta: dict, solver_dir: Path, state_dir: Path | None = None) -> list[str]:
        calls.append((solver_dir, state_dir))
        return []

    monkeypatch.setattr(common, "sync_solver_artifacts_to_model_workspace", fake_sync_solver_artifacts_to_model_workspace)

    common.sync_latest_attempt_to_model_workspace(
        str(workspace_root),
        {
            "solver_template_dir": str(workspace_root / "templates" / solver_name),
            "model_workspace_dir": str(workspace_root / "agent" / solver_name),
        },
    )

    assert calls == [(active_solver, active / "supervisor" / "arc")]


def test_rehearse_seed_on_model_resolves_agent_prefixed_paths(tmp_path: Path) -> None:
    _load_module("common", "scripts/flux/common.py")
    rehearse = _load_module("flux_rehearse_seed_test", "scripts/flux/rehearse_seed_on_model.py")
    model_workspace = tmp_path / "game_ls20"
    target = model_workspace / "level_1" / "sequences" / "seq_0007.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('{"ok":true}\n', encoding="utf-8")

    resolved = rehearse._resolve_rehearsal_path(
        model_workspace,
        "agent/game_ls20/level_1/sequences/seq_0007.json",
    )
    assert resolved == target.resolve()


def test_replay_seed_on_real_game_resolves_agent_prefixed_paths(tmp_path: Path) -> None:
    _load_module("common", "scripts/flux/common.py")
    replay = _load_module("flux_replay_seed_real_test", "scripts/flux/replay_seed_on_real_game.py")
    working_directory = tmp_path / "game_ls20"
    target = working_directory / "level_1" / "sequences" / "seq_0001.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('{"ok":true}\n', encoding="utf-8")

    resolved = replay._resolve_replay_path(
        working_directory,
        "agent/game_ls20/level_1/sequences/seq_0001.json",
    )
    assert resolved == target.resolve()


def test_validate_replay_shell_cmd_rejects_shell_snippet_array() -> None:
    common = _load_module("flux_common_replay_shell_test", "scripts/flux/common.py")

    try:
        common.validate_replay_shell_cmd(["cd agent/game_ls20 && python - <<'PY'"])
    except RuntimeError as exc:
        assert "direct program token, not a shell snippet" in str(exc)
    else:
        raise AssertionError("expected replay shell validation to reject shell snippet array")


def test_validate_replay_shell_cmd_rejects_non_replayable_program() -> None:
    common = _load_module("flux_common_replay_shell_allowlist_test", "scripts/flux/common.py")

    try:
        common.validate_replay_shell_cmd(["python3", "-c", "print('hi')"])
    except RuntimeError as exc:
        assert "must be one of arc_action, arc_level, arc_repl" in str(exc)
    else:
        raise AssertionError("expected replay shell validation to reject non-replayable program")


def test_copy_model_workspace_ignores_transient_flux_artifacts(tmp_path: Path) -> None:
    common = _load_module("flux_common_snapshot_test", "scripts/flux/common.py")
    source = tmp_path / "agent" / "game_ls20"
    destination = tmp_path / "snapshot" / "game_ls20"
    (source / "level_1").mkdir(parents=True, exist_ok=True)
    (source / "level_1" / "meta.json").write_text("{}\n", encoding="utf-8")
    (source / ".level_6.flux-prev-deadbeef").mkdir(parents=True, exist_ok=True)
    (source / ".level_current.tmp").mkdir(parents=True, exist_ok=True)
    (source / ".workspace-tree.lock").write_text("", encoding="utf-8")
    meta = {"model_workspace_dir": str(source)}

    common.copy_model_workspace(meta, destination)

    assert (destination / "level_1" / "meta.json").exists()
    assert not (destination / ".level_6.flux-prev-deadbeef").exists()
    assert not (destination / ".level_current.tmp").exists()
    assert not (destination / ".workspace-tree.lock").exists()


def test_sync_latest_attempt_to_model_workspace_preserves_richer_level_sequences(tmp_path: Path) -> None:
    common = _load_module("flux_common_latest_instance_test", "scripts/flux/common.py")
    workspace_root = tmp_path / "run"
    attempts_root = workspace_root / "flux_instances"
    solver_name = "game_ls20"

    rich_attempt = attempts_root / "attempt_older"
    sparse_seed = attempts_root / "seed_rev_newer"
    rich_solver = rich_attempt / "agent" / solver_name
    sparse_solver = sparse_seed / "agent" / solver_name
    rich_level = rich_solver / "level_1"
    sparse_level = sparse_solver / "level_1"
    rich_sequences = rich_level / "sequences"
    rich_sequences.mkdir(parents=True, exist_ok=True)
    (rich_sequences / "seq_0001.json").write_text("{}\n", encoding="utf-8")
    (rich_level / "initial_state.hex").write_text("0\n", encoding="utf-8")
    (rich_level / "initial_state.meta.json").write_text("{}\n", encoding="utf-8")

    sparse_level.mkdir(parents=True, exist_ok=True)
    (sparse_level / "initial_state.hex").write_text("0\n", encoding="utf-8")
    (sparse_level / "initial_state.meta.json").write_text("{}\n", encoding="utf-8")
    (sparse_solver / "level_current").mkdir(parents=True, exist_ok=True)
    (sparse_solver / "level_current" / "meta.json").write_text(json.dumps({"level": 1}), encoding="utf-8")
    (sparse_solver / "level_current" / "initial_state.hex").write_text("0\n", encoding="utf-8")
    (sparse_solver / "level_current" / "initial_state.meta.json").write_text("{}\n", encoding="utf-8")

    model_workspace = workspace_root / "agent" / solver_name
    meta = {
        "model_workspace_dir": str(model_workspace),
        "solver_template_dir": str(workspace_root / "flux_seed" / "agent" / solver_name),
    }

    rich_mtime = time.time() - 10
    sparse_mtime = time.time()
    os.utime(rich_attempt, (rich_mtime, rich_mtime))
    os.utime(sparse_seed, (sparse_mtime, sparse_mtime))

    common.sync_latest_attempt_to_model_workspace(str(workspace_root), meta)

    assert (model_workspace / "level_1" / "sequences" / "seq_0001.json").exists()


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
