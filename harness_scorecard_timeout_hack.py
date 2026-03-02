from __future__ import annotations

import time


# HACK(scorecard-timeout-keepalive):
# Temporary mitigation for 15-minute scorecard inactivity timeout.
# Remove this module once we have a first-class heartbeat/keepalive in the toolkit flow.
KEEPALIVE_IDLE_SECONDS = 14 * 60

def _post_scorecard_keepalive_reset(rt) -> None:
    """Touch scorecard activity without mutating the active play guid.

    IMPORTANT:
    - Send a raw REST request directly.
    - Do not route through SDK wrapper state.
    - Do not send guid.
    - Ignore response body content.
    """
    try:
        import requests
    except Exception as exc:
        raise RuntimeError(f"requests unavailable for keepalive REST call: {exc}") from exc

    game_id = str(getattr(rt, "active_game_id", "") or getattr(rt.args, "game_id", "")).strip()
    if not game_id:
        raise RuntimeError("missing game_id for keepalive")
    card_id = str(getattr(rt, "active_scorecard_id", "") or "").strip()
    if not card_id:
        raise RuntimeError("missing scorecard_id for keepalive")
    arc_api_key = str(getattr(rt, "arc_api_key", "") or "").strip()
    if not arc_api_key:
        raise RuntimeError("missing ARC_API_KEY for keepalive")
    arc_base_url = str(getattr(rt, "arc_base_url", "") or "").strip()
    if not arc_base_url:
        raise RuntimeError("missing arc_base_url for keepalive")

    url = f"{arc_base_url.rstrip('/')}/api/cmd/RESET"
    headers = {
        "X-API-Key": arc_api_key,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    payload = {
        "card_id": card_id,
        "game_id": game_id,
    }
    response = requests.post(url, json=payload, headers=headers, timeout=15)
    response.raise_for_status()


def maybe_inject_scorecard_keepalive_hack(
    rt,
    *,
    last_action_at_monotonic: float,
    agent_history_floor: int,
    now_monotonic: float | None = None,
) -> tuple[float, bool]:
    """Inject one scorecard keepalive if inactivity is near timeout.

    Returns:
      (updated_last_action_timestamp, injected)
    """
    _ = agent_history_floor
    if not getattr(rt, "active_scorecard_id", None):
        return last_action_at_monotonic, False

    now = time.monotonic() if now_monotonic is None else float(now_monotonic)
    if now - float(last_action_at_monotonic) < KEEPALIVE_IDLE_SECONDS:
        return last_action_at_monotonic, False

    try:
        _post_scorecard_keepalive_reset(rt)
    except Exception as exc:
        rt.log(
            "[harness] HACK(scorecard-timeout-keepalive) failed "
            f"(scorecard heartbeat RESET): {exc}"
        )
        return last_action_at_monotonic, False
    rt.log(
        "[harness] HACK(scorecard-timeout-keepalive) injected "
        f"RESET(no-guid) game_id={rt.args.game_id}"
    )
    return now, True
