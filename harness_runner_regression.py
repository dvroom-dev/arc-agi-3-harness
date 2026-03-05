from __future__ import annotations

def _as_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _find_step_level_regression(
    *,
    levels_before_resume: int,
    new_events: list[dict],
) -> dict | None:
    """Find the first step event that regresses levels_completed within new events."""
    last_levels = int(levels_before_resume)
    for idx, event in enumerate(new_events):
        if str(event.get("kind", "")).strip() != "step":
            continue
        levels_now = _as_int(event.get("levels_completed", last_levels), last_levels)
        if levels_now < last_levels:
            return {
                "event_offset": idx,
                "action": str(event.get("action", "")).strip() or "?",
                "from_levels_completed": int(last_levels),
                "to_levels_completed": int(levels_now),
            }
        last_levels = levels_now
    return None


def _classify_level_drop(
    *,
    prev_state: dict | None,
    post_state: dict | None,
    new_events: list[dict],
) -> dict | None:
    """Classify a level drop; returns None when no hard-stop is needed."""
    prev_levels = _as_int((prev_state or {}).get("levels_completed", 0), 0)
    post_levels = _as_int((post_state or {}).get("levels_completed", prev_levels), prev_levels)
    if post_levels >= prev_levels:
        return None

    post_state_name = str((post_state or {}).get("state", "")).strip().upper()
    if post_state_name == "GAME_OVER":
        return {
            "kind": "drop_after_game_over",
            "from_levels_completed": prev_levels,
            "to_levels_completed": post_levels,
        }

    confirmed = _find_step_level_regression(
        levels_before_resume=prev_levels,
        new_events=new_events,
    )
    if confirmed:
        return {
            "kind": "confirmed_step_regression_without_game_over",
            **confirmed,
        }

    return {
        "kind": "unconfirmed_level_drop_without_game_over",
        "from_levels_completed": prev_levels,
        "to_levels_completed": post_levels,
    }
