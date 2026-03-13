from __future__ import annotations

import json
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator


def _sanitize_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(key): _sanitize_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize_value(item) for item in value]
    return str(value)


def append_phase_timing_impl(
    runtime,
    *,
    category: str,
    name: str,
    elapsed_ms: int,
    ok: bool,
    metadata: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    runtime.telemetry_dir.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_name": runtime.session_name,
        "game_id": str(getattr(runtime.args, "game_id", "") or ""),
        "active_game_id": str(getattr(runtime, "active_game_id", "") or ""),
        "scorecard_id": getattr(runtime, "active_scorecard_id", None),
        "category": str(category),
        "name": str(name),
        "elapsed_ms": max(0, int(elapsed_ms)),
        "ok": bool(ok),
    }
    if error:
        entry["error"] = str(error)
    if metadata:
        entry["meta"] = _sanitize_value(metadata)
    with runtime.phase_timings_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")


@contextmanager
def phase_scope_impl(
    runtime,
    *,
    category: str,
    name: str,
    metadata: dict[str, Any] | None = None,
) -> Iterator[dict[str, Any]]:
    started_at = time.monotonic()
    phase_metadata: dict[str, Any] = dict(metadata or {})
    ok = True
    error: str | None = None
    try:
        yield phase_metadata
    except BaseException as exc:
        ok = False
        error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        append_phase_timing_impl(
            runtime,
            category=category,
            name=name,
            elapsed_ms=int(round((time.monotonic() - started_at) * 1000)),
            ok=ok,
            metadata=phase_metadata,
            error=error,
        )
