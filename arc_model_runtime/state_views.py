from __future__ import annotations

from typing import Any

from .utils import effective_analysis_level, grid_hex_rows, load_frontier_level_from_arc_state


def state_transition_flags(env) -> dict[str, Any]:
    current_level_complete = bool(env.level_complete or str(env.state) == "WIN")
    last_step_level_complete = bool(env.last_step_level_complete or str(env.state) == "WIN")
    current_level_game_over = bool(env.game_over or str(env.state) == "GAME_OVER")
    last_step_game_over = bool(env.last_step_game_over or str(env.state) == "GAME_OVER")
    return {
        "level_complete": last_step_level_complete,
        "current_level_complete": current_level_complete,
        "last_step_level_complete": last_step_level_complete,
        "last_completed_level": int(env.last_completed_level) if env.last_completed_level is not None else None,
        "game_over": last_step_game_over,
        "current_level_game_over": current_level_game_over,
        "last_step_game_over": last_step_game_over,
        "last_game_over_level": int(env.last_game_over_level) if env.last_game_over_level is not None else None,
    }


def state_payload(env) -> dict[str, Any]:
    env.refresh_level_initial_states()
    visible_level = int(env.pending_level_init) if getattr(env, "pending_level_init", None) is not None else int(env.current_level)
    return {
        "state": str(env.state),
        "current_level": visible_level,
        "levels_completed": int(env.levels_completed),
        **state_transition_flags(env),
        "win_levels": int(env.win_levels),
        "guid": getattr(env, "guid", None),
        "available_actions": [int(a) for a in getattr(env, "available_actions", [])],
        "available_model_levels": [int(v) for v in env.available_model_levels],
        "full_reset": bool(getattr(env, "full_reset", False)),
        "grid_hex_rows": grid_hex_rows(env.grid),
    }


def status_state(*, game_dir, env) -> dict[str, Any]:
    env.refresh_level_initial_states()
    pending_level = int(env.pending_level_init) if getattr(env, "pending_level_init", None) is not None else None
    visible_level = effective_analysis_level(
        game_dir,
        frontier_level=load_frontier_level_from_arc_state() or pending_level or int(env.current_level),
    )
    current_level = int(visible_level) if visible_level is not None else (pending_level or int(env.current_level))
    levels_completed = max(int(env.levels_completed), max(0, current_level - 1))
    available_model_levels = [int(v) for v in env.available_model_levels]
    if visible_level is not None:
        available_model_levels = [lvl for lvl in available_model_levels if int(lvl) <= int(visible_level)]
    return {
        "state": str(env.state),
        "current_level": current_level,
        "levels_completed": levels_completed,
        **state_transition_flags(env),
        "win_levels": int(env.win_levels),
        "guid": getattr(env, "guid", None),
        "available_model_levels": available_model_levels,
        "full_reset": bool(getattr(env, "full_reset", False)),
    }
