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


def test_check_model_accepts_frontier_discovery_when_prior_levels_match(tmp_path: Path, monkeypatch) -> None:
    _load_module("common", "scripts/flux/common.py")
    check_model = _load_module("flux_check_model_frontier_discovery_test", "scripts/flux/check_model.py")
    model_workspace = tmp_path / "agent" / "game_ls20"
    model_workspace.mkdir(parents=True, exist_ok=True)
    (model_workspace / "model.py").write_text("# stub\n", encoding="utf-8")
    level1_sequences = model_workspace / "level_1" / "sequences"
    level2_sequences = model_workspace / "level_2" / "sequences"
    level1_sequences.mkdir(parents=True, exist_ok=True)
    level2_sequences.mkdir(parents=True, exist_ok=True)
    (model_workspace / "level_current").mkdir(parents=True, exist_ok=True)
    (model_workspace / "level_current" / "meta.json").write_text(
        json.dumps({"schema_version": "arc_repl.level_current.v1", "level": 2}, indent=2) + "\n",
        encoding="utf-8",
    )
    (model_workspace / "level_1" / "initial_state.hex").write_text("0\n", encoding="utf-8")
    (model_workspace / "level_1" / "initial_state.meta.json").write_text("{}\n", encoding="utf-8")
    (model_workspace / "level_2" / "initial_state.hex").write_text("0\n", encoding="utf-8")
    (model_workspace / "level_2" / "initial_state.meta.json").write_text("{}\n", encoding="utf-8")
    (level1_sequences / "seq_0001.json").write_text(json.dumps({"level": 1, "sequence_id": "seq_0001"}, indent=2) + "\n", encoding="utf-8")
    (level2_sequences / "seq_0001.json").write_text(json.dumps({"level": 2, "sequence_id": "seq_0001"}, indent=2) + "\n", encoding="utf-8")

    monkeypatch.setattr(check_model, "read_json_stdin", lambda: {"workspaceRoot": str(tmp_path), "modelOutput": {}})
    monkeypatch.setattr(check_model, "load_runtime_meta", lambda _workspace: {
        "model_workspace_dir": str(model_workspace),
        "run_config_dir": str(tmp_path / "config"),
        "run_bin_dir": str(tmp_path / "bin"),
        "game_id": "ls20",
    })

    def fake_run_compare(_workspace, _meta, _env, frontier_level=None, *, include_reset_ended=False):
        if frontier_level == 1:
            return 0, {
                "ok": True,
                "action": "compare_sequences",
                "level": 1,
                "all_match": True,
                "eligible_sequences": 1,
                "compared_sequences": 1,
                "diverged_sequences": 0,
                "reports": [{"level": 1, "sequence_id": "seq_0001", "matched": True}],
            }
        return 1, {
            "ok": False,
            "action": "compare_sequences",
            "error": {"type": "no_eligible_sequences", "message": "frontier level has only open sequences"},
            "level": 2,
            "requested_sequences": 1,
            "eligible_sequences": 0,
            "skipped_sequences": [{"sequence_id": "seq_0001", "sequence_file": "seq_0001.json", "end_reason": "open", "reason": "wrong_level"}],
            "include_reset_ended": True,
            "include_level_regressions": False,
        }

    payloads: list[dict] = []
    monkeypatch.setattr(check_model, "_run_compare", fake_run_compare)
    monkeypatch.setattr(check_model, "write_json_stdout", lambda payload: payloads.append(payload))

    check_model.main()

    assert payloads
    assert payloads[0]["accepted"] is True
    assert payloads[0]["compare_payload"]["frontier_discovery"] is True
    assert payloads[0]["compare_payload"]["frontier_level"] == 2
