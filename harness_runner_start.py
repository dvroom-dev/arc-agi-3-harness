from __future__ import annotations

from pathlib import Path


def start_super_new_impl(
    runtime,
    deps,
    *,
    phase_label: str,
    start_mode: str | None = None,
    image_paths: list[Path] | None = None,
) -> None:
    runtime.log(f"[harness] starting super new ({phase_label})...")
    runtime.refresh_dynamic_super_env()
    runtime.log(f"[harness] super agent-dir: {runtime.active_agent_dir()}")
    cmd = [
        "new",
        "--config", str(runtime.super_config),
        "--workspace", str(runtime.run_dir),
        "--config-dir", str(runtime.run_config_dir),
        "--agent-dir", str(runtime.active_agent_dir()),
        "--supervisor-dir", str(runtime.supervisor_dir),
        *runtime.provider_args(),
        *runtime.supervisor_args(),
        "--output", str(runtime.session_file),
    ]
    if runtime.cycle_limit is not None:
        cmd.extend(["--cycle-limit", str(runtime.cycle_limit)])
    if start_mode:
        cmd.extend(["--start-mode", str(start_mode)])
    if image_paths:
        cmd.extend(runtime.prompt_args("", prompt_kind="new", image_paths=image_paths))
    with runtime.phase_scope(
        category="super",
        name="new",
        metadata={"phase_label": phase_label, "start_mode": start_mode},
    ):
        deps.run_super(
            cmd,
            stream=True,
            cwd=runtime.run_dir,
            env=runtime.super_env,
        )
