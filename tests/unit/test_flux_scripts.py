from __future__ import annotations

import importlib.util
import json
import shutil
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
