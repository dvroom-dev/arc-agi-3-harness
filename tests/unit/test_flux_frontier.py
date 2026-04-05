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
