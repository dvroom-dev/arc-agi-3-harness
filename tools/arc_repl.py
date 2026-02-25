#!/usr/bin/env python3
"""Stateful ARC Python REPL tool for super shell usage."""
from __future__ import annotations

import argparse
import errno
import json
import multiprocessing.connection
import os
import re
import subprocess
import sys
import time
import traceback
from hashlib import sha1
from pathlib import Path

from arc_action_diffs import (
    _change_bbox,
    _iter_cell_changes,
    build_aggregate_diff_record,
    build_step_diff_records,
    format_diff_minimal,
    frame_action_metadata,
    write_game_state,
    write_machine_state,
)
from arc_action_env import (
    _action_from_event_name,
    _get_pixels,
    _make_env,
    _make_id_candidates,
    _replay_history,
)
from arc_action_exec import _write_turn_trace
from arc_action_state import (
    _append_level_completion,
    _arc_dir,
    _completion_action_windows_by_level,
    _default_game_id,
    _ensure_play_lib_file,
    _ensure_level_completions_file,
    _error_payload,
    _read_max_recorded_completion_level,
    _save_history,
)
from arc_action_state import _load_history as _load_history_impl
from arc_repl_daemon import run_daemon
from arc_repl_session_core import (
    BaseReplSession,
    _StopScript,
    _chunk_for_bbox,
    _coerce_grid,
    _grid_from_hex_rows,
    _same_game_lineage as _same_game_lineage_impl,
)

SCHEMA_VERSION = "arc_repl.v1"
SOCKET_WAIT_TIMEOUT_S = 90.0

def _load_history(cwd: Path, game_id: str) -> dict:
    return _load_history_impl(cwd, game_id, _make_id_candidates)

def _lifecycle_path(cwd: Path, conversation_id: str) -> Path:
    return _session_dir(cwd, conversation_id) / "daemon.lifecycle.jsonl"

def _append_lifecycle_event(cwd: Path, conversation_id: str, event: str, **fields: object) -> None:
    try:
        session_dir = _session_dir(cwd, conversation_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "ts_unix": time.time(),
            "event": str(event),
            **fields,
        }
        with _lifecycle_path(cwd, conversation_id).open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=True) + "\n")
    except Exception:
        pass

def _error(*, action: str, requested_game_id: str, message: str, error_type: str, details: str = "") -> dict:
    payload = _error_payload(
        action=action,
        requested_game_id=requested_game_id,
        message=message,
        error_type=error_type,
        details=details,
    )
    payload["schema_version"] = SCHEMA_VERSION
    return payload

def _read_args() -> dict:
    raw = sys.stdin.read().strip()
    if not raw:
        return {"_error": "expected JSON args on stdin"}
    try:
        parsed = json.loads(raw)
    except Exception as exc:
        return {"_error": f"invalid JSON args: {exc}"}
    if not isinstance(parsed, dict):
        return {"_error": "JSON args must be an object"}
    return parsed

def _emit_json(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, indent=2))
    if not sys.stdout.isatty():
        sys.stdout.write("\n")

def _conversation_id() -> str:
    raw = str(os.getenv("ARC_CONVERSATION_ID", "") or "").strip()
    if not raw:
        raw = "default"
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("._")
    return safe[:120] or "default"

def _session_key() -> str:
    raw = str(os.getenv("ARC_REPL_SESSION_KEY", "") or "").strip()
    if raw:
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("._")
        return safe[:120] or "default"
    return _conversation_id()

def _session_dir(cwd: Path, conversation_id: str) -> Path:
    return _arc_dir(cwd) / "repl-sessions" / conversation_id

def _is_socket_permission_error(exc: BaseException) -> bool:
    """True when sandbox/policy blocks AF_UNIX connect/listen operations."""
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if isinstance(cur, PermissionError):
            return True
        if isinstance(cur, OSError) and getattr(cur, "errno", None) in {
            errno.EPERM,
            errno.EACCES,
        }:
            return True
        msg = str(cur).lower()
        if "operation not permitted" in msg or "permission denied" in msg:
            return True
        cur = cur.__cause__ or cur.__context__
    return False

def _socket_path(cwd: Path, conversation_id: str) -> Path:
    key = f"{_arc_dir(cwd)}::{conversation_id}"
    digest = sha1(key.encode("utf-8")).hexdigest()[:20]
    return Path("/tmp") / f"arc-repl-{digest}.sock"

def _pid_path(cwd: Path, conversation_id: str) -> Path:
    return _session_dir(cwd, conversation_id) / "daemon.pid"

def _meta_path(cwd: Path, conversation_id: str) -> Path:
    return _session_dir(cwd, conversation_id) / "session.json"

def _daemon_log_path(cwd: Path, conversation_id: str) -> Path:
    return _session_dir(cwd, conversation_id) / "daemon.log"

def _same_game_lineage(existing_game_id: str, requested_game_id: str) -> bool:
    return _same_game_lineage_impl(existing_game_id, requested_game_id, _make_id_candidates)

class ReplSession(BaseReplSession):
    def __init__(self, *, cwd: Path, conversation_id: str, requested_game_id: str) -> None:
        super().__init__(
            cwd=cwd,
            conversation_id=conversation_id,
            requested_game_id=requested_game_id,
            deps=sys.modules[__name__],
        )

def _spawn_daemon(cwd: Path, conversation_id: str, game_id: str) -> None:
    session_dir = _session_dir(cwd, conversation_id)
    session_dir.mkdir(parents=True, exist_ok=True)

    socket_path = _socket_path(cwd, conversation_id)
    if socket_path.exists():
        try:
            socket_path.unlink()
        except Exception:
            pass

    log_path = _daemon_log_path(cwd, conversation_id)
    with log_path.open("a", encoding="utf-8") as logf:
        proc = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--daemon",
                "--cwd",
                str(cwd),
                "--conversation-id",
                conversation_id,
                "--game-id",
                game_id,
            ],
            cwd=str(cwd),
            env=dict(os.environ),
            stdin=subprocess.DEVNULL,
            stdout=logf,
            stderr=subprocess.STDOUT,
        )
    _pid_path(cwd, conversation_id).write_text(str(proc.pid) + "\n")
    _append_lifecycle_event(
        cwd,
        conversation_id,
        "spawned",
        daemon_pid=int(proc.pid),
        game_id=str(game_id),
        parent_pid=int(os.getpid()),
        socket=str(socket_path),
        log_file=str(log_path),
    )

def _wait_for_daemon(cwd: Path, conversation_id: str, timeout_s: float = SOCKET_WAIT_TIMEOUT_S) -> None:
    socket_path = _socket_path(cwd, conversation_id)
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if socket_path.exists():
            try:
                conn = multiprocessing.connection.Client(str(socket_path), family="AF_UNIX")
            except Exception as exc:
                if _is_socket_permission_error(exc):
                    raise
                time.sleep(0.05)
                continue
            try:
                conn.send({"action": "ping"})
                resp = conn.recv()
                if isinstance(resp, dict) and resp.get("ok"):
                    return
            except Exception:
                pass
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
        time.sleep(0.05)
    _append_lifecycle_event(
        cwd,
        conversation_id,
        "wait_timeout",
        timeout_s=float(timeout_s),
        socket=str(socket_path),
    )
    raise RuntimeError(f"arc_repl daemon did not start within {timeout_s}s")

def _send_request(cwd: Path, conversation_id: str, request: dict) -> tuple[dict, bool]:
    socket_path = _socket_path(cwd, conversation_id)
    session_created = False

    def _try_send() -> dict:
        conn = multiprocessing.connection.Client(str(socket_path), family="AF_UNIX")
        try:
            conn.send(request)
            resp = conn.recv()
            if not isinstance(resp, dict):
                raise RuntimeError("daemon returned non-object response")
            return resp
        finally:
            conn.close()

    def _spawn_for_request(reason: str) -> None:
        nonlocal session_created
        requested_game_id = str(request.get("game_id", "") or "").strip() or _default_game_id(cwd)
        if not requested_game_id:
            raise RuntimeError(
                "game_id is required (or initialize state first with action=status and game_id)"
            )
        _append_lifecycle_event(
            cwd,
            conversation_id,
            "spawn_request",
            reason=str(reason),
            requested_game_id=str(requested_game_id),
            request_action=str(request.get("action", "") or ""),
        )
        _spawn_daemon(cwd, conversation_id, requested_game_id)
        _wait_for_daemon(cwd, conversation_id)
        session_created = True

    if not socket_path.exists():
        _spawn_for_request("socket_missing")

    try:
        return _try_send(), session_created
    except (FileNotFoundError, ConnectionRefusedError):
        if session_created:
            return _try_send(), session_created
        _spawn_for_request("connect_race")
        return _try_send(), session_created

def _daemon_main(cwd: Path, conversation_id: str, requested_game_id: str) -> int:
    session_dir = _session_dir(cwd, conversation_id)
    session_dir.mkdir(parents=True, exist_ok=True)

    socket_path = _socket_path(cwd, conversation_id)
    if socket_path.exists():
        try:
            socket_path.unlink()
        except Exception:
            pass
    return run_daemon(
        cwd=cwd,
        conversation_id=conversation_id,
        requested_game_id=requested_game_id,
        socket_path=socket_path,
        meta_path=_meta_path(cwd, conversation_id),
        make_session=lambda: ReplSession(
            cwd=cwd,
            conversation_id=conversation_id,
            requested_game_id=requested_game_id,
        ),
        append_lifecycle_event=_append_lifecycle_event,
        error_payload=_error,
        schema_version=SCHEMA_VERSION,
        listener_factory=multiprocessing.connection.Listener,
    )

def _parse_daemon_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--daemon", action="store_true")
    parser.add_argument("--cwd", default="")
    parser.add_argument("--conversation-id", default="")
    parser.add_argument("--game-id", default="")
    return parser.parse_args(argv)

def main() -> int:
    daemon_args = _parse_daemon_args(sys.argv[1:])
    if daemon_args.daemon:
        cwd = Path(daemon_args.cwd).resolve()
        conversation_id = str(daemon_args.conversation_id).strip() or _session_key()
        requested_game_id = str(daemon_args.game_id).strip()
        try:
            return _daemon_main(cwd, conversation_id, requested_game_id)
        except Exception as exc:
            _append_lifecycle_event(
                cwd,
                conversation_id,
                "daemon_fatal_exception",
                daemon_pid=int(os.getpid()),
                requested_game_id=str(requested_game_id),
                error=str(exc),
            )
            traceback.print_exc(file=sys.stderr)
            return 1

    cwd = Path.cwd().resolve()
    args = _read_args()
    action = str(args.get("action", "")).strip() if isinstance(args, dict) else ""
    requested_game_id = str(args.get("game_id", "")).strip() if isinstance(args, dict) else ""

    if "_error" in args:
        _emit_json(
            _error(
                action=action or "status",
                requested_game_id=requested_game_id,
                message=str(args["_error"]),
                error_type="invalid_args",
            )
        )
        return 1

    if not action:
        _emit_json(
            _error(
                action="",
                requested_game_id=requested_game_id,
                message="missing required `action` (expected: status|exec|reset_level|shutdown)",
                error_type="missing_action",
            )
        )
        return 1

    if action == "exec" and not str(args.get("script", "") or "").strip():
        _emit_json(
            _error(
                action="exec",
                requested_game_id=requested_game_id,
                message="exec requires non-empty inline `script`",
                error_type="invalid_exec_args",
            )
        )
        return 1

    conversation_id = _session_key()
    request = {
        "action": action,
        "game_id": requested_game_id,
    }
    if action == "exec":
        request["script"] = str(args.get("script", ""))

    try:
        result, session_created = _send_request(cwd, conversation_id, request)
        if isinstance(result, dict):
            result.setdefault("schema_version", SCHEMA_VERSION)
            repl = result.get("repl") if isinstance(result.get("repl"), dict) else {}
            repl.setdefault("conversation_id", conversation_id)
            repl["session_created"] = bool(session_created or repl.get("session_created"))
            result["repl"] = repl
        if action == "exec":
            if not isinstance(result, dict):
                if result is not None:
                    sys.stdout.write(str(result))
                    if not str(result).endswith("\n"):
                        sys.stdout.write("\n")
                return 1
            script_stdout = str(result.get("script_stdout", "") or "")
            if script_stdout:
                sys.stdout.write(script_stdout)
                if not script_stdout.endswith("\n"):
                    sys.stdout.write("\n")
            if not bool(result.get("ok")):
                script_error = str(result.get("script_error", "") or "").strip()
                if script_error:
                    sys.stderr.write(script_error)
                    if not script_error.endswith("\n"):
                        sys.stderr.write("\n")
                else:
                    err = result.get("error")
                    if isinstance(err, dict):
                        msg = str(err.get("message", "") or "").strip()
                        details = str(err.get("details", "") or "").strip()
                        if msg:
                            sys.stderr.write(msg)
                            if not msg.endswith("\n"):
                                sys.stderr.write("\n")
                        if details:
                            sys.stderr.write(details)
                            if not details.endswith("\n"):
                                sys.stderr.write("\n")
                return 1
            return 0

        _emit_json(result)
        return 0 if bool(result.get("ok")) else 1
    except Exception as exc:
        _emit_json(
            _error(
                action=action,
                requested_game_id=requested_game_id,
                message=str(exc),
                error_type="internal_exception",
                details=traceback.format_exc(),
            )
        )
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
