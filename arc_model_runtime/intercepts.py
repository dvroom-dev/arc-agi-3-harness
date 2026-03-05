from __future__ import annotations

import os
import time
from pathlib import Path

IDLE_KEEPALIVE_INTERCEPT_MARKER = "__ARC_INTERCEPT_IDLE_KEEPALIVE__"
IDLE_KEEPALIVE_SECONDS = 12 * 60


def _idle_stamp_path() -> Path:
    arc_state_dir = Path(str(os.getenv("ARC_STATE_DIR", "") or "")).expanduser()
    if not str(arc_state_dir).strip():
        arc_state_dir = Path.cwd() / ".arc"
    arc_state_dir.mkdir(parents=True, exist_ok=True)
    return arc_state_dir / "last_real_game_action_at.txt"


def _idle_keepalive_needed() -> tuple[bool, int]:
    if not str(os.getenv("ARC_SCORECARD_ID", "") or "").strip():
        return False, 0
    path = _idle_stamp_path()
    now = time.monotonic()
    if not path.exists():
        try:
            path.write_text(f"{now:.6f}\n", encoding="utf-8")
        except Exception:
            pass
        return False, 0
    try:
        stamp = float(path.read_text(encoding="utf-8").strip())
    except Exception:
        stamp = now
    idle_seconds = max(0, int(now - stamp))
    return idle_seconds >= IDLE_KEEPALIVE_SECONDS, idle_seconds


def inject_idle_hint(payload: dict, *, action_name: str) -> None:
    needed, idle_seconds = _idle_keepalive_needed()
    if not needed:
        return
    payload["intercept_hint"] = (
        f"{IDLE_KEEPALIVE_INTERCEPT_MARKER} "
        f"idle_seconds={idle_seconds} "
        f"action={action_name}"
    )
