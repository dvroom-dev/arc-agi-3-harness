from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path

IDLE_KEEPALIVE_INTERCEPT_MARKER = "__ARC_INTERCEPT_IDLE_KEEPALIVE__"
COMPARE_CLEAN_INTERCEPT_MARKER = "__ARC_INTERCEPT_COMPARE_CLEAN__"
IDLE_KEEPALIVE_FLAG_REL = "intercepts/idle_keepalive.flag"
IDLE_KEEPALIVE_TRIGGER_SECONDS = 12 * 60


def _idle_flag_path() -> Path:
    arc_state_dir = Path(str(os.getenv("ARC_STATE_DIR", "") or "")).expanduser()
    if not str(arc_state_dir).strip():
        arc_state_dir = Path.cwd() / ".arc"
    arc_state_dir.mkdir(parents=True, exist_ok=True)
    return arc_state_dir / IDLE_KEEPALIVE_FLAG_REL


def _peek_idle_keepalive_flag() -> str | None:
    path = _idle_flag_path()
    if not path.exists():
        return None
    try:
        payload = path.read_text(encoding="utf-8").strip()
    except Exception:
        payload = ""
    return payload or IDLE_KEEPALIVE_INTERCEPT_MARKER


def _idle_keepalive_enabled_from_env() -> bool:
    if str(os.getenv("ARC_OPERATION_MODE", "") or "").strip().upper() != "ONLINE":
        return False
    backend = str(os.getenv("ARC_BACKEND", "") or "").strip().lower()
    if backend:
        return backend == "api"
    base_url = str(os.getenv("ARC_BASE_URL", "") or "").strip().lower()
    if not base_url:
        return False
    return "three.arcprize.org" in base_url


def _parse_iso8601_utc(value: object) -> datetime | None:
    s = str(value or "").strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _idle_seconds_from_action_history(action_history_path: Path, *, now_utc: datetime) -> int | None:
    if not action_history_path.exists():
        return None
    try:
        payload = json.loads(action_history_path.read_text())
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    records = payload.get("records")
    if not isinstance(records, list) or not records:
        return None
    for rec in reversed(records):
        if not isinstance(rec, dict):
            continue
        ts = _parse_iso8601_utc(rec.get("recorded_at_utc"))
        if ts is None:
            continue
        return max(0, int((now_utc - ts).total_seconds()))
    return None


def _ensure_idle_keepalive_flag(payload: dict) -> str | None:
    if not _idle_keepalive_enabled_from_env():
        return None
    existing = _peek_idle_keepalive_flag()
    if existing:
        return existing

    action_history_file = str(payload.get("action_history_file", "") or "").strip()
    if action_history_file:
        action_history_path = Path(action_history_file)
    else:
        action_history_path = _idle_flag_path().parent.parent / "action-history.json"

    now_utc = datetime.now(timezone.utc)
    idle_seconds = _idle_seconds_from_action_history(action_history_path, now_utc=now_utc)
    if idle_seconds is None or idle_seconds < IDLE_KEEPALIVE_TRIGGER_SECONDS:
        return None

    level = payload.get("current_level")
    try:
        level_txt = str(int(level))
    except Exception:
        level_txt = "NA"
    queued_at_unix = int(now_utc.timestamp())
    marker_payload = (
        f"{IDLE_KEEPALIVE_INTERCEPT_MARKER} "
        f"idle_seconds={int(idle_seconds)} "
        f"level={level_txt} "
        f"source=tool "
        f"queued_at_unix={queued_at_unix}"
    ).strip()
    flag_path = _idle_flag_path()
    flag_path.parent.mkdir(parents=True, exist_ok=True)
    flag_path.write_text(marker_payload + "\n", encoding="utf-8")
    return marker_payload


def inject_idle_hint(payload: dict, *, action_name: str) -> None:
    if not isinstance(payload, dict):
        return
    markers: list[str] = []

    if (
        str(action_name).strip().lower() == "compare_sequences"
        and bool(payload.get("ok"))
        and bool(payload.get("all_match"))
    ):
        markers.append(COMPARE_CLEAN_INTERCEPT_MARKER)

    marker_payload = _ensure_idle_keepalive_flag(payload)
    if marker_payload:
        markers.append(f"{marker_payload} action={action_name}".strip())

    if not markers:
        return
    payload["intercept_hints"] = markers
    payload["intercept_hint"] = " | ".join(markers)
