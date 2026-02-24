from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any


def _read_int(path: Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except Exception:
        return None


def _pid_alive(pid: int | None) -> bool:
    if pid is None:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        parsed = json.loads(path.read_text())
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def _read_last_jsonl(path: Path) -> dict[str, Any] | None:
    try:
        lines = path.read_text().splitlines()
    except Exception:
        return None
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except Exception:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def format_repl_health_summary(runtime) -> str:
    session_key = str(getattr(runtime, "active_repl_session_key", "") or "").strip()
    if not session_key:
        return "repl_health: session_key=missing"

    session_dir = runtime.arc_state_dir / "repl-sessions" / session_key
    pid_file = session_dir / "daemon.pid"
    meta_file = session_dir / "session.json"
    lifecycle_file = session_dir / "daemon.lifecycle.jsonl"

    pid = _read_int(pid_file) if pid_file.exists() else None
    alive = _pid_alive(pid)
    expected_pid = getattr(runtime, "last_repl_daemon_pid", None)
    expected_fragment = "unknown"
    if isinstance(expected_pid, int):
        expected_fragment = "yes" if pid == expected_pid else "no"

    meta = _read_json(meta_file) if meta_file.exists() else None
    status = str((meta or {}).get("status", "missing"))
    meta_game = str((meta or {}).get("game_id", "") or "")

    last_event = _read_last_jsonl(lifecycle_file) if lifecycle_file.exists() else None
    event_name = str((last_event or {}).get("event", "missing"))
    event_age = "n/a"
    ts = (last_event or {}).get("ts_unix")
    if isinstance(ts, (int, float)):
        event_age = f"{max(0.0, time.time() - float(ts)):.1f}s"

    return (
        "repl_health: "
        f"session_key={session_key} "
        f"pid={pid if pid is not None else 'missing'} "
        f"alive={str(alive).lower()} "
        f"matches_last_seen={expected_fragment} "
        f"meta_status={status} "
        f"meta_game={meta_game or '?'} "
        f"last_event={event_name} "
        f"last_event_age={event_age}"
    )
