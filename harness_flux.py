from __future__ import annotations

import codecs
import json
import os
import selectors
import signal
import subprocess
import sys
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

import harness as deps
from harness_runner_args import resolve_arc_base_url, resolve_game_ids
from harness_runtime import HarnessRuntime

PROJECT_ROOT = Path(__file__).resolve().parent
SUPER_FLUX_ENTRYPOINT = Path("/home/dvroom/projs/super/src/bin/flux.ts")
FLUX_STOP_TERMINATE_GRACE_SECONDS = 10.0
FLUX_STOP_KILL_GRACE_SECONDS = 5.0


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
        "solver_template_dir": str((runtime.run_dir / "flux_seed" / "agent" / Path(runtime.active_agent_dir()).name)),
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


def _snapshot_clean_solver_seed(runtime: HarnessRuntime) -> Path:
    source = runtime.active_agent_dir()
    destination = runtime.run_dir / "flux_seed" / "agent" / source.name
    if destination.exists():
        shutil.rmtree(destination, ignore_errors=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination)
    return destination


def _write_initial_seed_bundle(run_dir: Path) -> Path:
    seed_path = run_dir / "flux" / "seed" / "current.json"
    seed_path.parent.mkdir(parents=True, exist_ok=True)
    seed_path.write_text(
        json.dumps(
            {
                "version": 1,
                "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
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


def _read_flux_state_status(state_path: Path) -> tuple[str | None, bool]:
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return None, False
    if not isinstance(payload, dict):
        return None, False
    status = payload.get("status")
    stop_requested = bool(payload.get("stopRequested"))
    return (str(status) if isinstance(status, str) else None), stop_requested


def _render_flux_config(runtime: HarnessRuntime) -> str:
    template = (PROJECT_ROOT / "flux.yaml").read_text(encoding="utf-8")
    prompts_root = PROJECT_ROOT / "prompts" / "flux"
    scripts_root = PROJECT_ROOT / "scripts" / "flux"
    model_workspace_rel = _safe_relpath(runtime.run_dir, runtime.active_agent_dir())
    provider_name = str(getattr(runtime.args, "provider", None) or "codex").strip() or "codex"
    provider_default_model = {
        "mock": "mock-model",
        "claude": "claude-opus-4-6",
        "codex": "gpt-5.4",
    }
    solver_model = provider_default_model.get(provider_name, "claude-opus-4-6")
    modeler_provider = provider_name
    modeler_model = provider_default_model.get(modeler_provider, "claude-opus-4-6")
    bootstrapper_provider = provider_name
    bootstrapper_model = provider_default_model.get(bootstrapper_provider, "claude-opus-4-6")
    replacements = {
        "{{RUNTIME_PROVIDER}}": provider_name,
        "{{RUNTIME_MODEL}}": solver_model,
        "{{PROMPTS_ROOT}}": str(prompts_root),
        "{{SCRIPTS_ROOT}}": str(scripts_root),
        "{{MODEL_WORKSPACE_REL}}": model_workspace_rel,
        "{{MODELER_PROVIDER}}": modeler_provider,
        "{{MODELER_MODEL}}": modeler_model,
        "{{BOOTSTRAPPER_PROVIDER}}": bootstrapper_provider,
        "{{BOOTSTRAPPER_MODEL}}": bootstrapper_model,
    }
    rendered = template
    for needle, value in replacements.items():
        rendered = rendered.replace(needle, value)
    return rendered


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
    flux_logs_dir = runtime.run_dir / "flux" / "logs"
    flux_logs_dir.mkdir(parents=True, exist_ok=True)
    launcher_log_path = flux_logs_dir / "launcher.log"
    proc = subprocess.Popen(
        cmd,
        cwd=str(runtime.run_dir),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=0,
        start_new_session=True,
    )
    assert proc.stdout is not None
    stdout_fd = proc.stdout.fileno()
    os.set_blocking(stdout_fd, False)
    selector = selectors.DefaultSelector()
    selector.register(stdout_fd, selectors.EVENT_READ)
    state_path = runtime.run_dir / "flux" / "state.json"
    stop_seen_at: float | None = None
    terminate_sent_at: float | None = None
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    pending_text = ""

    def _write_output(text: str, *, final: bool = False) -> None:
        nonlocal pending_text
        if text:
            pending_text += text
        while True:
            newline_index = pending_text.find("\n")
            if newline_index < 0:
                break
            line = pending_text[: newline_index + 1]
            pending_text = pending_text[newline_index + 1 :]
            log_file.write(line)
            log_file.flush()
            sys.stdout.write(line)
            sys.stdout.flush()
        if final and pending_text:
            log_file.write(pending_text)
            log_file.flush()
            sys.stdout.write(pending_text)
            sys.stdout.flush()
            pending_text = ""

    def _signal_child(sig: signal.Signals, message: str) -> None:
        if proc.poll() is not None:
            return
        log_file.write(message + "\n")
        log_file.flush()
        try:
            os.killpg(proc.pid, sig)
        except Exception:
            if sig == signal.SIGTERM:
                proc.terminate()
            else:
                proc.kill()

    with launcher_log_path.open("a", encoding="utf-8") as log_file:
        while True:
            if proc.poll() is not None:
                break
            events = selector.select(timeout=0.5)
            for key, _mask in events:
                try:
                    chunk = os.read(int(key.fd), 4096)
                except BlockingIOError:
                    continue
                if not chunk:
                    try:
                        selector.unregister(key.fd)
                    except Exception:
                        pass
                    continue
                _write_output(decoder.decode(chunk))
            status, stop_requested = _read_flux_state_status(state_path)
            if status in {"stopped", "stopping"} or (stop_requested and status == "running"):
                if stop_seen_at is None:
                    stop_seen_at = time.monotonic()
                elapsed = time.monotonic() - stop_seen_at
                if terminate_sent_at is None and elapsed >= FLUX_STOP_TERMINATE_GRACE_SECONDS:
                    _signal_child(signal.SIGTERM, "[launcher] flux child still alive after stop state; sending SIGTERM")
                    terminate_sent_at = time.monotonic()
                elif terminate_sent_at is not None and (time.monotonic() - terminate_sent_at) >= FLUX_STOP_KILL_GRACE_SECONDS and proc.poll() is None:
                    _signal_child(signal.SIGKILL, "[launcher] flux child ignored SIGTERM after stop state; sending SIGKILL")
            else:
                stop_seen_at = None
                terminate_sent_at = None
        while True:
            try:
                chunk = os.read(stdout_fd, 4096)
            except BlockingIOError:
                break
            if not chunk:
                break
            _write_output(decoder.decode(chunk))
        _write_output(decoder.decode(b"", final=True), final=True)
    try:
        selector.close()
    except Exception:
        pass
    rc = int(proc.wait())
    event_path = runtime.run_dir / "flux" / "events.jsonl"
    if event_path.exists():
        event_payload = {
            "eventId": f"evt_launcher_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}",
            "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "kind": "launcher.child_exited",
            "workspaceRoot": str(runtime.run_dir),
            "summary": f"flux child exited with code {rc}",
            "payload": {"exitCode": rc, "logFile": str(launcher_log_path)},
        }
        with event_path.open("a", encoding="utf-8") as event_file:
            event_file.write(json.dumps(event_payload) + "\n")
    state_path = runtime.run_dir / "flux" / "state.json"
    if state_path.exists():
        try:
            state_payload = json.loads(state_path.read_text(encoding="utf-8"))
            if isinstance(state_payload, dict) and state_payload.get("status") == "running":
                state_payload["status"] = "stopped"
                state_payload["updatedAt"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                state_path.write_text(json.dumps(state_payload, indent=2) + "\n", encoding="utf-8")
        except Exception:
            pass
    return rc


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
    _snapshot_clean_solver_seed(runtime)
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
