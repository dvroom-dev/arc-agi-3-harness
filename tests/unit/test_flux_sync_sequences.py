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


def test_sync_latest_attempt_to_model_workspace_prefers_canonical_game_artifacts_over_agent_surface(tmp_path: Path) -> None:
    common = _load_module("flux_common_canonical_sync_test", "scripts/flux/common.py")
    workspace_root = tmp_path / "run"
    attempts_root = workspace_root / "flux_instances"
    solver_name = "game_ls20"

    active = attempts_root / "attempt_live"
    active_solver = active / "agent" / solver_name
    active_state = active / "supervisor" / "arc"
    canonical_level = active_state / "game_artifacts" / "game_ls20-abc123" / "level_1" / "sequences"
    agent_level = active_solver / "level_1" / "sequences"
    canonical_level.mkdir(parents=True, exist_ok=True)
    agent_level.mkdir(parents=True, exist_ok=True)
    workspace_root.joinpath("flux").mkdir(parents=True, exist_ok=True)
    (workspace_root / "flux" / "state.json").write_text(
        json.dumps({"active": {"solver": {"instanceId": "attempt_live", "status": "running"}}}) + "\n",
        encoding="utf-8",
    )

    canonical_seq = {
        "level": 1,
        "sequence_id": "seq_0001",
        "sequence_number": 1,
        "start_action_index": 1,
        "end_action_index": 4,
        "end_reason": "reset_level",
        "action_count": 3,
        "actions": [
            {"local_step": 1, "action_index": 1, "action_name": "ACTION1", "state_before": "NOT_FINISHED", "state_after": "NOT_FINISHED", "level_before": 1, "level_after": 1, "levels_completed_before": 0, "levels_completed_after": 0, "files": {"meta_json": "sequences/seq_0001/actions/step_0001_action_000001_action1/meta.json"}},
            {"local_step": 2, "action_index": 2, "action_name": "ACTION2", "state_before": "NOT_FINISHED", "state_after": "NOT_FINISHED", "level_before": 1, "level_after": 1, "levels_completed_before": 0, "levels_completed_after": 0, "files": {"meta_json": "sequences/seq_0001/actions/step_0002_action_000002_action2/meta.json"}},
            {"local_step": 3, "action_index": 3, "action_name": "ACTION3", "state_before": "NOT_FINISHED", "state_after": "NOT_FINISHED", "level_before": 1, "level_after": 1, "levels_completed_before": 0, "levels_completed_after": 0, "files": {"meta_json": "sequences/seq_0001/actions/step_0003_action_000003_action3/meta.json"}},
        ],
    }
    stale_agent_seq = {
        "level": 1,
        "sequence_id": "seq_0001",
        "sequence_number": 1,
        "start_action_index": 45,
        "end_action_index": 46,
        "end_reason": "reset_level",
        "action_count": 1,
        "actions": [
            {"local_step": 1, "action_index": 45, "action_name": "ACTION1", "state_before": "NOT_FINISHED", "state_after": "NOT_FINISHED", "level_before": 1, "level_after": 1, "levels_completed_before": 0, "levels_completed_after": 0, "files": {"meta_json": "sequences/seq_0001/actions/step_0001_action_000045_action1/meta.json"}},
        ],
    }
    (canonical_level / "seq_0001.json").write_text(json.dumps(canonical_seq, indent=2) + "\n", encoding="utf-8")
    (agent_level / "seq_0001.json").write_text(json.dumps(stale_agent_seq, indent=2) + "\n", encoding="utf-8")
    for rel in [
        "seq_0001/actions/step_0001_action_000001_action1/meta.json",
        "seq_0001/actions/step_0002_action_000002_action2/meta.json",
        "seq_0001/actions/step_0003_action_000003_action3/meta.json",
    ]:
        path = canonical_level / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")
    stale_meta = agent_level / "seq_0001" / "actions" / "step_0001_action_000045_action1" / "meta.json"
    stale_meta.parent.mkdir(parents=True, exist_ok=True)
    stale_meta.write_text("{}\n", encoding="utf-8")

    model_workspace = workspace_root / "agent" / solver_name
    meta = {
        "model_workspace_dir": str(model_workspace),
        "solver_template_dir": str(workspace_root / "flux_seed" / "agent" / solver_name),
    }

    common.sync_latest_attempt_to_model_workspace(str(workspace_root), meta)

    synced = json.loads((model_workspace / "level_1" / "sequences" / "seq_0001.json").read_text())
    assert synced["start_action_index"] == 1
    assert synced["action_count"] == 3
    assert [action["action_index"] for action in synced["actions"]] == [1, 2, 3]
