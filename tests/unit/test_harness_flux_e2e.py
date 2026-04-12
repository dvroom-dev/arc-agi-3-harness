from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
import pytest

from harness_flux import _launch_flux


@pytest.mark.skip(reason="stale mocked flux launcher flow superseded by real-filesystem orchestrator e2e coverage in super")
def test_launch_flux_mocked_end_to_end_flow_retries_bootstrap_until_seed_rev_solver(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    prompts_dir = run_dir / "prompts"
    scripts_dir = run_dir / "scripts"
    model_workspace = run_dir / "model_workspace"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    scripts_dir.mkdir(parents=True, exist_ok=True)
    model_workspace.mkdir(parents=True, exist_ok=True)

    (prompts_dir / "solver.md").write_text("SOLVER_PROMPT", encoding="utf-8")
    (prompts_dir / "modeler.md").write_text("MODELER_PROMPT", encoding="utf-8")
    (prompts_dir / "bootstrapper.md").write_text("BOOTSTRAP_PROMPT", encoding="utf-8")
    (prompts_dir / "modeler_continue.md").write_text("Continue model.", encoding="utf-8")
    (prompts_dir / "bootstrapper_continue.md").write_text("Continue bootstrap.", encoding="utf-8")

    def write_script(name: str, body: str) -> Path:
        path = scripts_dir / name
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)
        return path

    provision = write_script(
        "provision.py",
        """#!/usr/bin/env python3
import json, sys
payload = json.load(sys.stdin)
instance_id = payload.get("seedRevisionId") or payload.get("attemptId") or "instance_1"
workspace_root = payload.get("workspaceRoot")
print(json.dumps({
  "instance_id": instance_id,
  "working_directory": workspace_root,
  "prompt_text": "Puzzle context",
  "env": {},
  "metadata": {"state_dir": workspace_root, "solver_dir": workspace_root},
}))
""",
    )
    destroy = write_script(
        "destroy.py",
        """#!/usr/bin/env python3
import json, sys
json.load(sys.stdin)
print("{}")
""",
    )
    observe = write_script(
        "observe.py",
        """#!/usr/bin/env python3
import json, sys
payload = json.load(sys.stdin)
instance = payload.get("instance") or {}
instance_id = str(instance.get("instance_id") or "instance_1")
preplayed = instance_id.startswith("seed_rev_")
state = {
  "current_level": 3 if preplayed else 1,
  "levels_completed": 2 if preplayed else 0,
  "win_levels": 7,
  "state": "WIN" if preplayed else "NOT_FINISHED",
  "total_steps": 25 if preplayed else 1,
  "current_attempt_steps": 0 if preplayed else 1,
  "last_action_name": "ACTION1",
}
print(json.dumps({
  "evidence": [{
    "summary": "preplayed frontier" if preplayed else "solver evidence",
    "action_count": 25 if preplayed else 1,
    "changed_pixels": 1,
    "state": state,
  }]
}))
""",
    )
    sync = write_script(
        "sync.py",
        """#!/usr/bin/env python3
import json, sys
payload = json.load(sys.stdin)
print(json.dumps({"synced": True, "reason": payload.get("reason", "")}))
""",
    )
    rehearse = write_script(
        "rehearse.py",
        """#!/usr/bin/env python3
import json
import sys
from pathlib import Path

payload = json.load(sys.stdin)
workspace_root = Path(payload["workspaceRoot"])
seed_path = workspace_root / "flux" / "seed" / "candidate.json"
counter_path = workspace_root / "flux" / "seed" / "rehearsal_count.txt"
count = int(counter_path.read_text(encoding="utf-8") or "0") if counter_path.exists() else 0
count += 1
counter_path.write_text(str(count), encoding="utf-8")

if count == 1:
    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    seed["generatedAt"] = "2026-04-05T00:39:30Z"
    seed["syntheticMessages"] = [{"role": "assistant", "text": "Retry 1 frontier seed"}]
    seed["replayPlan"] = [{"tool": "shell", "args": {"cmd": ["arc_action", "ACTION1"]}}]
    seed["assertions"] = ["retry-1"]
    seed_path.write_text(json.dumps(seed, indent=2) + "\\n", encoding="utf-8")
    print(json.dumps({
      "rehearsal_ok": False,
      "status_before": {"current_level": 1, "levels_completed": 0, "state": "NOT_FINISHED", "win_levels": 7},
      "status_after": {"current_level": 2, "levels_completed": 1, "state": "NOT_FINISHED", "win_levels": 7},
      "error": {"type": "missing_next_level_initial_state", "message": "missing initial_state.hex for level 3; discovered initial states [1, 2]"},
      "tool_results": []
    }))
elif count == 2:
    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    seed["generatedAt"] = "2026-04-05T00:40:30Z"
    seed["syntheticMessages"] = [{"role": "assistant", "text": "Retry 2 frontier seed"}]
    seed["replayPlan"] = [{"tool": "shell", "args": {"cmd": ["arc_action", "ACTION1"]}}]
    seed["assertions"] = ["retry-2"]
    seed_path.write_text(json.dumps(seed, indent=2) + "\\n", encoding="utf-8")
    print(json.dumps({
      "rehearsal_ok": False,
      "status_before": {"current_level": 1, "levels_completed": 0, "state": "NOT_FINISHED", "win_levels": 7},
      "status_after": {"current_level": 2, "levels_completed": 1, "state": "NOT_FINISHED", "win_levels": 7},
      "error": {"type": "missing_next_level_initial_state", "message": "missing initial_state.hex for level 3; discovered initial states [1, 2]"},
      "tool_results": []
    }))
else:
    print(json.dumps({
      "rehearsal_ok": True,
      "status_before": {"current_level": 1, "levels_completed": 0, "state": "NOT_FINISHED", "win_levels": 7},
      "status_after": {"current_level": 2, "levels_completed": 1, "state": "NOT_FINISHED", "win_levels": 7},
      "compare_payload": {
        "ok": True,
        "action": "compare_sequences",
        "level": 2,
        "all_match": True,
        "compared_sequences": 1,
        "eligible_sequences": 1,
        "diverged_sequences": 0,
        "reports": [{"sequence_id": "seq_0001", "matched": True, "report_file": "level_2/report.md"}]
      },
      "tool_results": []
    }))
""",
    )
    replay = write_script(
        "replay.py",
        """#!/usr/bin/env python3
import json, sys
payload = json.load(sys.stdin)
print(json.dumps({
  "replay_ok": True,
  "tool_results": [],
  "evidence": [{
    "summary": "preplayed frontier",
    "state": {
      "current_level": 2,
      "levels_completed": 1,
      "win_levels": 7,
      "state": "NOT_FINISHED",
      "total_steps": 17,
      "current_attempt_steps": 0,
      "last_action_name": "ACTION1"
    }
  }],
  "instance": payload.get("instance") or {}
}))
""",
    )
    acceptance = write_script(
        "accept.py",
        """#!/usr/bin/env python3
import json, sys
payload = json.load(sys.stdin)
model_output = payload.get("modelOutput") or {}
print(json.dumps({
  "accepted": True,
  "message": model_output.get("summary") or "accepted",
  "compare_payload": {
    "level": 1,
    "all_match": True,
    "compared_sequences": 1,
    "diverged_sequences": 0,
    "reports": [{"level": 1, "sequence_id": "seq_0001", "matched": True, "frontier_level_after_sequence": 2, "sequence_completed_level": True}]
  },
  "model_output": model_output
}))
""",
    )

    (run_dir / "flux" / "seed").mkdir(parents=True, exist_ok=True)
    (run_dir / "flux" / "seed" / "current.json").write_text(
        json.dumps(
            {
                "version": 1,
                "generatedAt": "2026-04-05T00:37:00Z",
                "syntheticMessages": [{"role": "assistant", "text": "Initial overlong frontier seed"}],
                "replayPlan": [],
                "assertions": ["initial-overreach"],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "level_1" / "sequences").mkdir(parents=True, exist_ok=True)
    (run_dir / "level_1" / "sequences" / "seq_0001.json").write_text(
        json.dumps({"level": 1, "sequence_id": "seq_0001"}, indent=2) + "\n",
        encoding="utf-8",
    )

    (run_dir / "flux.yaml").write_text(
        f"""
schema_version: 1
runtime_defaults:
  provider: mock
  model: mock-model
  env: {{}}
storage:
  flux_root: flux
  ai_root: .ai-flux
orchestrator:
  tick_ms: 10
  solver_preempt_grace_ms: 10
  evidence_poll_ms: 10
  modeler_idle_backoff_ms: 10
  bootstrapper_idle_backoff_ms: 10
problem:
  provision_instance:
    command: ["{provision}"]
  destroy_instance:
    command: ["{destroy}"]
  observe_evidence:
    command: ["{observe}"]
  sync_model_workspace:
    command: ["{sync}"]
  rehearse_seed_on_model:
    command: ["{rehearse}"]
  replay_seed_on_real_game:
    command: ["{replay}"]
  merge_evidence:
    strategy: dedupe_by_fingerprint
solver:
  prompt_file: prompts/solver.md
  session_scope: per_attempt
  resume_policy: never
  cadence_ms: 10
  queue_replacement_grace_ms: 10
  tools:
    builtin: [shell]
modeler:
  prompt_file: prompts/modeler.md
  working_directory: model_workspace
  session_scope: run
  resume_policy: always
  triggers:
    on_new_evidence: true
    on_solver_stopped: true
    periodic_ms: 10
  output_schema: model_update_v1
  acceptance:
    command: ["{acceptance}"]
    parse_as: json
    continue_message_template_file: prompts/modeler_continue.md
bootstrapper:
  prompt_file: prompts/bootstrapper.md
  session_scope: run
  resume_policy: always
  output_schema: bootstrap_seed_decision_v1
  seed_bundle_path: flux/seed/current.json
  require_model_rehearsal_before_finalize: true
  replay:
    max_attempts_per_event: 1
    continue_message_template_file: prompts/bootstrapper_continue.md
observability:
  capture_prompts: true
  capture_raw_provider_events: true
  capture_tool_calls: true
  capture_tool_results: true
  capture_queue_snapshots: true
  capture_timing_metrics: true
retention:
  keep_all_events: true
  keep_all_sessions: true
  keep_all_attempts: true
""".strip()
        + "\n",
        encoding="utf-8",
    )

    runtime = SimpleNamespace(
        run_dir=run_dir,
        super_env={
            **os.environ,
            "MOCK_PROVIDER_STREAMED_TEXT": "solver output",
            "MOCK_PROVIDER_STREAMED_MATCHERS_JSON": json.dumps(
                [
                    {
                        "contains": "BOOTSTRAP_PROMPT",
                        "text": json.dumps(
                            {
                                "decision": "finalize_seed",
                                "summary": "seed is ready",
                                "seed_bundle_updated": True,
                                "notes": "finalize best known seed",
                                "solver_action": "queue_and_interrupt",
                                "seed_delta_kind": "level_completion_advanced",
                            }
                        ),
                    }
                ]
            ),
            "MOCK_PROVIDER_DELAY_MS": "10",
        },
        log=lambda _message: None,
    )

    rc = _launch_flux(runtime, run_dir / "flux.yaml")
    assert rc == 0

    event_rows = [
        json.loads(line)
        for line in (run_dir / "flux" / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert sum(1 for row in event_rows if row["kind"] == "bootstrapper.model_rehearsal_started") == 3
    assert sum(1 for row in event_rows if row["kind"] == "bootstrapper.model_rehearsal_failed") == 2
    assert sum(1 for row in event_rows if row["kind"] == "bootstrapper.model_rehearsal_passed") == 1
    assert sum(1 for row in event_rows if row["kind"] == "bootstrapper.auto_accepted_after_rehearsal") == 1
    assert sum(1 for row in event_rows if row["kind"] == "bootstrapper.real_replay_passed") == 1
    assert sum(1 for row in event_rows if row["kind"] == "bootstrapper.attested_satisfactory") == 1
    assert any(
        row["kind"] == "solver.instance_provisioned"
        and str((row.get("payload") or {}).get("instanceId", "")).startswith("seed_rev_")
        for row in event_rows
    )

    state = json.loads((run_dir / "flux" / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "stopped"

    revisions = sorted((run_dir / "flux" / "seed" / "revisions").glob("seed_rev_*.json"))
    assert len(revisions) == 3
    assert any("Retry 2 frontier seed" in path.read_text(encoding="utf-8") for path in revisions)

    solver_sessions = sorted((run_dir / ".ai-flux" / "sessions" / "solver").glob("solver_attempt_*/messages.jsonl"))
    assert len(solver_sessions) >= 2
    replacement_messages = [path.read_text(encoding="utf-8") for path in solver_sessions]
    assert any("Seed preplay already ran on this instance." in text for text in replacement_messages)
    assert any("Current live state after preplay: level 2" in text for text in replacement_messages)
    solver_prompt_payloads = []
    for prompts_dir in sorted((run_dir / ".ai-flux" / "sessions" / "solver").glob("solver_attempt_*/prompts")):
        for prompt_path in sorted(prompts_dir.glob("turn_*.json")):
            solver_prompt_payloads.append(json.loads(prompt_path.read_text(encoding="utf-8")))
    assert any("Retry 2 frontier seed" in str(payload.get("promptText", "")) for payload in solver_prompt_payloads)
    assert any("Synthetic transcript to inherit:" in str(payload.get("promptText", "")) for payload in solver_prompt_payloads)


@pytest.mark.skip(reason="stale mocked flux launcher flow superseded by real-filesystem orchestrator e2e coverage in super")
def test_launch_flux_mocked_end_to_end_flow_retries_modeler_then_bootstraps_and_preempts_solver(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    prompts_dir = run_dir / "prompts"
    scripts_dir = run_dir / "scripts"
    model_workspace = run_dir / "model_workspace"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    scripts_dir.mkdir(parents=True, exist_ok=True)
    model_workspace.mkdir(parents=True, exist_ok=True)

    (prompts_dir / "solver.md").write_text("SOLVER_PROMPT", encoding="utf-8")
    (prompts_dir / "modeler.md").write_text("MODELER_PROMPT", encoding="utf-8")
    (prompts_dir / "bootstrapper.md").write_text("BOOTSTRAP_PROMPT", encoding="utf-8")
    (prompts_dir / "modeler_continue.md").write_text("Continue model: {{acceptance_message}}", encoding="utf-8")
    (prompts_dir / "bootstrapper_continue.md").write_text("Continue bootstrap.", encoding="utf-8")

    def write_script(name: str, body: str) -> Path:
        path = scripts_dir / name
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)
        return path

    provision = write_script(
        "provision.py",
        """#!/usr/bin/env python3
import json, sys
payload = json.load(sys.stdin)
instance_id = payload.get("seedRevisionId") or payload.get("attemptId") or "instance_1"
workspace_root = payload.get("workspaceRoot")
print(json.dumps({
  "instance_id": instance_id,
  "working_directory": workspace_root,
  "prompt_text": "Puzzle context",
  "env": {},
  "metadata": {"state_dir": workspace_root, "solver_dir": workspace_root},
}))
""",
    )
    destroy = write_script(
        "destroy.py",
        """#!/usr/bin/env python3
import json, sys
json.load(sys.stdin)
print("{}")
""",
    )
    observe = write_script(
        "observe.py",
        """#!/usr/bin/env python3
import json
import sys
from pathlib import Path

payload = json.load(sys.stdin)
workspace_root = Path(payload["workspaceRoot"])
instance = payload.get("instance") or {}
instance_id = str(instance.get("instance_id") or "instance_1")
counter_path = workspace_root / "flux" / f"observe_{instance_id}.txt"
count = int(counter_path.read_text(encoding="utf-8") or "0") if counter_path.exists() else 0
count += 1
counter_path.parent.mkdir(parents=True, exist_ok=True)
counter_path.write_text(str(count), encoding="utf-8")
preplayed = instance_id.startswith("seed_rev_")
if preplayed:
    print(json.dumps({
      "evidence": [{
        "summary": "replacement solver reached solved frontier",
        "action_count": 25,
        "changed_pixels": 1,
        "state": {
          "current_level": 2,
          "levels_completed": 2,
          "win_levels": 2,
          "state": "WIN",
          "total_steps": 25,
          "current_attempt_steps": 0,
          "last_action_name": "ACTION1"
        }
      }],
      "evidence_bundle_id": "bundle_replacement",
      "evidence_bundle_path": str(workspace_root / "flux" / "evidence_bundles" / "bundle_replacement"),
    }))
else:
    print(json.dumps({
      "evidence": [{
        "summary": "solver found one real opening action",
        "action_count": 1,
        "changed_pixels": 1,
        "state": {
          "current_level": 1,
          "levels_completed": 0,
          "win_levels": 2,
          "state": "NOT_FINISHED",
          "total_steps": 1,
          "current_attempt_steps": 1,
          "last_action_name": "ACTION1"
        }
      }],
      "evidence_bundle_id": "bundle_initial",
      "evidence_bundle_path": str(workspace_root / "flux" / "evidence_bundles" / "bundle_initial"),
    }))
""",
    )
    sync = write_script(
        "sync.py",
        """#!/usr/bin/env python3
import json, sys
payload = json.load(sys.stdin)
print(json.dumps({"synced": True, "reason": payload.get("reason", "")}))
""",
    )
    rehearse = write_script(
        "rehearse.py",
        """#!/usr/bin/env python3
import json, sys
json.load(sys.stdin)
print(json.dumps({
  "rehearsal_ok": True,
  "status_before": {"current_level": 1, "levels_completed": 0, "state": "NOT_FINISHED", "win_levels": 2},
  "status_after": {"current_level": 2, "levels_completed": 1, "state": "NOT_FINISHED", "win_levels": 2},
  "compare_payload": {
    "ok": True,
    "action": "compare_sequences",
    "level": 2,
    "frontier_level": 2,
    "all_match": True,
    "compared_sequences": 1,
    "eligible_sequences": 1,
    "diverged_sequences": 0,
    "reports": [{"level": 2, "sequence_id": "seq_0001", "matched": True, "report_file": "level_2/report.md"}]
  },
  "tool_results": []
}))
""",
    )
    replay = write_script(
        "replay.py",
        """#!/usr/bin/env python3
import json, sys
payload = json.load(sys.stdin)
print(json.dumps({
  "replay_ok": True,
  "tool_results": [],
  "evidence": [{
    "summary": "preplayed frontier",
    "state": {
      "current_level": 2,
      "levels_completed": 1,
      "win_levels": 2,
      "state": "NOT_FINISHED",
      "total_steps": 17,
      "current_attempt_steps": 0,
      "last_action_name": "ACTION1"
    }
  }],
  "instance": payload.get("instance") or {}
}))
""",
    )
    acceptance = write_script(
        "accept.py",
        """#!/usr/bin/env python3
import json
import sys
from pathlib import Path

payload = json.load(sys.stdin)
model_output = payload.get("modelOutput") or {}
workspace_root = Path(payload["workspaceRoot"])
counter_path = workspace_root / "flux" / "acceptance_count.txt"
if model_output.get("decision") == "checked_current_model":
    print(json.dumps({
      "accepted": False,
      "message": "compare mismatch at level 1 sequence seq_0001 step 2: intermediate_frame_mismatch",
      "compare_payload": {
        "level": 1,
        "all_match": False,
        "compared_sequences": 1,
        "diverged_sequences": 1,
        "reports": [{"sequence_id": "seq_0001", "matched": False, "divergence_step": 2, "divergence_reason": "intermediate_frame_mismatch"}]
      },
      "model_output": model_output
    }))
    raise SystemExit(0)

count = int(counter_path.read_text(encoding="utf-8") or "0") if counter_path.exists() else 0
count += 1
counter_path.parent.mkdir(parents=True, exist_ok=True)
counter_path.write_text(str(count), encoding="utf-8")
if count == 1:
    print(json.dumps({
      "accepted": False,
      "message": "compare mismatch at level 1 sequence seq_0001 step 2: intermediate_frame_mismatch",
      "compare_payload": {
        "level": 1,
        "all_match": False,
        "compared_sequences": 1,
        "diverged_sequences": 1,
        "reports": [{"sequence_id": "seq_0001", "matched": False, "divergence_step": 2, "divergence_reason": "intermediate_frame_mismatch"}]
      },
      "model_output": model_output
    }))
else:
    print(json.dumps({
      "accepted": True,
      "message": model_output.get("summary") or "accepted",
      "compare_payload": {
        "level": 1,
        "frontier_level": 1,
        "all_match": True,
        "compared_sequences": 1,
        "eligible_sequences": 1,
        "diverged_sequences": 0,
        "reports": [{"level": 1, "sequence_id": "seq_0001", "matched": True, "frontier_level_after_sequence": 2, "sequence_completed_level": True}]
      },
      "model_output": model_output
    }))
""",
    )

    (run_dir / "flux" / "seed").mkdir(parents=True, exist_ok=True)
    (run_dir / "flux" / "seed" / "current.json").write_text(
        json.dumps(
            {
                "version": 1,
                "generatedAt": "2026-04-05T00:37:00Z",
                "syntheticMessages": [{"role": "assistant", "text": "Initial seed knowledge"}],
                "replayPlan": [],
                "assertions": ["initial-seed"],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "level_1" / "sequences").mkdir(parents=True, exist_ok=True)
    (run_dir / "level_1" / "sequences" / "seq_0001.json").write_text(
        json.dumps({"level": 1, "sequence_id": "seq_0001"}, indent=2) + "\n",
        encoding="utf-8",
    )

    (run_dir / "flux.yaml").write_text(
        f"""
schema_version: 1
runtime_defaults:
  provider: mock
  model: mock-model
  env: {{}}
storage:
  flux_root: flux
  ai_root: .ai-flux
orchestrator:
  tick_ms: 10
  solver_preempt_grace_ms: 10
  evidence_poll_ms: 500
  modeler_idle_backoff_ms: 10
  bootstrapper_idle_backoff_ms: 10
problem:
  provision_instance:
    command: ["{provision}"]
  destroy_instance:
    command: ["{destroy}"]
  observe_evidence:
    command: ["{observe}"]
  sync_model_workspace:
    command: ["{sync}"]
  rehearse_seed_on_model:
    command: ["{rehearse}"]
  replay_seed_on_real_game:
    command: ["{replay}"]
  merge_evidence:
    strategy: dedupe_by_fingerprint
solver:
  prompt_file: prompts/solver.md
  session_scope: per_attempt
  resume_policy: never
  cadence_ms: 10
  queue_replacement_grace_ms: 10
  tools:
    builtin: [shell]
modeler:
  prompt_file: prompts/modeler.md
  working_directory: model_workspace
  session_scope: run
  resume_policy: always
  triggers:
    on_new_evidence: true
    on_solver_stopped: true
    periodic_ms: 10
  output_schema: model_update_v1
  acceptance:
    command: ["{acceptance}"]
    parse_as: json
    continue_message_template_file: prompts/modeler_continue.md
bootstrapper:
  prompt_file: prompts/bootstrapper.md
  session_scope: run
  resume_policy: always
  output_schema: bootstrap_seed_decision_v1
  seed_bundle_path: flux/seed/current.json
  require_model_rehearsal_before_finalize: true
  replay:
    max_attempts_per_event: 1
    continue_message_template_file: prompts/bootstrapper_continue.md
observability:
  capture_prompts: true
  capture_raw_provider_events: true
  capture_tool_calls: true
  capture_tool_results: true
  capture_queue_snapshots: true
  capture_timing_metrics: true
retention:
  keep_all_events: true
  keep_all_sessions: true
  keep_all_attempts: true
""".strip()
        + "\n",
        encoding="utf-8",
    )

    runtime = SimpleNamespace(
        run_dir=run_dir,
        super_env={
            **os.environ,
            "MOCK_PROVIDER_STREAMED_TEXT": "solver output",
            "MOCK_PROVIDER_STREAMED_MATCHERS_JSON": json.dumps(
                [
                    {
                        "contains": "MODELER_PROMPT",
                        "text": json.dumps(
                            {
                                "decision": "updated_model",
                                "summary": "first model patch",
                                "message_for_bootstrapper": "",
                                "artifacts_updated": ["model_lib.py"],
                                "evidence_watermark": "wm_initial",
                            }
                        ),
                    },
                    {
                        "contains": "Continue model:",
                        "text": json.dumps(
                            {
                                "decision": "updated_model",
                                "summary": "second model patch",
                                "message_for_bootstrapper": "seed is now ready",
                                "artifacts_updated": ["model_lib.py"],
                                "evidence_watermark": "wm_initial",
                            }
                        ),
                    },
                    {
                        "contains": "BOOTSTRAP_PROMPT",
                        "text": json.dumps(
                            {
                                "decision": "finalize_seed",
                                "summary": "seed is ready",
                                "seed_bundle_updated": False,
                                "notes": "finalize best known seed",
                                "solver_action": "queue_and_interrupt",
                                "seed_delta_kind": "mechanic_explanation_added",
                            }
                        ),
                    },
                ]
            ),
            "MOCK_PROVIDER_DELAY_MS": "400",
        },
        log=lambda _message: None,
    )

    rc = _launch_flux(runtime, run_dir / "flux.yaml")
    assert rc == 0

    event_rows = [
        json.loads(line)
        for line in (run_dir / "flux" / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert any(row["kind"] == "modeler.acceptance_failed" for row in event_rows)
    assert any(row["kind"] == "modeler.acceptance_passed" for row in event_rows)
    assert any(row["kind"] == "bootstrapper.attested_satisfactory" for row in event_rows)
    assert any(row["kind"] == "queue.preempt_requested" for row in event_rows)

    modeler_prompts = sorted((run_dir / ".ai-flux" / "sessions" / "modeler" / "modeler_run" / "prompts").glob("turn_*.json"))
    assert len(modeler_prompts) >= 2
    second_prompt = json.loads(modeler_prompts[1].read_text(encoding="utf-8"))
    assert "compare mismatch at level 1 sequence seq_0001 step 2: intermediate_frame_mismatch" in str(second_prompt.get("promptText", ""))

    solver_sessions = sorted((run_dir / ".ai-flux" / "sessions" / "solver").glob("solver_attempt_*/messages.jsonl"))
    assert len(solver_sessions) >= 2
    assert any("Seed preplay already ran on this instance." in path.read_text(encoding="utf-8") for path in solver_sessions)
    assert any("Current live state after preplay: level 2" in path.read_text(encoding="utf-8") for path in solver_sessions)
