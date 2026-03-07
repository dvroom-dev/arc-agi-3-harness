from __future__ import annotations

import time

IDLE_KEEPALIVE_TRIGGER_SECONDS = 12 * 60
IDLE_KEEPALIVE_MARKER = "__ARC_INTERCEPT_IDLE_KEEPALIVE__"


def marker_fields(payload: str | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for token in str(payload or "").strip().split():
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        out[key.strip()] = value.strip()
    return out


def log_keepalive_resolution(runtime, marker_payload: str | None, *, reason: str) -> None:
    marker_text = str(marker_payload or "").strip()
    if not marker_text:
        return
    fields = marker_fields(marker_text)
    queued_at_unix = fields.get("queued_at_unix")
    latency_seconds: int | None = None
    if queued_at_unix:
        try:
            latency_seconds = max(0, int(time.time() - float(queued_at_unix)))
        except Exception:
            latency_seconds = None
    idle_seconds_at_queue = fields.get("idle_seconds")
    runtime.log(
        "[harness] keepalive resolved: "
        f"reason={reason} "
        f"latency_seconds={latency_seconds if latency_seconds is not None else 'NA'} "
        f"idle_seconds_at_queue={idle_seconds_at_queue or 'NA'} "
        f"marker=\"{marker_text}\""
    )


def events_include_real_game_action(events: list[dict]) -> bool:
    for event in events:
        kind = str(event.get("kind", "")).strip().lower()
        if kind in {"step", "reset"}:
            return True
    return False
