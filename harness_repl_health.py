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


def collect_repl_health(runtime) -> dict[str, Any]:
    session_key = str(getattr(runtime, "active_repl_session_key", "") or "").strip()
    if not session_key:
        return {
            "session_key": "",
            "pid": None,
            "alive": False,
            "matches_last_seen": "unknown",
            "meta_status": "missing",
            "meta_game": "",
            "last_event": "missing",
            "last_event_age_s": None,
            "is_crashed": False,
            "session_dir": None,
            "lifecycle_file": None,
            "log_file": None,
        }

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
    ts = (last_event or {}).get("ts_unix")
    event_age_s: float | None = None
    if isinstance(ts, (int, float)):
        event_age_s = max(0.0, time.time() - float(ts))

    pid_mismatch = isinstance(expected_pid, int) and pid != expected_pid
    stopped = event_name in {"daemon_stop", "daemon_fatal_exception"} or status == "stopped"
    is_crashed = bool((not alive and isinstance(expected_pid, int)) or pid_mismatch or stopped)

    return {
        "session_key": session_key,
        "pid": pid,
        "alive": alive,
        "matches_last_seen": expected_fragment,
        "meta_status": status,
        "meta_game": meta_game,
        "last_event": event_name,
        "last_event_age_s": event_age_s,
        "is_crashed": is_crashed,
        "session_dir": session_dir,
        "lifecycle_file": lifecycle_file,
        "log_file": session_dir / "daemon.log",
    }


def _tail(path: Path, n: int = 40) -> str:
    try:
        lines = path.read_text().splitlines()
    except Exception:
        return ""
    return "\n".join(lines[-max(1, int(n)):])


def format_repl_crash_diagnostics(runtime, health: dict[str, Any] | None = None) -> str:
    info = health or collect_repl_health(runtime)
    session_dir = info.get("session_dir")
    lifecycle_file = info.get("lifecycle_file")
    log_file = info.get("log_file")
    lifecycle_tail = _tail(lifecycle_file, 20) if isinstance(lifecycle_file, Path) else ""
    log_tail = _tail(log_file, 80) if isinstance(log_file, Path) else ""
    parts = [
        "repl_crash_diagnostics:",
        f"session_key={info.get('session_key', '')}",
        f"session_dir={session_dir}",
        f"pid={info.get('pid')} alive={info.get('alive')}",
        f"matches_last_seen={info.get('matches_last_seen')}",
        f"meta_status={info.get('meta_status')} meta_game={info.get('meta_game')}",
        f"last_event={info.get('last_event')} last_event_age_s={info.get('last_event_age_s')}",
    ]
    if lifecycle_tail:
        parts.append("lifecycle_tail:")
        parts.append(lifecycle_tail)
    if log_tail:
        parts.append("daemon_log_tail:")
        parts.append(log_tail[-8000:])
    return "\n".join(parts)


def format_repl_health_summary(runtime) -> str:
    info = collect_repl_health(runtime)
    session_key = str(info.get("session_key", "") or "").strip()
    if not session_key:
        return "repl_health: session_key=missing"
    event_age = "n/a"
    event_age_s = info.get("last_event_age_s")
    if isinstance(event_age_s, (int, float)):
        event_age = f"{max(0.0, float(event_age_s)):.1f}s"
    return (
        "repl_health: "
        f"session_key={session_key} "
        f"pid={info.get('pid') if info.get('pid') is not None else 'missing'} "
        f"alive={str(bool(info.get('alive'))).lower()} "
        f"matches_last_seen={info.get('matches_last_seen')} "
        f"meta_status={info.get('meta_status')} "
        f"meta_game={str(info.get('meta_game') or '?')} "
        f"last_event={info.get('last_event')} "
        f"last_event_age={event_age}"
    )
