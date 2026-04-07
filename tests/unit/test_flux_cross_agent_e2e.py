from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


def test_sync_model_workspace_script_prefers_canonical_solver_sequences(tmp_path: Path) -> None:
    workspace_root = tmp_path / "run"
    solver_name = "game_ls20"
    attempt_root = workspace_root / "flux_instances" / "attempt_live"
    agent_surface = attempt_root / "agent" / solver_name / "level_1" / "sequences"
    canonical_surface = attempt_root / "supervisor" / "arc" / "game_artifacts" / "game_ls20-abc123" / "level_1" / "sequences"
    model_workspace = workspace_root / "agent" / solver_name
    runtime_meta_path = workspace_root / "flux_runtime.json"

    agent_surface.mkdir(parents=True, exist_ok=True)
    canonical_surface.mkdir(parents=True, exist_ok=True)
    model_workspace.mkdir(parents=True, exist_ok=True)
    (workspace_root / "flux").mkdir(parents=True, exist_ok=True)
    (workspace_root / "flux" / "state.json").write_text(
        json.dumps({"active": {"solver": {"instanceId": "attempt_live", "status": "running"}}}, indent=2) + "\n",
        encoding="utf-8",
    )
    runtime_meta_path.write_text(
        json.dumps(
            {
                "solver_template_dir": str(workspace_root / "flux_seed" / "agent" / solver_name),
                "model_workspace_dir": str(model_workspace),
                "game_id": "ls20",
                "run_config_dir": str(workspace_root / "config"),
                "run_bin_dir": str(workspace_root / "config" / "bin"),
            },
            indent=2,
        )
        + "\n",
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
            {
                "local_step": 1,
                "action_index": 1,
                "action_name": "ACTION1",
                "state_before": "NOT_FINISHED",
                "state_after": "NOT_FINISHED",
                "level_before": 1,
                "level_after": 1,
                "levels_completed_before": 0,
                "levels_completed_after": 0,
                "files": {"meta_json": "sequences/seq_0001/actions/step_0001_action_000001_action1/meta.json"},
            },
            {
                "local_step": 2,
                "action_index": 2,
                "action_name": "ACTION2",
                "state_before": "NOT_FINISHED",
                "state_after": "NOT_FINISHED",
                "level_before": 1,
                "level_after": 1,
                "levels_completed_before": 0,
                "levels_completed_after": 0,
                "files": {"meta_json": "sequences/seq_0001/actions/step_0002_action_000002_action2/meta.json"},
            },
            {
                "local_step": 3,
                "action_index": 3,
                "action_name": "ACTION3",
                "state_before": "NOT_FINISHED",
                "state_after": "NOT_FINISHED",
                "level_before": 1,
                "level_after": 1,
                "levels_completed_before": 0,
                "levels_completed_after": 0,
                "files": {"meta_json": "sequences/seq_0001/actions/step_0003_action_000003_action3/meta.json"},
            },
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
            {
                "local_step": 1,
                "action_index": 45,
                "action_name": "ACTION1",
                "state_before": "NOT_FINISHED",
                "state_after": "NOT_FINISHED",
                "level_before": 1,
                "level_after": 1,
                "levels_completed_before": 0,
                "levels_completed_after": 0,
                "files": {"meta_json": "sequences/seq_0001/actions/step_0001_action_000045_action1/meta.json"},
            }
        ],
    }
    (canonical_surface / "seq_0001.json").write_text(json.dumps(canonical_seq, indent=2) + "\n", encoding="utf-8")
    (agent_surface / "seq_0001.json").write_text(json.dumps(stale_agent_seq, indent=2) + "\n", encoding="utf-8")

    for rel in [
        "seq_0001/actions/step_0001_action_000001_action1/meta.json",
        "seq_0001/actions/step_0002_action_000002_action2/meta.json",
        "seq_0001/actions/step_0003_action_000003_action3/meta.json",
    ]:
        path = canonical_surface / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")
    stale_meta = agent_surface / "seq_0001" / "actions" / "step_0001_action_000045_action1" / "meta.json"
    stale_meta.parent.mkdir(parents=True, exist_ok=True)
    stale_meta.write_text("{}\n", encoding="utf-8")

    script_path = Path(__file__).resolve().parents[2] / "scripts" / "flux" / "sync_model_workspace.py"
    proc = subprocess.run(
        [str(Path(__file__).resolve().parents[2] / ".venv" / "bin" / "python"), str(script_path)],
        input=json.dumps({"workspaceRoot": str(workspace_root), "reason": "solver_new_evidence"}),
        text=True,
        capture_output=True,
        env={**os.environ, "ARC_FLUX_META_PATH": str(runtime_meta_path)},
        cwd=str(workspace_root),
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    payload = json.loads(proc.stdout)
    assert payload["count"] >= 1

    synced = json.loads((model_workspace / "level_1" / "sequences" / "seq_0001.json").read_text())
    assert synced["start_action_index"] == 1
    assert synced["action_count"] == 3
    assert [action["action_index"] for action in synced["actions"]] == [1, 2, 3]
