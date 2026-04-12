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


def test_check_model_classifies_missing_sequence_frame_as_infrastructure_failure(tmp_path, monkeypatch) -> None:
    _load_module("common", "scripts/flux/common.py")
    check_model = _load_module("flux_check_model_missing_frame_test", "scripts/flux/check_model.py")
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
            RuntimeError(
                "Traceback...\nFileNotFoundError: [Errno 2] No such file or directory: '/tmp/game_ls20/level_1/sequences/seq_0001/actions/step_0001_action_000014_action1/frames/frame_0001.hex'"
            )
        ),
    )

    payloads: list[dict] = []
    monkeypatch.setattr(check_model, "write_json_stdout", lambda payload: payloads.append(payload))

    check_model.main()

    assert payloads
    assert payloads[0]["accepted"] is False
    assert payloads[0]["infrastructure_failure"]["type"] == "missing_sequence_surface"


def test_check_model_uses_targeted_sequence_compare_before_full_compare(tmp_path, monkeypatch) -> None:
    _load_module("common", "scripts/flux/common.py")
    check_model = _load_module("flux_check_model_targeted_compare_test", "scripts/flux/check_model.py")
    model_workspace = tmp_path / "agent" / "game_ls20"
    (model_workspace / "model.py").parent.mkdir(parents=True, exist_ok=True)
    (model_workspace / "model.py").write_text("# stub\n", encoding="utf-8")
    seq_dir = model_workspace / "level_1" / "sequences"
    seq_dir.mkdir(parents=True, exist_ok=True)
    (seq_dir / "seq_0002.json").write_text(json.dumps({"level": 1, "sequence_id": "seq_0002"}, indent=2) + "\n", encoding="utf-8")

    bundle_root = _ready_evidence_bundle(tmp_path, "game_ls20")
    monkeypatch.setattr(check_model, "read_json_stdin", lambda: {
        "workspaceRoot": str(tmp_path),
        "modelOutput": {},
        "evidenceBundlePath": str(bundle_root),
        "acceptanceTarget": {"maxLevel": 1, "level": 1, "sequenceId": "seq_0002"},
    })
    monkeypatch.setattr(check_model, "load_runtime_meta", lambda _workspace: {
        "model_workspace_dir": str(model_workspace),
        "run_config_dir": str(tmp_path / "config"),
        "run_bin_dir": str(tmp_path / "bin"),
        "game_id": "ls20",
    })

    calls: list[tuple[int | None, str | None]] = []

    def fake_run_compare(_workspace, _meta, _env, frontier_level=None, sequence_id=None, *, include_reset_ended=False):
        calls.append((frontier_level, sequence_id))
        if sequence_id == "seq_0002":
            return 0, {
                "ok": True,
                "action": "compare_sequences",
                "level": 1,
                "all_match": False,
                "requested_sequences": 1,
                "eligible_sequences": 1,
                "compared_sequences": 1,
                "diverged_sequences": 1,
                "reports": [
                    {
                        "level": 1,
                        "sequence_id": "seq_0002",
                        "matched": False,
                        "divergence_step": 7,
                        "divergence_reason": "frame_count_mismatch",
                    }
                ],
            }
        raise AssertionError("full compare should not run when targeted sequence still fails")

    payloads: list[dict] = []
    monkeypatch.setattr(check_model, "_run_compare", fake_run_compare)
    monkeypatch.setattr(check_model, "write_json_stdout", lambda payload: payloads.append(payload))

    check_model.main()

    assert calls == [(1, "seq_0002")]
    assert payloads
    assert payloads[0]["accepted"] is False
    assert payloads[0]["compare_payload"]["compared_sequences"] == 1
    assert payloads[0]["compare_payload"]["reports"][0]["sequence_id"] == "seq_0002"


def test_check_model_runs_compare_in_no_persist_mode(tmp_path, monkeypatch) -> None:
    _load_module("common", "scripts/flux/common.py")
    check_model = _load_module("flux_check_model_no_persist_test", "scripts/flux/check_model.py")
    model_workspace = tmp_path / "agent" / "game_ls20"
    (model_workspace / "model.py").parent.mkdir(parents=True, exist_ok=True)
    (model_workspace / "model.py").write_text("# stub\n", encoding="utf-8")
    seq_dir = model_workspace / "level_1" / "sequences"
    seq_dir.mkdir(parents=True, exist_ok=True)
    (seq_dir / "seq_0001.json").write_text(json.dumps({"level": 1, "sequence_id": "seq_0001"}, indent=2) + "\n", encoding="utf-8")

    bundle_root = _ready_evidence_bundle(tmp_path, "game_ls20")
    monkeypatch.setattr(check_model, "read_json_stdin", lambda: {
        "workspaceRoot": str(tmp_path),
        "modelOutput": {"summary": "accepted"},
        "evidenceBundlePath": str(bundle_root),
        "acceptanceTarget": {"maxLevel": 1, "level": 1},
    })
    monkeypatch.setattr(check_model, "load_runtime_meta", lambda _workspace: {
        "model_workspace_dir": str(model_workspace),
        "run_config_dir": str(tmp_path / "config"),
        "run_bin_dir": str(tmp_path / "bin"),
        "game_id": "ls20",
    })

    seen_env: dict[str, str] = {}

    def fake_run_compare(_workspace, _meta, env, frontier_level=None, sequence_id=None, *, include_reset_ended=False):
        seen_env.update(env)
        return 0, {
            "ok": True,
            "action": "compare_sequences",
            "level": frontier_level or 1,
            "frontier_level": frontier_level or 1,
            "requested_sequences": 1,
            "eligible_sequences": 1,
            "compared_sequences": 1,
            "diverged_sequences": 0,
            "all_match": True,
            "reports": [{"level": frontier_level or 1, "sequence_id": "seq_0001", "matched": True}],
        }

    payloads: list[dict] = []
    monkeypatch.setattr(check_model, "_run_compare", fake_run_compare)
    monkeypatch.setattr(check_model, "write_json_stdout", lambda payload: payloads.append(payload))

    check_model.main()

    assert payloads
    assert payloads[0]["accepted"] is True
    assert seen_env["ARC_MODEL_COMPARE_NO_PERSIST"] == "1"
    assert seen_env["ARC_MODEL_PERSIST_STATUS"] == "0"


def test_check_model_falls_back_to_full_compare_after_targeted_sequence_passes(tmp_path, monkeypatch) -> None:
    _load_module("common", "scripts/flux/common.py")
    check_model = _load_module("flux_check_model_targeted_then_full_test", "scripts/flux/check_model.py")
    model_workspace = tmp_path / "agent" / "game_ls20"
    (model_workspace / "model.py").parent.mkdir(parents=True, exist_ok=True)
    (model_workspace / "model.py").write_text("# stub\n", encoding="utf-8")
    seq_dir = model_workspace / "level_1" / "sequences"
    seq_dir.mkdir(parents=True, exist_ok=True)
    (seq_dir / "seq_0002.json").write_text(json.dumps({"level": 1, "sequence_id": "seq_0002"}, indent=2) + "\n", encoding="utf-8")

    bundle_root = _ready_evidence_bundle(tmp_path, "game_ls20")
    monkeypatch.setattr(check_model, "read_json_stdin", lambda: {
        "workspaceRoot": str(tmp_path),
        "modelOutput": {"summary": "accepted"},
        "evidenceBundlePath": str(bundle_root),
        "acceptanceTarget": {"maxLevel": 1, "level": 1, "sequenceId": "seq_0002"},
    })
    monkeypatch.setattr(check_model, "load_runtime_meta", lambda _workspace: {
        "model_workspace_dir": str(model_workspace),
        "run_config_dir": str(tmp_path / "config"),
        "run_bin_dir": str(tmp_path / "bin"),
        "game_id": "ls20",
    })

    calls: list[tuple[int | None, str | None]] = []

    def fake_run_compare(_workspace, _meta, _env, frontier_level=None, sequence_id=None, *, include_reset_ended=False):
        calls.append((frontier_level, sequence_id))
        if sequence_id == "seq_0002":
            return 0, {
                "ok": True,
                "action": "compare_sequences",
                "level": 1,
                "all_match": True,
                "requested_sequences": 1,
                "eligible_sequences": 1,
                "compared_sequences": 1,
                "diverged_sequences": 0,
                "reports": [
                    {
                        "level": 1,
                        "sequence_id": "seq_0002",
                        "matched": True,
                    }
                ],
            }
        return 0, {
            "ok": True,
            "action": "compare_sequences",
            "level": 1,
            "all_match": True,
            "requested_sequences": 1,
            "eligible_sequences": 1,
            "compared_sequences": 1,
            "diverged_sequences": 0,
            "reports": [
                {
                    "level": 1,
                    "sequence_id": "seq_0002",
                    "matched": True,
                }
            ],
        }

    payloads: list[dict] = []
    monkeypatch.setattr(check_model, "_run_compare", fake_run_compare)
    monkeypatch.setattr(check_model, "write_json_stdout", lambda payload: payloads.append(payload))

    check_model.main()

    assert calls == [(1, "seq_0002"), (1, None)]
    assert payloads
    assert payloads[0]["accepted"] is True


def test_check_model_accepts_requested_level_batch_without_comparing_later_levels(tmp_path, monkeypatch) -> None:
    _load_module("common", "scripts/flux/common.py")
    check_model = _load_module("flux_check_model_level_batch_test", "scripts/flux/check_model.py")
    model_workspace = tmp_path / "agent" / "game_ls20"
    (model_workspace / "model.py").parent.mkdir(parents=True, exist_ok=True)
    (model_workspace / "model.py").write_text("# stub\n", encoding="utf-8")
    for level in (1, 2):
        seq_dir = model_workspace / f"level_{level}" / "sequences"
        seq_dir.mkdir(parents=True, exist_ok=True)
        (seq_dir / "seq_0001.json").write_text(json.dumps({"level": level, "sequence_id": "seq_0001"}, indent=2) + "\n", encoding="utf-8")

    bundle_root = _ready_evidence_bundle(tmp_path, "game_ls20")
    monkeypatch.setattr(check_model, "read_json_stdin", lambda: {
        "workspaceRoot": str(tmp_path),
        "modelOutput": {"summary": "accepted"},
        "evidenceBundlePath": str(bundle_root),
        "acceptanceTarget": {"maxLevel": 1, "level": 1},
    })
    monkeypatch.setattr(check_model, "load_runtime_meta", lambda _workspace: {
        "model_workspace_dir": str(model_workspace),
        "run_config_dir": str(tmp_path / "config"),
        "run_bin_dir": str(tmp_path / "bin"),
        "game_id": "ls20",
    })

    calls: list[tuple[int | None, str | None]] = []

    def fake_run_compare(_workspace, _meta, _env, frontier_level=None, sequence_id=None, *, include_reset_ended=False):
        calls.append((frontier_level, sequence_id))
        if frontier_level == 1:
            return 0, {
                "ok": True,
                "action": "compare_sequences",
                "level": 1,
                "frontier_level": 1,
                "requested_sequences": 1,
                "eligible_sequences": 1,
                "compared_sequences": 1,
                "diverged_sequences": 0,
                "all_match": True,
                "reports": [
                    {
                        "level": 1,
                        "sequence_id": "seq_0001",
                        "matched": True,
                    }
                ],
            }
        raise AssertionError("later levels should not be compared when batching the requested level")

    payloads: list[dict] = []
    monkeypatch.setattr(check_model, "_run_compare", fake_run_compare)
    monkeypatch.setattr(check_model, "write_json_stdout", lambda payload: payloads.append(payload))

    check_model.main()

    assert calls == [(1, None)]
    assert payloads
    assert payloads[0]["accepted"] is True
    assert payloads[0]["compare_payload"]["level"] == 1


def test_check_model_batches_previous_levels_through_requested_level_only(tmp_path, monkeypatch) -> None:
    _load_module("common", "scripts/flux/common.py")
    check_model = _load_module("flux_check_model_batched_levels_test", "scripts/flux/check_model.py")
    model_workspace = tmp_path / "agent" / "game_ls20"
    (model_workspace / "model.py").parent.mkdir(parents=True, exist_ok=True)
    (model_workspace / "model.py").write_text("# stub\n", encoding="utf-8")
    for level in (1, 2, 3):
        seq_dir = model_workspace / f"level_{level}" / "sequences"
        seq_dir.mkdir(parents=True, exist_ok=True)
        (seq_dir / "seq_0001.json").write_text(json.dumps({"level": level, "sequence_id": "seq_0001"}, indent=2) + "\n", encoding="utf-8")

    bundle_root = _ready_evidence_bundle(tmp_path, "game_ls20")
    monkeypatch.setattr(check_model, "read_json_stdin", lambda: {
        "workspaceRoot": str(tmp_path),
        "modelOutput": {"summary": "accepted"},
        "evidenceBundlePath": str(bundle_root),
        "acceptanceTarget": {"maxLevel": 2, "level": 2},
    })
    monkeypatch.setattr(check_model, "load_runtime_meta", lambda _workspace: {
        "model_workspace_dir": str(model_workspace),
        "run_config_dir": str(tmp_path / "config"),
        "run_bin_dir": str(tmp_path / "bin"),
        "game_id": "ls20",
    })

    calls: list[tuple[int | None, str | None]] = []

    def fake_run_compare(_workspace, _meta, _env, frontier_level=None, sequence_id=None, *, include_reset_ended=False):
        calls.append((frontier_level, sequence_id))
        return 0, {
            "ok": True,
            "action": "compare_sequences",
            "level": frontier_level,
            "frontier_level": frontier_level,
            "requested_sequences": 1,
            "eligible_sequences": 1,
            "compared_sequences": 1,
            "diverged_sequences": 0,
            "all_match": True,
            "reports": [
                {
                    "level": frontier_level,
                    "sequence_id": "seq_0001",
                    "matched": True,
                }
            ],
        }

    payloads: list[dict] = []
    monkeypatch.setattr(check_model, "_run_compare", fake_run_compare)
    monkeypatch.setattr(check_model, "write_json_stdout", lambda payload: payloads.append(payload))

    check_model.main()

    assert calls == [(1, None), (2, None)]
    assert payloads
    assert payloads[0]["accepted"] is True
