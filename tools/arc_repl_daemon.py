from __future__ import annotations

import json
import os
import signal
import sys
import time
import traceback
from pathlib import Path
from typing import Callable


def _read_proc_start_ticks(pid: int) -> int | None:
    stat_path = Path("/proc") / str(int(pid)) / "stat"
    try:
        raw = stat_path.read_text(encoding="utf-8")
    except Exception:
        return None
    try:
        # /proc/<pid>/stat field 22 is process starttime in clock ticks.
        return int(raw.rsplit(")", 1)[1].split()[19])
    except Exception:
        return None


def _parent_alive(parent_pid: int | None, parent_start_ticks: int | None) -> bool:
    if parent_pid is None:
        return True
    try:
        pid = int(parent_pid)
    except Exception:
        return False
    if pid <= 1:
        return False

    current_start_ticks = _read_proc_start_ticks(pid)
    if parent_start_ticks is not None:
        if current_start_ticks is None:
            return False
        if int(current_start_ticks) != int(parent_start_ticks):
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def run_daemon(
    *,
    cwd: Path,
    conversation_id: str,
    requested_game_id: str,
    socket_path: Path,
    meta_path: Path,
    make_session: Callable[[], object],
    append_lifecycle_event: Callable[..., None],
    error_payload: Callable[..., dict],
    schema_version: str,
    parent_pid: int | None = None,
    parent_start_ticks: int | None = None,
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
        parent_pid=(int(parent_pid) if parent_pid is not None else None),
        parent_start_ticks=(
            int(parent_start_ticks) if parent_start_ticks is not None else None
        ),
    )
    session = make_session()
    started_at_unix = time.time()
    meta_path.write_text(
        json.dumps(
            {
                "conversation_id": conversation_id,
                "game_id": session.game_id,
                "transport": "file",
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
        transport="file",
        socket_path=str(socket_path),
    )

    ipc_dir = meta_path.parent / "ipc"
    requests_dir = ipc_dir / "requests"
    responses_dir = ipc_dir / "responses"
    requests_dir.mkdir(parents=True, exist_ok=True)
    responses_dir.mkdir(parents=True, exist_ok=True)
    socket_path.write_text("file-ipc\n", encoding="utf-8")

    def _send_response(request_file: Path, response_payload: dict) -> None:
        response_file = responses_dir / request_file.name
        tmp_file = response_file.with_suffix(response_file.suffix + ".tmp")
        tmp_file.write_text(json.dumps(response_payload), encoding="utf-8")
        tmp_file.replace(response_file)

    def _handle_request(request: dict) -> tuple[dict, bool]:
        action = str(request.get("action", "")).strip()
        req_game_id = str(request.get("game_id", "") or "").strip()

        if action == "ping":
            return {"ok": True, "action": "ping"}, False
        if action == "status":
            return session.do_status(req_game_id, session_created=False), False
        if action == "reset_level":
            return session.do_reset_level(req_game_id, session_created=False), False
        if action == "exec":
            script = str(request.get("script", "") or "")
            source = str(request.get("source", "") or "").strip() or None
            script_path = str(request.get("script_path", "") or "").strip() or None
            return (
                session.do_exec(
                    req_game_id,
                    script,
                    session_created=False,
                    source=source,
                    script_path=script_path,
                ),
                False,
            )
        if action == "shutdown":
            return (
                {
                    "schema_version": schema_version,
                    "ok": True,
                    "action": "shutdown",
                    "conversation_id": conversation_id,
                    "game_id": session.game_id,
                },
                True,
            )
        return (
            error_payload(
                action=action,
                requested_game_id=req_game_id,
                message="unknown action. expected: status|exec|reset_level|shutdown",
                error_type="unknown_action",
            ),
            False,
        )

    should_stop = False
    stop_reason = "shutdown"
    next_parent_check = 0.0
    try:
        while not should_stop:
            now = time.monotonic()
            if now >= next_parent_check:
                next_parent_check = now + 1.0
                if not _parent_alive(parent_pid, parent_start_ticks):
                    stop_reason = "parent_exit"
                    append_lifecycle_event(
                        cwd,
                        conversation_id,
                        "daemon_parent_exit_detected",
                        daemon_pid=int(os.getpid()),
                        parent_pid=(int(parent_pid) if parent_pid is not None else None),
                    )
                    break
            request_file: Path | None = None
            try:
                request_candidates = sorted(requests_dir.glob("*.json"))
                if not request_candidates:
                    time.sleep(0.05)
                    continue
                request_file = request_candidates[0]
                request = json.loads(request_file.read_text(encoding="utf-8"))
                if not isinstance(request, dict):
                    _send_response(
                        request_file,
                        {"schema_version": schema_version, "ok": False, "error": "request must be an object"},
                    )
                    continue
                result, should_stop = _handle_request(request)
                if should_stop:
                    stop_reason = "shutdown_request"
                _send_response(request_file, result)
            except Exception as exc:
                traceback_text = traceback.format_exc()
                append_lifecycle_event(
                    cwd,
                    conversation_id,
                    "request_exception",
                    daemon_pid=int(os.getpid()),
                    request_action="",
                    error=str(exc),
                )
                print(traceback_text, file=sys.stderr, flush=True)
                if request_file is not None and request_file.exists():
                    _send_response(
                        request_file,
                        {
                            "schema_version": schema_version,
                            "ok": False,
                            "error": {
                                "type": "daemon_exception",
                                "message": str(exc),
                                "details": traceback_text,
                            },
                        },
                    )
            finally:
                try:
                    if request_file is not None and request_file.exists():
                        request_file.unlink()
                except Exception:
                    pass
    finally:
        try:
            meta_path.write_text(
                json.dumps(
                    {
                        "conversation_id": conversation_id,
                        "game_id": session.game_id,
                        "transport": "file",
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
            reason=str(stop_reason),
        )
        try:
            if socket_path.exists():
                socket_path.unlink()
        except Exception:
            pass
    return 0
