#!/usr/bin/env python3
"""Stateful ARC Python REPL tool for super shell usage.

JSON stdin contract:
- action=status
- action=exec (inline script only via `script`)
- action=reset_level
- action=shutdown (stop conversation REPL daemon)

The REPL is conversation-scoped (ARC_CONVERSATION_ID) and persists Python globals
across calls in a daemon process. New conversations start a fresh REPL namespace,
seeded with an `env` already positioned at the current game state via replay history.
"""

from __future__ import annotations

import argparse
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

from arc_action import (
    _action_from_event_name,
    _arc_dir,
    _append_level_completion,
    _call_quiet,
    _change_bbox,
    _completion_action_windows_by_level,
    _default_game_id,
    _ensure_agent_lib_file,
    _ensure_level_completions_file,
    _error_payload,
    _get_pixels,
    _iter_cell_changes,
    _load_history,
    _make_env,
    _make_id_candidates,
    _read_max_recorded_completion_level,
    _replay_history,
    _save_history,
    _write_turn_trace,
    build_aggregate_diff_record,
    build_step_diff_records,
    format_diff_minimal,
    frame_action_metadata,
    write_game_state,
    write_machine_state,
)

try:
    from arc_repl_session_core import (
        BaseReplSession,
        _StopScript,
        _chunk_for_bbox,
        _coerce_grid,
        _grid_from_hex_rows,
        _same_game_lineage as _same_game_lineage_impl,
    )
except Exception:
    from tools.arc_repl_session_core import (
        BaseReplSession,
        _StopScript,
        _chunk_for_bbox,
        _coerce_grid,
        _grid_from_hex_rows,
        _same_game_lineage as _same_game_lineage_impl,
    )

SCHEMA_VERSION = "arc_repl.v1"
SOCKET_WAIT_TIMEOUT_S = 90.0


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


def _session_dir(cwd: Path, conversation_id: str) -> Path:
    return _arc_dir(cwd) / "repl-sessions" / conversation_id


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


def _wait_for_daemon(cwd: Path, conversation_id: str, timeout_s: float = SOCKET_WAIT_TIMEOUT_S) -> None:
    socket_path = _socket_path(cwd, conversation_id)
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if socket_path.exists():
            try:
                conn = multiprocessing.connection.Client(str(socket_path), family="AF_UNIX")
            except Exception:
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
    raise RuntimeError(f"arc_repl daemon did not start within {timeout_s}s")


def _send_request(cwd: Path, conversation_id: str, request: dict) -> tuple[dict, bool]:
    """Send request to conversation daemon, starting it if needed.

    Returns (response, session_created).
    """
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

    try:
        return _try_send(), session_created
    except Exception:
        requested_game_id = str(request.get("game_id", "") or "").strip() or _default_game_id(cwd)
        if not requested_game_id:
            raise RuntimeError(
                "game_id is required (or initialize state first with action=status and game_id)"
            )
        _spawn_daemon(cwd, conversation_id, requested_game_id)
        _wait_for_daemon(cwd, conversation_id)
        session_created = True
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

    session = ReplSession(cwd=cwd, conversation_id=conversation_id, requested_game_id=requested_game_id)
    _meta_path(cwd, conversation_id).write_text(
        json.dumps(
            {
                "conversation_id": conversation_id,
                "game_id": session.game_id,
                "socket": str(socket_path),
                "pid": os.getpid(),
                "started_at_unix": time.time(),
            },
            indent=2,
        )
        + "\n"
    )

    listener = multiprocessing.connection.Listener(str(socket_path), family="AF_UNIX")
    should_stop = False
    try:
        while not should_stop:
            conn = listener.accept()
            try:
                request = conn.recv()
                if not isinstance(request, dict):
                    conn.send({"ok": False, "error": "request must be an object"})
                    continue
                action = str(request.get("action", "")).strip()
                requested_game_id = str(request.get("game_id", "") or "").strip()

                if action == "ping":
                    conn.send({"ok": True, "action": "ping"})
                    continue
                if action == "status":
                    result = session.do_status(requested_game_id, session_created=False)
                elif action == "reset_level":
                    result = session.do_reset_level(requested_game_id, session_created=False)
                elif action == "exec":
                    script = str(request.get("script", "") or "")
                    result = session.do_exec(requested_game_id, script, session_created=False)
                elif action == "shutdown":
                    result = {
                        "schema_version": SCHEMA_VERSION,
                        "ok": True,
                        "action": "shutdown",
                        "conversation_id": conversation_id,
                        "game_id": session.game_id,
                    }
                    should_stop = True
                else:
                    result = _error(
                        action=action,
                        requested_game_id=requested_game_id,
                        message="unknown action. expected: status|exec|reset_level|shutdown",
                        error_type="unknown_action",
                    )
                conn.send(result)
            except Exception as exc:
                conn.send(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "ok": False,
                        "error": {
                            "type": "daemon_exception",
                            "message": str(exc),
                            "details": traceback.format_exc(),
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
            listener.close()
        except Exception:
            pass
        try:
            if socket_path.exists():
                socket_path.unlink()
        except Exception:
            pass
    return 0


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
        conversation_id = str(daemon_args.conversation_id).strip() or _conversation_id()
        requested_game_id = str(daemon_args.game_id).strip()
        try:
            return _daemon_main(cwd, conversation_id, requested_game_id)
        except Exception:
            traceback.print_exc()
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

    conversation_id = _conversation_id()
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
