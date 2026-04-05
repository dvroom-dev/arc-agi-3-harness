from __future__ import annotations

import importlib.util
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


def test_check_model_classifies_missing_sequence_frame_as_infrastructure_failure(tmp_path, monkeypatch) -> None:
    _load_module("common", "scripts/flux/common.py")
    check_model = _load_module("flux_check_model_missing_frame_test", "scripts/flux/check_model.py")
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
