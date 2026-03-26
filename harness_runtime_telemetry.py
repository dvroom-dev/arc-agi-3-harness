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
    last_error_path = runtime.telemetry_dir / "last_error.json"
    if ok:
        if last_error_path.exists():
            try:
                payload = json.loads(last_error_path.read_text(encoding="utf-8"))
            except Exception:
                payload = None
            if (
                isinstance(payload, dict)
                and str(payload.get("category") or "").strip() == entry["category"]
                and str(payload.get("name") or "").strip() == entry["name"]
            ):
                last_error_path.unlink(missing_ok=True)
        return
    if not ok:
        last_error = {
            "timestamp": entry["timestamp"],
            "session_name": entry["session_name"],
            "game_id": entry["game_id"],
            "active_game_id": entry["active_game_id"],
            "scorecard_id": entry["scorecard_id"],
            "category": entry["category"],
            "name": entry["name"],
            "error": entry.get("error"),
            "meta": entry.get("meta"),
        }
        last_error_path.write_text(json.dumps(last_error, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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
        if getattr(exc, "detail", None):
            phase_metadata["detail"] = str(getattr(exc, "detail"))
        if getattr(exc, "process_name", None):
            phase_metadata["process_name"] = str(getattr(exc, "process_name"))
        if getattr(exc, "return_code", None) is not None:
            try:
                phase_metadata["return_code"] = int(getattr(exc, "return_code"))
            except Exception:
                phase_metadata["return_code"] = str(getattr(exc, "return_code"))
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
