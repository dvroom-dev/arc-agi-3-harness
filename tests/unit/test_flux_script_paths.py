from __future__ import annotations

import importlib.util
import json
import os
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


def test_rehearse_seed_on_model_marks_compare_error_as_failed_rehearsal(tmp_path: Path, monkeypatch) -> None:
    _load_module("common", "scripts/flux/common.py")
    rehearse = _load_module("flux_rehearse_seed_compare_error_test", "scripts/flux/rehearse_seed_on_model.py")
    workspace_root = tmp_path / "run"
    model_workspace = workspace_root / "agent" / "game_ls20"
    model_workspace.mkdir(parents=True, exist_ok=True)
    (model_workspace / "model.py").write_text("# stub\n", encoding="utf-8")

    monkeypatch.setattr(rehearse, "read_json_stdin", lambda: {
        "workspaceRoot": str(workspace_root),
        "seedBundle": {"replayPlan": []},
        "seedHash": "seed_hash_x",
    })
    monkeypatch.setattr(rehearse, "load_runtime_meta", lambda _workspace: {
        "model_workspace_dir": str(model_workspace),
        "run_config_dir": str(workspace_root / "config"),
        "run_bin_dir": str(workspace_root / "bin"),
        "game_id": "ls20",
    })
    monkeypatch.setattr(rehearse, "copy_model_workspace", lambda _meta, destination: destination.mkdir(parents=True, exist_ok=True) or destination)

    calls = {"count": 0}

    def fake_run_model_command(_model_workspace, _env, args, stdin_text=None):
        calls["count"] += 1
        action = args[0]
        if action == "shutdown":
            return {"parsed": {"ok": True}}
        if action == "status":
            return {"parsed": {"ok": True, "action": "status", "current_level": 2 if calls["count"] >= 3 else 1, "levels_completed": 1 if calls["count"] >= 3 else 0}}
        if action == "compare_sequences":
            return {
                "parsed": {
                    "ok": False,
                    "action": "compare_sequences",
                    "error": {
                        "type": "missing_sequences",
                        "message": "missing sequences dir: /tmp/rehearsal/level_2/sequences",
                    },
                }
            }
        raise AssertionError(f"unexpected action: {args}")

    monkeypatch.setattr(rehearse, "_run_model_command", fake_run_model_command)

    payloads: list[dict] = []
    monkeypatch.setattr(rehearse, "write_json_stdout", lambda payload: payloads.append(payload))

    rehearse.main()

    assert payloads
    assert payloads[0]["rehearsal_ok"] is False
    assert payloads[0]["error"]["type"] == "compare_failed"
    assert payloads[0]["compare_payload"]["error"]["type"] == "missing_sequences"


def test_rehearse_seed_on_model_stops_when_expected_frontier_is_reached(tmp_path: Path, monkeypatch) -> None:
    _load_module("common", "scripts/flux/common.py")
    rehearse = _load_module("flux_rehearse_seed_frontier_test", "scripts/flux/rehearse_seed_on_model.py")
    workspace_root = tmp_path / "run"
    model_workspace = workspace_root / "agent" / "game_ls20"
    model_workspace.mkdir(parents=True, exist_ok=True)
    (model_workspace / "model.py").write_text("# stub\n", encoding="utf-8")

    monkeypatch.setattr(rehearse, "read_json_stdin", lambda: {
        "workspaceRoot": str(workspace_root),
        "seedBundle": {"replayPlan": [{"tool": "shell", "args": {"cmd": ["arc_action", "ACTION1"]}}, {"tool": "shell", "args": {"cmd": ["arc_action", "ACTION1"]}}]},
        "seedHash": "seed_hash_x",
        "expectedFrontierLevel": 2,
    })
    monkeypatch.setattr(rehearse, "load_runtime_meta", lambda _workspace: {
        "model_workspace_dir": str(model_workspace),
        "run_config_dir": str(workspace_root / "config"),
        "run_bin_dir": str(workspace_root / "bin"),
        "game_id": "ls20",
    })
    monkeypatch.setattr(rehearse, "copy_model_workspace", lambda _meta, destination: destination.mkdir(parents=True, exist_ok=True) or destination)

    calls: list[tuple[str, list[str]]] = []

    def fake_run_model_command(_model_workspace, _env, args, stdin_text=None):
        action = args[0]
        calls.append((action, list(args)))
        if action == "shutdown":
            return {"parsed": {"ok": True}}
        if action == "status":
            return {"parsed": {"ok": True, "action": "status", "current_level": 2, "levels_completed": 1}}
        if action == "exec":
            return {"returncode": 0, "parsed": {"ok": True, "action": "exec", "current_level": 2, "levels_completed": 1}}
        if action == "compare_sequences":
            return {"parsed": {"ok": True, "action": "compare_sequences", "level": 2, "all_match": True, "compared_sequences": 1, "eligible_sequences": 1}}
        raise AssertionError(f"unexpected action: {args}")

    monkeypatch.setattr(rehearse, "_run_model_command", fake_run_model_command)

    payloads: list[dict] = []
    monkeypatch.setattr(rehearse, "write_json_stdout", lambda payload: payloads.append(payload))

    rehearse.main()

    exec_calls = [entry for entry in calls if entry[0] == "exec"]
    assert len(exec_calls) == 1
    compare_calls = [entry for entry in calls if entry[0] == "compare_sequences"]
    assert compare_calls
    assert compare_calls[0][1][compare_calls[0][1].index("--level") + 1] == "2"
    assert payloads[0]["rehearsal_ok"] is True


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


def test_replay_seed_on_real_game_uses_evidence_bundle_sync(tmp_path: Path, monkeypatch) -> None:
    _load_module("common", "scripts/flux/common.py")
    replay = _load_module("flux_replay_seed_real_bundle_test", "scripts/flux/replay_seed_on_real_game.py")
    workspace_root = tmp_path / "run"
    working_directory = workspace_root / "agent" / "game_ls20"
    state_dir = workspace_root / "supervisor" / "arc"
    working_directory.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(replay, "read_json_stdin", lambda: {
        "workspaceRoot": str(workspace_root),
        "attemptId": "attempt_x",
        "seedBundle": {"replayPlan": []},
        "instance": {
            "instance_id": "attempt_x",
            "working_directory": str(working_directory),
            "metadata": {"state_dir": str(state_dir)},
            "env": {},
        },
    })
    monkeypatch.setattr(replay, "load_runtime_meta", lambda _workspace: {"model_workspace_dir": str(workspace_root / "durable")})
    monkeypatch.setattr(replay, "summarize_instance_state", lambda _state_dir: {"summary": "ok"})

    calls: dict[str, object] = {}
    monkeypatch.setattr(replay, "materialize_attempt_snapshot", lambda *args, **kwargs: {"snapshot_id": "snap", "workspace_dir": str(working_directory), "arc_state_dir": str(state_dir)})
    monkeypatch.setattr(replay, "materialize_evidence_bundle_from_snapshot", lambda *_args, **_kwargs: {
        "bundle_id": "bundle_x",
        "bundle_path": str(workspace_root / "flux" / "evidence_bundles" / "bundle_x"),
        "bundle_completeness": {"status": "ready_for_compare"},
    })
    def fake_sync(_meta, bundle_path):
        calls["bundle_path"] = str(bundle_path)
        return ["synced"]

    monkeypatch.setattr(replay, "sync_evidence_bundle_to_model_workspace", fake_sync)

    payloads: list[dict] = []
    monkeypatch.setattr(replay, "write_json_stdout", lambda payload: payloads.append(payload))

    replay.main()

    assert calls["bundle_path"].endswith("bundle_x")
    assert payloads
    assert payloads[0]["evidence_bundle_id"] == "bundle_x"
    assert payloads[0]["evidence_bundle_path"].endswith("bundle_x")


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
