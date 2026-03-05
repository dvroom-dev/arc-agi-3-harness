from __future__ import annotations

import os
from pathlib import Path

IDLE_KEEPALIVE_INTERCEPT_MARKER = "__ARC_INTERCEPT_IDLE_KEEPALIVE__"
IDLE_KEEPALIVE_FLAG_REL = "intercepts/idle_keepalive.flag"


def _idle_flag_path() -> Path:
    arc_state_dir = Path(str(os.getenv("ARC_STATE_DIR", "") or "")).expanduser()
    if not str(arc_state_dir).strip():
        arc_state_dir = Path.cwd() / ".arc"
    arc_state_dir.mkdir(parents=True, exist_ok=True)
    return arc_state_dir / IDLE_KEEPALIVE_FLAG_REL


def _consume_idle_keepalive_flag() -> str | None:
    path = _idle_flag_path()
    if not path.exists():
        return None
    try:
        payload = path.read_text(encoding="utf-8").strip()
    except Exception:
        payload = ""
    try:
        path.unlink()
    except Exception:
        pass
    if payload:
        return payload
    return IDLE_KEEPALIVE_INTERCEPT_MARKER


def inject_idle_hint(payload: dict, *, action_name: str) -> None:
    marker_payload = _consume_idle_keepalive_flag()
    if not marker_payload:
        return
    payload["intercept_hint"] = f"{marker_payload} action={action_name}".strip()
