from __future__ import annotations

import json
import os
import signal
import sys
import time
import traceback
from pathlib import Path
from typing import Callable


def run_daemon(
    *,
    cwd: Path,
    conversation_id: str,
    requested_game_id: str,
    socket_path: Path,
    socket_endpoint: tuple[str, int],
    socket_family: str,
    meta_path: Path,
    make_session: Callable[[], object],
    append_lifecycle_event: Callable[..., None],
    error_payload: Callable[..., dict],
    schema_version: str,
    listener_factory,
) -> int:
    # Detach daemon from terminal interrupt/hangup signals so agent/harness
    # keyboard interrupts do not silently kill session state mid-run.
    for sig_name in ("SIGINT", "SIGHUP"):
        sig = getattr(signal, sig_name, None)
        if sig is None:
            continue
        try:
            signal.signal(sig, signal.SIG_IGN)
        except Exception:
            pass

    append_lifecycle_event(
        cwd,
        conversation_id,
        "daemon_boot",
        daemon_pid=int(os.getpid()),
        requested_game_id=str(requested_game_id),
    )
    session = make_session()
    started_at_unix = time.time()
    meta_path.write_text(
        json.dumps(
            {
                "conversation_id": conversation_id,
                "game_id": session.game_id,
                "socket": f"tcp://{socket_endpoint[0]}:{socket_endpoint[1]}",
                "socket_path": str(socket_path),
                "pid": os.getpid(),
                "started_at_unix": started_at_unix,
                "status": "running",
            },
            indent=2,
        )
        + "\n"
    )
    append_lifecycle_event(
        cwd,
        conversation_id,
        "daemon_ready",
        daemon_pid=int(os.getpid()),
        game_id=str(session.game_id),
        socket=f"tcp://{socket_endpoint[0]}:{socket_endpoint[1]}",
        socket_path=str(socket_path),
    )

    listener = listener_factory(socket_endpoint, family=socket_family)
    socket_path.write_text(f"{socket_endpoint[0]}:{socket_endpoint[1]}\n")
    should_stop = False
    try:
        while not should_stop:
            conn = listener.accept()
            request: dict | None = None
            try:
                request = conn.recv()
                if not isinstance(request, dict):
                    conn.send({"ok": False, "error": "request must be an object"})
                    continue
                action = str(request.get("action", "")).strip()
                req_game_id = str(request.get("game_id", "") or "").strip()

                if action == "ping":
                    conn.send({"ok": True, "action": "ping"})
                    continue
                if action == "status":
                    result = session.do_status(req_game_id, session_created=False)
                elif action == "reset_level":
                    result = session.do_reset_level(req_game_id, session_created=False)
                elif action == "exec":
                    script = str(request.get("script", "") or "")
                    source = str(request.get("source", "") or "").strip() or None
                    script_path = str(request.get("script_path", "") or "").strip() or None
                    result = session.do_exec(
                        req_game_id,
                        script,
                        session_created=False,
                        source=source,
                        script_path=script_path,
                    )
                elif action == "shutdown":
                    result = {
                        "schema_version": schema_version,
                        "ok": True,
                        "action": "shutdown",
                        "conversation_id": conversation_id,
                        "game_id": session.game_id,
                    }
                    should_stop = True
                else:
                    result = error_payload(
                        action=action,
                        requested_game_id=req_game_id,
                        message="unknown action. expected: status|exec|reset_level|shutdown",
                        error_type="unknown_action",
                    )
                conn.send(result)
            except Exception as exc:
                traceback_text = traceback.format_exc()
                append_lifecycle_event(
                    cwd,
                    conversation_id,
                    "request_exception",
                    daemon_pid=int(os.getpid()),
                    request_action=str(request.get("action", "") if isinstance(request, dict) else ""),
                    error=str(exc),
                )
                print(traceback_text, file=sys.stderr, flush=True)
                conn.send(
                    {
                        "schema_version": schema_version,
                        "ok": False,
                        "error": {
                            "type": "daemon_exception",
                            "message": str(exc),
                            "details": traceback_text,
                        },
                    }
                )
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
    finally:
        try:
            meta_path.write_text(
                json.dumps(
                    {
                        "conversation_id": conversation_id,
                        "game_id": session.game_id,
                        "socket": f"tcp://{socket_endpoint[0]}:{socket_endpoint[1]}",
                        "socket_path": str(socket_path),
                        "pid": os.getpid(),
                        "started_at_unix": started_at_unix,
                        "stopped_at_unix": time.time(),
                        "status": "stopped",
                    },
                    indent=2,
                )
                + "\n"
            )
        except Exception:
            pass
        append_lifecycle_event(
            cwd,
            conversation_id,
            "daemon_stop",
            daemon_pid=int(os.getpid()),
            graceful=bool(should_stop),
        )
        try:
            listener.close()
        except Exception:
            pass
        try:
            if socket_path.exists():
                socket_path.unlink()
        except Exception:
            pass
    return 0
