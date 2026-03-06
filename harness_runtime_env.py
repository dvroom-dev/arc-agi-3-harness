from __future__ import annotations


def provider_args_impl(runtime) -> list[str]:
    return ["--provider", runtime.args.provider] if runtime.args.provider else []


def supervisor_args_impl(runtime) -> list[str]:
    return ["--no-supervisor"] if runtime.args.no_supervisor else []


def current_level_for_define_impl(runtime) -> int:
    state = runtime.load_state() or {}
    try:
        level = int(state.get("current_level", 1) or 1)
    except Exception:
        level = 1
    return max(1, level)


def refresh_dynamic_super_env_impl(runtime) -> None:
    runtime.super_env["ARC_CONVERSATION_ID"] = runtime.active_conversation_id
    runtime.super_env["ARC_ACTIVE_GAME_ID"] = runtime.active_game_id
    runtime.super_env["ARC_PROMPT_GAME_ID"] = runtime.prompt_game_id
    runtime.super_env["ARC_PROMPT_GAME_SLUG"] = runtime.prompt_game_slug
    runtime.super_env["ARC_PROMPT_GAME_DIR"] = runtime.prompt_game_dir
    runtime.super_env["ARC_REPL_SESSION_KEY"] = runtime.active_repl_session_key
    runtime.super_env["ARC_LEVEL_NUM"] = str(current_level_for_define_impl(runtime))


def define_args_impl(runtime) -> list[str]:
    level_num = str(runtime.super_env.get("ARC_LEVEL_NUM", current_level_for_define_impl(runtime)))
    return ["--define", f"level_num={level_num}"]


def has_idle_keepalive_marker_impl(runtime) -> bool:
    return bool(runtime.idle_keepalive_marker_path.exists())


def idle_keepalive_enabled_impl(runtime) -> bool:
    return bool(runtime.api_idle_keepalive_base_enabled and runtime.active_scorecard_id)


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
