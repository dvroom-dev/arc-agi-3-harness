from __future__ import annotations

import json


def has_recoverable_run_state(runtime) -> bool:
    if (runtime.run_dir / "super" / "state.json").exists():
        return True
    if runtime.discover_workspace_conversation_id():
        return True
    frontmatter = runtime.session_frontmatter()
    return bool(
        runtime.session_file.exists()
        and str(frontmatter.get("conversation_id") or "").strip()
        and str(frontmatter.get("fork_id") or "").strip()
    )


def log_monitor_sources(runtime) -> None:
    monitor = runtime.monitor_snapshot()
    runtime.log(
        "[harness] monitor sources: "
        f"state={monitor['state_path']} "
        f"history={monitor['history_path']} "
        f"model_status={monitor['model_status_path']} "
        f"session={monitor['session_path']} "
        f"raw_events={monitor.get('raw_events_path') or '(not-found-yet)'}"
    )


def continue_existing_run(runtime) -> None:
    runtime.log("[harness] continuing existing run from persisted supervisor state...")
    runtime.refresh_dynamic_super_env()
    runtime.recover_session_file_from_workspace(reason="continue-start", force=True)
    runtime.sync_active_conversation_id_from_session()
    repaired_mode = runtime.repair_stale_wrapup_mode()
    if repaired_mode:
        runtime.log(
            "[harness] repaired stale supervisor mode before continue: "
            f"{repaired_mode} -> theory (pin remains active)"
        )
    runtime.certify_or_block_wrapup_transition()
    log_monitor_sources(runtime)


def load_super_resume_permission(runtime) -> tuple[bool, list[str], list[str]]:
    state_path = runtime.run_dir / "super" / "state.json"
    if not state_path.exists():
        return True, [], []
    try:
        payload = json.loads(state_path.read_text())
    except Exception as exc:
        raise RuntimeError(f"failed to parse super/state.json: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("super/state.json must contain a JSON object")
    resume_allowed = bool(payload.get("resumeAllowed", True))
    stop_reasons = payload.get("lastStopReasons") if isinstance(payload.get("lastStopReasons"), list) else []
    stop_details = payload.get("lastStopDetails") if isinstance(payload.get("lastStopDetails"), list) else []
    return (
        resume_allowed,
        [str(item) for item in stop_reasons],
        [str(item) for item in stop_details],
    )


def stop_if_supervisor_terminal(runtime) -> bool:
    resume_allowed, super_stop_reasons, super_stop_details = load_super_resume_permission(runtime)
    if resume_allowed:
        return False
    runtime.log(
        "[harness] supervisor marked run terminal; stopping outer resume loop: "
        f"reasons={super_stop_reasons or ['(none)']} "
        f"details={super_stop_details or ['(none)']}"
    )
    return True
