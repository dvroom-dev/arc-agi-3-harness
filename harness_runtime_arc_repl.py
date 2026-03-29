from __future__ import annotations

import json
import os


def run_arc_repl_impl(rt, payload: dict) -> tuple[dict | None, str, int]:
    request = dict(payload)
    action_name = str(request.get("action", "")).strip()
    requested_game_id = str(request.get("game_id", "")).strip()
    if requested_game_id:
        if (
            rt.active_game_id
            and requested_game_id == str(rt.args.game_id).strip()
            and rt.active_game_id != requested_game_id
        ):
            request["game_id"] = rt.active_game_id
    elif rt.active_game_id:
        request["game_id"] = rt.active_game_id

    cmd = [
        str(rt.deps.PROJECT_VENV_PYTHON),
        str(rt.run_arc_repl_tool),
    ]
    child_env = dict(os.environ)
    child_env["ARC_OPERATION_MODE"] = str(rt.args.operation_mode).strip().upper()
    child_env["ARC_BACKEND"] = str(getattr(rt.args, "arc_backend", "") or "")
    child_env["ARC_BASE_URL"] = rt.arc_base_url
    child_env.setdefault("ARC_ENVIRONMENTS_DIR", str(rt.arc_env_dir))
    child_env["ARC_STATE_DIR"] = str(rt.arc_state_dir)
    child_env["ARC_CONFIG_DIR"] = str(rt.run_config_dir)
    child_env["ONLY_RESET_LEVELS"] = "true"
    if rt.arc_api_key:
        child_env["ARC_API_KEY"] = rt.arc_api_key
    child_env["ARC_CONVERSATION_ID"] = rt.active_conversation_id
    child_env["ARC_ACTIVE_GAME_ID"] = rt.active_game_id or str(rt.args.game_id).strip()
    if rt.active_scorecard_id:
        child_env["ARC_SCORECARD_ID"] = rt.active_scorecard_id
    if rt.scorecard_cookies_json:
        child_env["ARC_SCORECARD_COOKIES"] = rt.scorecard_cookies_json
    child_env["ARC_REPL_SESSION_KEY"] = rt.active_repl_session_key
    child_env["ARC_REPL_PARENT_PID"] = str(rt.repl_parent_pid)
    if rt.repl_parent_start_ticks is not None:
        child_env["ARC_REPL_PARENT_START_TICKS"] = str(rt.repl_parent_start_ticks)

    with rt.phase_scope(
        category="tool",
        name="arc_repl",
        metadata={"action": action_name, "requested_game_id": requested_game_id or None},
    ) as phase:
        proc = rt.deps.subprocess.run(
            cmd,
            input=json.dumps(request),
            text=True,
            capture_output=True,
            cwd=str(rt.active_agent_dir()),
            env=child_env,
        )
        phase["return_code"] = proc.returncode
    if proc.stderr.strip():
        for line in proc.stderr.strip().splitlines():
            rt.log(f"[arc_repl] {line}")

    stdout = proc.stdout.strip()
    parsed: dict | None = None
    allow_raw_stdout = action_name == "exec"
    if allow_raw_stdout:
        return None, stdout, proc.returncode

    if stdout:
        try:
            maybe = json.loads(stdout)
        except Exception as exc:
            if proc.returncode == 0:
                preview = stdout[:800].replace("\n", "\\n")
                raise RuntimeError(
                    "arc_repl returned non-JSON stdout despite success status: "
                    f"{exc}. stdout_preview={preview}"
                ) from exc
        else:
            if isinstance(maybe, dict):
                parsed = maybe
                if (
                    rt.active_scorecard_id
                    and action_name == "status"
                    and proc.returncode == 0
                ):
                    echoed_scorecard_id = str(parsed.get("scorecard_id", "") or "").strip()
                    if echoed_scorecard_id != rt.active_scorecard_id:
                        raise RuntimeError(
                            "arc_repl status did not echo expected scorecard_id: "
                            f"expected={rt.active_scorecard_id!r} "
                            f"got={echoed_scorecard_id!r}"
                        )
                resolved_game_id = str(parsed.get("game_id", "")).strip()
                if resolved_game_id:
                    rt.active_game_id = resolved_game_id
                    rt.update_prompt_game_vars()
                    rt.super_env["ARC_ACTIVE_GAME_ID"] = rt.active_game_id
                repl_meta = parsed.get("repl")
                if isinstance(repl_meta, dict):
                    daemon_pid_raw = repl_meta.get("daemon_pid")
                    daemon_pid: int | None = None
                    try:
                        daemon_pid = int(daemon_pid_raw)
                    except Exception:
                        daemon_pid = None
                    if daemon_pid is not None:
                        session_created = bool(repl_meta.get("session_created", False))
                        if rt.last_repl_daemon_pid is None:
                            rt.log(
                                "[harness] arc_repl daemon active: "
                                f"pid={daemon_pid} session_key={rt.active_repl_session_key} "
                                f"session_created={session_created}"
                            )
                        elif daemon_pid != rt.last_repl_daemon_pid:
                            daemon_dir = rt.arc_state_dir / "repl-sessions" / rt.active_repl_session_key
                            rt.log(
                                "[harness] WARNING: arc_repl daemon pid changed: "
                                f"old={rt.last_repl_daemon_pid} new={daemon_pid} "
                                f"action={action_name} session_created={session_created}. "
                                f"Inspect {daemon_dir / 'daemon.log'} and "
                                f"{daemon_dir / 'daemon.lifecycle.jsonl'}."
                            )
                        rt.last_repl_daemon_pid = daemon_pid
            elif proc.returncode == 0:
                raise RuntimeError(
                    "arc_repl returned JSON that is not an object on success."
                )
    elif proc.returncode == 0:
        raise RuntimeError("arc_repl returned empty stdout on success.")

    return parsed, stdout, proc.returncode


def resume_super_impl(rt, prompt: str | None = None, *, image_paths=None) -> str:
    with rt.phase_scope(
        category="super",
        name="resume",
        metadata={"prompted": bool(prompt), "image_count": len(image_paths or [])},
    ) as phase:
        rt.refresh_dynamic_super_env()
        rt.recover_session_file_from_workspace(reason="pre-resume")
        rt.log(f"[harness] super agent-dir: {rt.active_agent_dir()}")
        resume_args: list[str] = [
            "resume",
            "--workspace", str(rt.run_dir),
            "--config", str(rt.super_config),
            "--config-dir", str(rt.run_config_dir),
            "--agent-dir", str(rt.active_agent_dir()),
            "--supervisor-dir", str(rt.supervisor_dir),
            *rt.provider_args(),
            *rt.supervisor_args(),
        ]
        if rt.cycle_limit is not None:
            resume_args += ["--cycle-limit", str(rt.cycle_limit)]
        if prompt or image_paths:
            resume_args += rt.prompt_args(prompt or "", prompt_kind="resume", image_paths=image_paths)
        resume_args += ["--output", str(rt.session_file)]
        stdout = rt.deps.run_super(resume_args, stream=True, cwd=rt.run_dir, env=rt.super_env)
        phase["assistant_text_bytes"] = len(stdout.encode("utf-8"))
        rt.recover_session_file_from_workspace(reason="post-resume", force=True)
        return stdout
