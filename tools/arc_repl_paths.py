from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from uuid import uuid4

from proc_utils import read_proc_start_ticks


def conversation_id_from_env() -> str:
    raw = str(os.getenv("ARC_CONVERSATION_ID", "") or "").strip()
    if not raw:
        raw = "default"
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("._")
    return safe[:120] or "default"


def session_key_from_env() -> str:
    raw = str(os.getenv("ARC_REPL_SESSION_KEY", "") or "").strip()
    if raw:
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("._")
        return safe[:120] or "default"
    return conversation_id_from_env()


def spawn_parent_identity_from_env() -> tuple[int | None, int | None]:
    raw_pid = str(os.getenv("ARC_REPL_PARENT_PID", "") or "").strip()
    if not raw_pid:
        return None, None
    try:
        parent_pid = int(raw_pid)
    except Exception:
        return None, None
    if parent_pid <= 1:
        return None, None

    raw_ticks = str(os.getenv("ARC_REPL_PARENT_START_TICKS", "") or "").strip()
    if raw_ticks:
        try:
            return parent_pid, int(raw_ticks)
        except Exception:
            pass
    return parent_pid, read_proc_start_ticks(parent_pid)


def session_dir(arc_dir: Path, conversation_id: str) -> Path:
    return arc_dir / "repl-sessions" / conversation_id


def socket_path(arc_dir: Path, conversation_id: str) -> Path:
    # Use a stable per-session marker path so calls from subdirectories resolve consistently.
    return session_dir(arc_dir, conversation_id) / "daemon.ready"


def pid_path(arc_dir: Path, conversation_id: str) -> Path:
    return session_dir(arc_dir, conversation_id) / "daemon.pid"


def meta_path(arc_dir: Path, conversation_id: str) -> Path:
    return session_dir(arc_dir, conversation_id) / "session.json"


def daemon_log_path(arc_dir: Path, conversation_id: str) -> Path:
    return session_dir(arc_dir, conversation_id) / "daemon.log"


def lifecycle_path(arc_dir: Path, conversation_id: str) -> Path:
    return session_dir(arc_dir, conversation_id) / "daemon.lifecycle.jsonl"


def _session_workspace_root(arc_dir: Path, conversation_id: str, cwd: Path) -> Path:
    root = cwd.resolve()
    meta = meta_path(arc_dir, conversation_id)
    if not meta.exists():
        return root
    try:
        payload = json.loads(meta.read_text(encoding="utf-8"))
    except Exception:
        return root
    if isinstance(payload, dict):
        raw = str(payload.get("workspace_root") or payload.get("cwd") or "").strip()
        if raw:
            try:
                return Path(raw).expanduser().resolve()
            except Exception:
                return Path(raw).expanduser()
    return root


def ipc_paths(arc_dir: Path, conversation_id: str, cwd: Path) -> tuple[Path, Path]:
    ipc_dir = _session_workspace_root(arc_dir, conversation_id, cwd) / ".arc_repl_ipc" / conversation_id
    return ipc_dir / "requests", ipc_dir / "responses"


def send_ipc_request(
    *,
    arc_dir: Path,
    cwd: Path,
    conversation_id: str,
    request: dict,
    timeout_s: float,
) -> dict:
    requests_dir, responses_dir = ipc_paths(arc_dir, conversation_id, cwd)
    requests_dir.mkdir(parents=True, exist_ok=True)
    responses_dir.mkdir(parents=True, exist_ok=True)

    request_id = f"{time.time_ns()}_{os.getpid()}_{uuid4().hex}"
    request_file = requests_dir / f"{request_id}.json"
    response_file = responses_dir / f"{request_id}.json"

    tmp_request = request_file.with_suffix(".json.tmp")
    tmp_request.write_text(json.dumps(request), encoding="utf-8")
    tmp_request.replace(request_file)

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if response_file.exists():
            try:
                payload = json.loads(response_file.read_text(encoding="utf-8"))
            finally:
                try:
                    response_file.unlink()
                except Exception:
                    pass
            if not isinstance(payload, dict):
                raise RuntimeError("daemon returned non-object response")
            return payload
        time.sleep(0.05)
    raise RuntimeError(f"arc_repl daemon response timeout after {timeout_s}s")
