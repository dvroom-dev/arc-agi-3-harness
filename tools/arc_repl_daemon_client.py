from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable


def spawn_daemon(
    *,
    cwd: Path,
    conversation_id: str,
    game_id: str,
    session_dir_fn: Callable[[Path, str], Path],
    socket_path_fn: Callable[[Path, str], Path],
    daemon_log_path_fn: Callable[[Path, str], Path],
    pid_path_fn: Callable[[Path, str], Path],
    append_lifecycle_event: Callable[..., None],
    spawn_parent_identity_from_env: Callable[[], tuple[int | None, int | None]],
    daemon_entry: Path,
) -> None:
    session_dir = session_dir_fn(cwd, conversation_id)
    session_dir.mkdir(parents=True, exist_ok=True)
    socket_path = socket_path_fn(cwd, conversation_id)
    if socket_path.exists():
        try:
            socket_path.unlink()
        except Exception:
            pass
    log_path = daemon_log_path_fn(cwd, conversation_id)
    with log_path.open("a", encoding="utf-8") as logf:
        parent_pid, parent_start_ticks = spawn_parent_identity_from_env()
        daemon_cmd = [
            sys.executable,
            str(daemon_entry),
            "--daemon",
            "--cwd",
            str(cwd),
            "--conversation-id",
            conversation_id,
            "--game-id",
            game_id,
        ]
        if parent_pid is not None:
            daemon_cmd.extend(["--parent-pid", str(parent_pid)])
            if parent_start_ticks is not None:
                daemon_cmd.extend(["--parent-start-ticks", str(parent_start_ticks)])
        proc = subprocess.Popen(
            daemon_cmd,
            cwd=str(cwd),
            env=dict(os.environ),
            stdin=subprocess.DEVNULL,
            stdout=logf,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    pid_path_fn(cwd, conversation_id).write_text(str(proc.pid) + "\n")
    append_lifecycle_event(
        cwd,
        conversation_id,
        "spawned",
        daemon_pid=int(proc.pid),
        game_id=str(game_id),
        parent_pid=int(os.getpid()),
        lifecycle_parent_pid=(int(parent_pid) if parent_pid is not None else None),
        lifecycle_parent_start_ticks=(
            int(parent_start_ticks) if parent_start_ticks is not None else None
        ),
        transport="file",
        socket_path=str(socket_path),
        log_file=str(log_path),
    )


def wait_for_daemon(
    *,
    cwd: Path,
    conversation_id: str,
    socket_path_fn: Callable[[Path, str], Path],
    send_ipc_request_fn: Callable[[Path, str, dict, float], dict],
    append_lifecycle_event: Callable[..., None],
    timeout_s: float,
) -> None:
    socket_path = socket_path_fn(cwd, conversation_id)
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if socket_path.exists():
            try:
                resp = send_ipc_request_fn(
                    cwd,
                    conversation_id,
                    {"action": "ping", "game_id": ""},
                    1.0,
                )
                if isinstance(resp, dict) and bool(resp.get("ok")):
                    return
            except Exception:
                pass
        time.sleep(0.05)
    append_lifecycle_event(
        cwd,
        conversation_id,
        "wait_timeout",
        timeout_s=float(timeout_s),
        transport="file",
        socket_path=str(socket_path),
    )
    raise RuntimeError(f"arc_repl daemon did not start within {timeout_s}s")
