from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


def test_observe_evidence_script_filters_reset_records_from_visible_action_handoff(tmp_path: Path) -> None:
    workspace_root = tmp_path / "run"
    solver_dir = workspace_root / "flux_instances" / "attempt_x" / "agent" / "game_ls20" / "level_1" / "sequences" / "seq_0001"
    state_dir = workspace_root / "flux_instances" / "attempt_x" / "supervisor" / "arc"
    (solver_dir / "actions" / "step_0008_action_000008_action3").mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    (workspace_root / "flux").mkdir(parents=True, exist_ok=True)
    (solver_dir.parent / "seq_0001.json").write_text(
        json.dumps(
            {
                "level": 1,
                "sequence_id": "seq_0001",
                "actions": [
                    {
                        "action_index": 8,
                        "files": {"meta_json": "sequences/seq_0001/actions/step_0008_action_000008_action3/meta.json"},
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (solver_dir / "actions" / "step_0008_action_000008_action3" / "meta.json").write_text("{}\n", encoding="utf-8")
    (state_dir / "state.json").write_text(
        json.dumps({"current_level": 1, "levels_completed": 0, "state": "NOT_FINISHED", "total_steps": 8, "current_attempt_steps": 0}, indent=2) + "\n",
        encoding="utf-8",
    )
    (state_dir / "tool-engine-history.json").write_text(json.dumps({"events": [{"kind": "step"}] * 8 + [{"kind": "reset"}]}) + "\n", encoding="utf-8")
    records = [{"action_index": index + 1, "action_name": "ACTION1"} for index in range(8)]
    records.append({"action_index": 9, "action_name": "RESET_LEVEL", "call_action": "reset_level", "source": "reset_level"})
    (state_dir / "action-history.json").write_text(json.dumps({"records": records}, indent=2) + "\n", encoding="utf-8")
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
                        "solver_dir": str(solver_dir.parent.parent.parent),
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
    evidence = payload["evidence"][0]
    assert evidence["action_count"] == 8
    assert evidence["reset_action_count"] == 1
    assert "artifact_handoff_incomplete" not in evidence


def test_observe_evidence_script_uses_canonical_surface_after_level_transition(tmp_path: Path) -> None:
    workspace_root = tmp_path / "run"
    solver_dir = workspace_root / "flux_instances" / "attempt_x" / "agent" / "game_ls20"
    state_dir = workspace_root / "flux_instances" / "attempt_x" / "supervisor" / "arc"
    canonical_dir = state_dir / "game_artifacts" / "game_ls20-abc123" / "level_1" / "sequences" / "seq_0001"
    (solver_dir / "level_current").mkdir(parents=True, exist_ok=True)
    (solver_dir / "level_current" / "meta.json").write_text(json.dumps({"level": 2}) + "\n", encoding="utf-8")
    (solver_dir / "level_2").mkdir(parents=True, exist_ok=True)
    (solver_dir / "level_2" / "meta.json").write_text(json.dumps({"level": 2}) + "\n", encoding="utf-8")
    canonical_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    (workspace_root / "flux").mkdir(parents=True, exist_ok=True)
    (canonical_dir.parent / "seq_0001.json").write_text(
        json.dumps(
            {
                "level": 1,
                "sequence_id": "seq_0001",
                "actions": [
                    {
                        "action_index": 21,
                        "files": {"meta_json": "sequences/seq_0001/actions/step_0021_action_000021_action1/meta.json"},
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (canonical_dir / "actions" / "step_0021_action_000021_action1").mkdir(parents=True, exist_ok=True)
    (canonical_dir / "actions" / "step_0021_action_000021_action1" / "meta.json").write_text("{}\n", encoding="utf-8")
    (state_dir / "state.json").write_text(
        json.dumps({"current_level": 2, "levels_completed": 1, "state": "NOT_FINISHED", "total_steps": 21, "current_attempt_steps": 1}, indent=2) + "\n",
        encoding="utf-8",
    )
    (state_dir / "tool-engine-history.json").write_text(json.dumps({"events": [{"kind": "step"}] * 21}) + "\n", encoding="utf-8")
    (state_dir / "action-history.json").write_text(
        json.dumps({"records": [{"action_index": index + 1, "action_name": "ACTION1"} for index in range(21)]}, indent=2) + "\n",
        encoding="utf-8",
    )
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
    evidence = payload["evidence"][0]
    assert evidence["action_count"] == 21
    assert evidence["visible_action_count"] == 21
    assert evidence["latest_visible_action_dir"].endswith("step_0021_action_000021_action1")
    assert "artifact_handoff_incomplete" not in evidence
    bundle_path = Path(str(payload["evidence_bundle_path"]))
    assert (bundle_path / "workspace" / "game_ls20" / "level_1" / "sequences" / "seq_0001.json").exists()
