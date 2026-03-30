from __future__ import annotations

import json
import signal
import subprocess
import sys
from pathlib import Path

import harness as deps
from harness_runner_args import resolve_arc_base_url, resolve_game_ids
from harness_runtime import HarnessRuntime

PROJECT_ROOT = Path(__file__).resolve().parent
SUPER_FLUX_ENTRYPOINT = Path("/home/dvroom/projs/super/src/bin/flux.ts")


def _safe_relpath(base: Path, child: Path) -> str:
    try:
        return str(child.relative_to(base))
    except Exception:
        return str(child)


def _write_flux_runtime_meta(runtime: HarnessRuntime, arc_base_url: str) -> Path:
    meta_path = runtime.run_dir / "flux_runtime.json"
    payload = {
        "run_dir": str(runtime.run_dir),
        "project_root": str(PROJECT_ROOT),
        "game_id": runtime.active_game_id or str(runtime.args.game_id).strip(),
        "operation_mode": runtime.operation_mode_name,
        "arc_backend": str(getattr(runtime.args, "arc_backend", "") or ""),
        "arc_base_url": arc_base_url,
        "run_config_dir": str(runtime.run_config_dir),
        "run_bin_dir": str(runtime.run_bin_dir),
        "run_tools_dir": str(runtime.run_tools_dir),
        "python_executable": str(deps.PROJECT_VENV_PYTHON),
        "run_arc_repl_tool": str(runtime.run_arc_repl_tool),
        "solver_template_dir": str(runtime.active_agent_dir()),
        "model_workspace_dir": str(runtime.active_agent_dir()),
        "arc_env_dir": str(runtime.arc_env_dir),
        "arc_prompt_game_id": runtime.prompt_game_id,
        "arc_prompt_game_slug": runtime.prompt_game_slug,
        "arc_prompt_game_dir": runtime.prompt_game_dir,
        "arc_prompt_actions_block": runtime.prompt_actions_block,
        "arc_prompt_available_actions": list(runtime.prompt_available_actions),
        "scorecard_id": runtime.active_scorecard_id,
    }
    meta_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return meta_path


def _write_initial_seed_bundle(run_dir: Path) -> Path:
    seed_path = run_dir / "flux" / "seed" / "current.json"
    seed_path.parent.mkdir(parents=True, exist_ok=True)
    seed_path.write_text(
        json.dumps(
            {
                "version": 1,
                "generatedAt": "",
                "syntheticMessages": [],
                "replayPlan": [],
                "assertions": [],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return seed_path


def _render_flux_config(runtime: HarnessRuntime) -> str:
    prompts_root = PROJECT_ROOT / "prompts" / "flux"
    scripts_root = PROJECT_ROOT / "scripts" / "flux"
    model_workspace_rel = _safe_relpath(runtime.run_dir, runtime.active_agent_dir())
    seed_bundle_rel = "flux/seed/current.json"
    provider_name = str(getattr(runtime.args, "provider", None) or "claude").strip() or "claude"
    solver_model = "mock-model" if provider_name == "mock" else "claude-opus-4-6"
    modeler_provider = provider_name
    modeler_model = "mock-model" if provider_name == "mock" else "claude-opus-4-6"
    bootstrapper_provider = provider_name if provider_name == "mock" else "codex"
    bootstrapper_model = "mock-model" if bootstrapper_provider == "mock" else "gpt-5.4"
    return f"""schema_version: 1
runtime_defaults:
  provider: {provider_name}
  model: {solver_model}
  reasoning_effort: medium
  sandbox_mode: workspace-write
  approval_policy: never
  env: {{}}
storage:
  flux_root: flux
  ai_root: .ai-flux
orchestrator:
  tick_ms: 1000
  solver_preempt_grace_ms: 15000
  evidence_poll_ms: 5000
  modeler_idle_backoff_ms: 10000
  bootstrapper_idle_backoff_ms: 10000
problem:
  provision_instance:
    command: ["python3", "{scripts_root / "provision_instance.py"}"]
  destroy_instance:
    command: ["python3", "{scripts_root / "destroy_instance.py"}"]
  observe_evidence:
    command: ["python3", "{scripts_root / "observe_evidence.py"}"]
  replay_seed:
    command: ["python3", "{scripts_root / "replay_seed.py"}"]
  merge_evidence:
    strategy: dedupe_by_fingerprint
solver:
  prompt_file: {prompts_root / "solver.md"}
  session_scope: per_attempt
  resume_policy: never
  cadence_ms: 30000
  queue_replacement_grace_ms: 15000
  tools:
    builtin: [shell, read_file, write_file, list_dir, apply_patch]
modeler:
  prompt_file: {prompts_root / "modeler.md"}
  working_directory: {model_workspace_rel}
  session_scope: run
  resume_policy: always
  provider: {modeler_provider}
  model: {modeler_model}
  triggers:
    on_new_evidence: true
    on_solver_stopped: true
    periodic_ms: 60000
  output_schema: model_update_v1
  acceptance:
    command: ["python3", "{scripts_root / "check_model.py"}"]
    parse_as: json
    continue_message_template_file: {prompts_root / "modeler_continue.md"}
bootstrapper:
  prompt_file: {prompts_root / "bootstrapper.md"}
  working_directory: {model_workspace_rel}
  session_scope: run
  resume_policy: always
  provider: {bootstrapper_provider}
  model: {bootstrapper_model}
  output_schema: bootstrap_attestation_v1
  seed_bundle_path: {seed_bundle_rel}
  replay:
    max_attempts_per_event: 5
    continue_message_template_file: {prompts_root / "bootstrapper_continue.md"}
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
"""


def _launch_flux(runtime: HarnessRuntime, config_path: Path) -> int:
    env = dict(runtime.super_env)
    env["ARC_FLUX_META_PATH"] = str(runtime.run_dir / "flux_runtime.json")
    cmd = [
        "bun",
        "run",
        str(SUPER_FLUX_ENTRYPOINT),
        "run",
        "--workspace",
        str(runtime.run_dir),
        "--config",
        str(config_path),
    ]
    runtime.log(f"[flux] running: {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=str(runtime.run_dir), env=env)
    return int(proc.returncode)


def main() -> None:
    def _handle_termination(signum, _frame):
        signame = signal.Signals(signum).name
        print(f"[flux-harness] received signal {signame}; terminating", file=sys.stderr, flush=True)
        raise SystemExit(128 + signum)

    for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(sig, _handle_termination)

    args = deps.parse_args()
    game_ids = resolve_game_ids(args)
    if len(game_ids) != 1:
        raise RuntimeError("harness_flux.py currently supports exactly one game ID.")
    args.game_id = game_ids[0]
    arc_base_url = resolve_arc_base_url(args)
    runtime = HarnessRuntime(
        deps,
        args,
        operation_mode_name=str(args.operation_mode).strip().upper(),
        arc_base_url=arc_base_url,
    )
    runtime.log(f"[flux] run dir: {runtime.run_dir}")
    runtime.log(f"[flux] durable model workspace: {runtime.active_agent_dir()}")
    _result, _stdout, init_rc = runtime.run_arc_repl({"action": "status", "game_id": args.game_id})
    if init_rc != 0:
        raise RuntimeError("failed to initialize ARC state for flux launcher")
    _write_flux_runtime_meta(runtime, arc_base_url)
    _write_initial_seed_bundle(runtime.run_dir)
    config_path = runtime.run_dir / "flux.yaml"
    config_path.write_text(_render_flux_config(runtime), encoding="utf-8")
    rc = _launch_flux(runtime, config_path)
    if rc != 0:
        raise SystemExit(rc)


if __name__ == "__main__":
    main()
