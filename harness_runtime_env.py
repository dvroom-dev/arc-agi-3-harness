from __future__ import annotations


def provider_args_impl(runtime) -> list[str]:
    return ["--provider", runtime.args.provider] if runtime.args.provider else []


def supervisor_args_impl(runtime) -> list[str]:
    return ["--no-supervisor"] if runtime.args.no_supervisor else []


def refresh_dynamic_super_env_impl(runtime) -> None:
    runtime.super_env["ARC_CONVERSATION_ID"] = runtime.active_conversation_id
    runtime.super_env["ARC_ACTIVE_GAME_ID"] = runtime.active_game_id
    runtime.super_env["ARC_PROMPT_GAME_ID"] = runtime.prompt_game_id
    runtime.super_env["ARC_PROMPT_GAME_SLUG"] = runtime.prompt_game_slug
    runtime.super_env["ARC_PROMPT_GAME_DIR"] = runtime.prompt_game_dir
    runtime.super_env["ARC_PROMPT_AVAILABLE_ACTIONS"] = ",".join(
        str(action) for action in runtime.prompt_available_actions
    )
    runtime.super_env["ARC_PROMPT_ACTIONS_BLOCK"] = runtime.prompt_actions_block
    runtime.super_env["ARC_REPL_SESSION_KEY"] = runtime.active_repl_session_key


def has_idle_keepalive_marker_impl(runtime) -> bool:
    return bool(runtime.idle_keepalive_marker_path.exists())


def read_idle_keepalive_marker_impl(runtime) -> str | None:
    if not runtime.idle_keepalive_marker_path.exists():
        return None
    try:
        payload = runtime.idle_keepalive_marker_path.read_text(encoding="utf-8").strip()
    except Exception:
        return None
    return payload or None


def idle_keepalive_enabled_impl(runtime) -> bool:
    return bool(runtime.api_idle_keepalive_base_enabled)


def write_idle_keepalive_marker_impl(runtime, *, marker: str, details: str = "") -> None:
    payload = str(marker).strip()
    if details:
        payload = f"{payload} {str(details).strip()}".strip()
    runtime.idle_keepalive_marker_path.parent.mkdir(parents=True, exist_ok=True)
    runtime.idle_keepalive_marker_path.write_text(payload + "\n", encoding="utf-8")


def clear_idle_keepalive_marker_impl(runtime) -> None:
    if not runtime.idle_keepalive_marker_path.exists():
        return
    try:
        runtime.idle_keepalive_marker_path.unlink()
    except Exception:
        pass
