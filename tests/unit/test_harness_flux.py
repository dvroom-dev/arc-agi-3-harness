from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import harness_flux
from harness_flux import _launch_flux, _read_flux_state_status, _render_flux_config, _write_initial_seed_bundle


def test_write_initial_seed_bundle_creates_empty_bundle(tmp_path: Path) -> None:
    bundle_path = _write_initial_seed_bundle(tmp_path)
    payload = json.loads(bundle_path.read_text())
    assert payload["version"] == 1
    assert payload["syntheticMessages"] == []
    assert payload["replayPlan"] == []


def test_render_flux_config_includes_durable_workspace() -> None:
    runtime = SimpleNamespace(
        args=SimpleNamespace(provider=None),
        run_dir=Path("/tmp/flux-run"),
        active_agent_dir=lambda: Path("/tmp/flux-run/agent/game_ls20"),
    )
    text = _render_flux_config(runtime)
    assert "working_directory: agent/game_ls20" in text
    assert "output_schema: model_update_v1" in text
    assert "check_model.py" in text
    assert "rehearse_seed_on_model.py" in text
    assert "replay_seed_on_real_game.py" in text
    assert "output_schema: bootstrap_seed_decision_v1" in text
    assert "runtime_defaults:\n  provider: claude" in text
    assert "modeler:\n  prompt_file:" in text
    assert "  provider: codex" in text
    assert "bootstrapper:\n  prompt_file:" in text
    assert "  provider: codex" in text


def test_render_flux_config_uses_split_defaults_for_claude_solver_runs() -> None:
    runtime = SimpleNamespace(
        args=SimpleNamespace(provider="claude"),
        run_dir=Path("/tmp/flux-run"),
        active_agent_dir=lambda: Path("/tmp/flux-run/agent/game_ls20"),
    )
    text = _render_flux_config(runtime)
    assert "runtime_defaults:\n  provider: claude" in text
    assert "modeler:\n  prompt_file:" in text
    assert "  provider: codex" in text
    assert "bootstrapper:\n  prompt_file:" in text
    assert "  provider: codex" in text


def test_render_flux_config_keeps_codex_provider_coherent() -> None:
    runtime = SimpleNamespace(
        args=SimpleNamespace(provider="codex"),
        run_dir=Path("/tmp/flux-run"),
        active_agent_dir=lambda: Path("/tmp/flux-run/agent/game_ls20"),
    )
    text = _render_flux_config(runtime)
    assert "runtime_defaults:\n  provider: codex" in text
    assert "modeler:\n  prompt_file:" in text
    assert "  provider: codex" in text
    assert "bootstrapper:\n  prompt_file:" in text
    assert "  provider: codex" in text


def test_render_flux_config_keeps_mock_provider_coherent() -> None:
    runtime = SimpleNamespace(
        args=SimpleNamespace(provider="mock"),
        run_dir=Path("/tmp/flux-run"),
        active_agent_dir=lambda: Path("/tmp/flux-run/agent/game_ls20"),
    )
    text = _render_flux_config(runtime)
    assert "runtime_defaults:\n  provider: mock" in text
    assert "modeler:\n  prompt_file:" in text
    assert "  provider: mock" in text


def test_flux_yaml_template_exists() -> None:
    assert Path("flux.yaml").exists()


def test_read_flux_state_status_parses_stop_state(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"status": "stopped", "stopRequested": True}), encoding="utf-8")
    status, stop_requested = _read_flux_state_status(state_path)
    assert status == "stopped"
    assert stop_requested is True


def test_read_flux_state_status_handles_bad_json(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text("{bad", encoding="utf-8")
    status, stop_requested = _read_flux_state_status(state_path)
    assert status is None
    assert stop_requested is False


def test_launch_flux_reaps_stopped_child_even_with_partial_stdout(tmp_path: Path, monkeypatch) -> None:
    run_dir = tmp_path / "run"
    (run_dir / "flux" / "logs").mkdir(parents=True, exist_ok=True)
    state_path = run_dir / "flux" / "state.json"
    state_path.write_text(json.dumps({"status": "running", "stopRequested": False}), encoding="utf-8")

    child_script = tmp_path / "child.py"
    child_script.write_text(
        "import signal\n"
        "import sys\n"
        "import time\n"
        "signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))\n"
        "sys.stdout.write('partial-without-newline')\n"
        "sys.stdout.flush()\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )

    real_popen = subprocess.Popen

    def fake_popen(*_args, **kwargs):
        return real_popen([sys.executable, str(child_script)], **kwargs)

    monkeypatch.setattr(harness_flux.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(harness_flux, "FLUX_STOP_TERMINATE_GRACE_SECONDS", 0.1)
    monkeypatch.setattr(harness_flux, "FLUX_STOP_KILL_GRACE_SECONDS", 0.1)

    def mark_stopped() -> None:
        time.sleep(0.05)
        state_path.write_text(json.dumps({"status": "stopped", "stopRequested": True}), encoding="utf-8")

    stopper = threading.Thread(target=mark_stopped, daemon=True)
    stopper.start()

    runtime = SimpleNamespace(
        run_dir=run_dir,
        super_env={},
        log=lambda _message: None,
    )
    started_at = time.monotonic()
    rc = _launch_flux(runtime, run_dir / "flux.yaml")
    elapsed = time.monotonic() - started_at

    assert elapsed < 3
    assert rc == 0
    launcher_log = (run_dir / "flux" / "logs" / "launcher.log").read_text(encoding="utf-8")
    assert "sending SIGTERM" in launcher_log
    assert "partial-without-newline" in launcher_log


def test_launch_flux_mocked_end_to_end_flow(tmp_path: Path) -> None:
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
  "current_level": 2 if preplayed else 1,
  "levels_completed": 1 if preplayed else 0,
  "win_levels": 7,
  "state": "WIN" if preplayed else "NOT_FINISHED",
  "total_steps": 18 if preplayed else 1,
  "current_attempt_steps": 0 if preplayed else 1,
  "last_action_name": "ACTION1",
}
print(json.dumps({
  "evidence": [{
    "summary": "preplayed frontier" if preplayed else "solver evidence",
    "action_count": 18 if preplayed else 1,
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
import json, sys
json.load(sys.stdin)
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

    (run_dir / "flux").mkdir(parents=True, exist_ok=True)
    (run_dir / "flux" / "seed").mkdir(parents=True, exist_ok=True)
    (run_dir / "flux" / "seed" / "current.json").write_text(
        json.dumps(
            {
                "version": 1,
                "generatedAt": "2026-04-04T00:00:00Z",
                "syntheticMessages": [{"role": "assistant", "text": "Seed knowledge"}],
                "replayPlan": [],
                "assertions": ["best known seed"],
            },
            indent=2,
        )
        + "\n",
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
                                "seed_bundle_updated": False,
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

    events_path = run_dir / "flux" / "events.jsonl"
    events_text = events_path.read_text(encoding="utf-8")
    assert '"kind":"bootstrapper.model_rehearsal_passed"' in events_text
    assert '"kind":"bootstrapper.real_replay_passed"' in events_text
    assert '"kind":"bootstrapper.attested_satisfactory"' in events_text
    assert '"kind":"solver.instance_provisioned"' in events_text
    assert '"kind":"orchestrator.stopped"' in events_text

    state = json.loads((run_dir / "flux" / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "stopped"

    solver_sessions = sorted((run_dir / ".ai-flux" / "sessions" / "solver").glob("solver_attempt_*/session.json"))
    assert len(solver_sessions) >= 2
