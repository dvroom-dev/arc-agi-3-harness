#!/usr/bin/env python3
"""Stateful ARC Python REPL tool for super shell usage."""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
import time
import traceback
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
    _last_step_failure_details,
    _make_env,
    _make_id_candidates,
    _reset_env_with_retry,
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
from arc_repl_diagnostics import (
    daemon_unavailable_diagnostics,
    has_prior_session_artifacts,
)
from arc_repl_session_core import (
    BaseReplSession,
    _StopScript,
    _chunk_for_bbox,
    _coerce_grid,
    _grid_from_hex_rows,
    _same_game_lineage as _same_game_lineage_impl,
)
from arc_repl_paths import (
    conversation_id_from_env,
    daemon_log_path,
    ipc_paths,
    lifecycle_path,
    meta_path,
    pid_path,
    send_ipc_request,
    session_dir,
    session_key_from_env,
    socket_path,
    spawn_parent_identity_from_env,
)
SCHEMA_VERSION = "arc_repl.v1"
SOCKET_WAIT_TIMEOUT_S = 90.0
IDLE_KEEPALIVE_INTERCEPT_MARKER = "__ARC_INTERCEPT_IDLE_KEEPALIVE__"
LEVEL_COMPLETE_MODEL_MISMATCH_MARKER = "__ARC_INTERCEPT_LEVEL_COMPLETE_MODEL_MISMATCH__"
RESET_LEVEL_INTERCEPT_MARKER = "__ARC_INTERCEPT_RESET_LEVEL__"
COMPARE_RESULTS_BEGIN_MARKER = "__ARC_COMPARE_RESULTS_BEGIN__"
COMPARE_RESULTS_END_MARKER = "__ARC_COMPARE_RESULTS_END__"
IDLE_KEEPALIVE_FLAG_REL = "intercepts/idle_keepalive.flag"


def _idle_keepalive_flag_path(cwd: Path) -> Path:
    arc_state_dir = Path(str(os.getenv("ARC_STATE_DIR", "") or "")).expanduser()
    if not str(arc_state_dir).strip():
        arc_state_dir = _arc_dir(cwd)
    arc_state_dir.mkdir(parents=True, exist_ok=True)
    return arc_state_dir / IDLE_KEEPALIVE_FLAG_REL


def _consume_idle_keepalive_marker(cwd: Path) -> str | None:
    path = _idle_keepalive_flag_path(cwd)
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
    return payload or IDLE_KEEPALIVE_INTERCEPT_MARKER


def _result_has_real_game_action(action: str, result: object) -> bool:
    if not isinstance(result, dict):
        return False
    action_name = str(action or "").strip().lower()
    if action_name == "reset_level":
        return bool(result.get("ok")) and not bool(result.get("reset_noop", False))
    if action_name == "exec":
        try:
            return int(result.get("steps_executed", 0) or 0) > 0
        except Exception:
            return False
    return False


def _latest_sequence_id_for_level(level_dir: Path) -> str | None:
    seq_root = level_dir / "sequences"
    if not seq_root.exists():
        return None
    seq_files = sorted(seq_root.glob("seq_*.json"))
    if not seq_files:
        return None
    return seq_files[-1].stem


def _run_level_completion_compare(cwd: Path, result: object) -> str | None:
    if not isinstance(result, dict):
        return None
    if not bool(result.get("ok")):
        return None
    if str(result.get("state", "")).strip().upper() == "WIN":
        return None
    try:
        levels_gained = int(result.get("levels_gained_in_call", 0) or 0)
    except Exception:
        levels_gained = 0
    if levels_gained <= 0:
        return None
    try:
        completed_level = int(result.get("levels_completed", 0) or 0)
    except Exception:
        completed_level = 0
    if completed_level <= 0:
        return None

    model_py = cwd / "model.py"
    if not model_py.exists():
        return None
    level_dir = cwd / f"level_{completed_level}"
    if not level_dir.exists():
        return None
    sequence_id = _latest_sequence_id_for_level(level_dir)
    if not sequence_id:
        return None

    game_id = str(result.get("game_id", "") or os.getenv("ARC_ACTIVE_GAME_ID", "")).strip() or "game"
    cmd = [
        sys.executable,
        str(model_py),
        "compare_sequences",
        "--game-id",
        game_id,
        "--level",
        str(completed_level),
        "--sequence",
        sequence_id,
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        text=True,
        capture_output=True,
    )
    compare_stdout = str(proc.stdout or "")
    compare_stderr = str(proc.stderr or "")
    parsed_payload: dict | None = None
    try:
        parsed = json.loads(compare_stdout) if compare_stdout.strip() else None
        if isinstance(parsed, dict):
            parsed_payload = parsed
    except Exception:
        parsed_payload = None

    compare_ok = bool(parsed_payload.get("ok")) if isinstance(parsed_payload, dict) else False
    all_match = bool(parsed_payload.get("all_match")) if isinstance(parsed_payload, dict) else False
    mismatch = (proc.returncode != 0) or (not compare_ok) or (not all_match)
    if not mismatch:
        return None

    compare_file = level_dir / "compare_results.md"
    compare_file.parent.mkdir(parents=True, exist_ok=True)
    report_lines = [
        f"# Compare Results (Level {completed_level})",
        "",
        f"- sequence_id: {sequence_id}",
        f"- command: {' '.join(cmd)}",
        f"- return_code: {int(proc.returncode)}",
        f"- compare_ok: {str(compare_ok).lower()}",
        f"- all_match: {str(all_match).lower()}",
        "",
        "## stdout",
        "```text",
        compare_stdout.rstrip(),
        "```",
        "",
        "## stderr",
        "```text",
        compare_stderr.rstrip(),
        "```",
    ]
    compare_text = "\n".join(report_lines).rstrip() + "\n"
    compare_file.write_text(compare_text, encoding="utf-8")
    try:
        compare_rel = str(compare_file.relative_to(cwd))
    except Exception:
        compare_rel = str(compare_file)
    return (
        f"# {LEVEL_COMPLETE_MODEL_MISMATCH_MARKER} level={completed_level} "
        f"sequence={sequence_id} compare_file={compare_rel}\n"
        f"# {COMPARE_RESULTS_BEGIN_MARKER}\n"
        f"{compare_text}"
        f"# {COMPARE_RESULTS_END_MARKER}\n"
    )


def _reset_level_intercept_line(action: str, result: object) -> str | None:
    if str(action or "").strip().lower() != "reset_level":
        return None
    if not isinstance(result, dict):
        return f"{RESET_LEVEL_INTERCEPT_MARKER} action=reset_level ok=false"
    ok = str(bool(result.get("ok"))).lower()
    reset_noop = str(bool(result.get("reset_noop", False))).lower()
    current_level = result.get("current_level")
    levels_completed = result.get("levels_completed")
    return (
        f"{RESET_LEVEL_INTERCEPT_MARKER} action=reset_level "
        f"ok={ok} reset_noop={reset_noop} "
        f"current_level={current_level} levels_completed={levels_completed}"
    )


def _load_history(cwd: Path, game_id: str) -> dict:
    return _load_history_impl(cwd, game_id, _make_id_candidates)
_session_dir = lambda cwd, conversation_id: session_dir(_arc_dir(cwd), conversation_id)
_socket_path = lambda cwd, conversation_id: socket_path(_arc_dir(cwd), conversation_id)
_pid_path = lambda cwd, conversation_id: pid_path(_arc_dir(cwd), conversation_id)
_meta_path = lambda cwd, conversation_id: meta_path(_arc_dir(cwd), conversation_id)
_daemon_log_path = lambda cwd, conversation_id: daemon_log_path(_arc_dir(cwd), conversation_id)
_lifecycle_path = lambda cwd, conversation_id: lifecycle_path(_arc_dir(cwd), conversation_id)
_ipc_paths = lambda cwd, conversation_id: ipc_paths(_arc_dir(cwd), conversation_id)
_send_ipc_request = lambda cwd, conversation_id, request, timeout_s: send_ipc_request(arc_dir=_arc_dir(cwd), conversation_id=conversation_id, request=request, timeout_s=timeout_s)
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
def _conversation_id() -> str: return conversation_id_from_env()
def _session_key() -> str:
    return session_key_from_env()
def _same_game_lineage(existing_game_id: str, requested_game_id: str) -> bool:
    return _same_game_lineage_impl(existing_game_id, requested_game_id, _make_id_candidates)
class ReplSession(BaseReplSession):
    def __init__(
        self,
        *,
        cwd: Path,
        conversation_id: str,
        requested_game_id: str,
        enable_history_functions: bool = False,
    ) -> None:
        super().__init__(
            cwd=cwd,
            conversation_id=conversation_id,
            requested_game_id=requested_game_id,
            enable_history_functions=enable_history_functions,
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
        parent_pid, parent_start_ticks = spawn_parent_identity_from_env()
        daemon_cmd = [
            sys.executable,
            str(Path(__file__).resolve()),
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
    _pid_path(cwd, conversation_id).write_text(str(proc.pid) + "\n")
    _append_lifecycle_event(
        cwd,
        conversation_id,
        "spawned",
        daemon_pid=int(proc.pid),
        game_id=str(game_id),
        parent_pid=int(os.getpid()),
        lifecycle_parent_pid=(
            int(parent_pid) if parent_pid is not None else None
        ),
        lifecycle_parent_start_ticks=(
            int(parent_start_ticks) if parent_start_ticks is not None else None
        ),
        transport="file",
        socket_path=str(socket_path),
        log_file=str(log_path),
    )
def _wait_for_daemon(cwd: Path, conversation_id: str, timeout_s: float = SOCKET_WAIT_TIMEOUT_S) -> None:
    socket_path = _socket_path(cwd, conversation_id)
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if socket_path.exists():
            try:
                resp = _send_ipc_request(
                    cwd,
                    conversation_id,
                    {"action": "ping", "game_id": ""},
                    timeout_s=1.0,
                )
                if isinstance(resp, dict) and bool(resp.get("ok")):
                    return
            except Exception:
                pass
        time.sleep(0.05)
    _append_lifecycle_event(
        cwd,
        conversation_id,
        "wait_timeout",
        timeout_s=float(timeout_s),
        transport="file",
        socket_path=str(socket_path),
    )
    raise RuntimeError(f"arc_repl daemon did not start within {timeout_s}s")
def _send_request(cwd: Path, conversation_id: str, request: dict) -> tuple[dict, bool]:
    socket_path = _socket_path(cwd, conversation_id)
    session_created = False
    request_action = str(request.get("action", "") or "").strip().lower()
    paths_resolved = True
    try:
        session_dir = _session_dir(cwd, conversation_id)
        pid_file = _pid_path(cwd, conversation_id)
        meta_file = _meta_path(cwd, conversation_id)
        lifecycle_file = _lifecycle_path(cwd, conversation_id)
        log_file = _daemon_log_path(cwd, conversation_id)
    except Exception:
        paths_resolved = False
        session_dir = None
        pid_file = None
        meta_file = None
        lifecycle_file = None
        log_file = None
    prior_session_artifacts = bool(
        paths_resolved
        and has_prior_session_artifacts(
            session_dir=session_dir,
            pid_file=pid_file,
            meta_file=meta_file,
            lifecycle_file=lifecycle_file,
            log_file=log_file,
        )
    )
    def _try_send() -> dict:
        return _send_ipc_request(
            cwd,
            conversation_id,
            request,
            timeout_s=SOCKET_WAIT_TIMEOUT_S,
        )
    def _raise_daemon_unavailable(reason: str, exc: BaseException | None = None) -> None:
        if paths_resolved:
            diagnostics = daemon_unavailable_diagnostics(
                session_dir=session_dir,
                socket_path=socket_path,
                pid_file=pid_file,
                meta_file=meta_file,
                lifecycle_file=lifecycle_file,
                log_file=log_file,
            )
        else:
            diagnostics = (
                "arc_repl session diagnostics unavailable: failed resolving session paths. "
                "Is ARC_STATE_DIR set?"
            )
        message = (
            f"arc_repl daemon unavailable ({reason}); automatic replay/recovery is disabled.\n"
            f"{diagnostics}"
        )
        if exc is None:
            raise RuntimeError(message)
        raise RuntimeError(message) from exc
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
        try:
            _wait_for_daemon(cwd, conversation_id)
        except Exception as exc:
            _raise_daemon_unavailable(f"spawn_failed:{reason}", exc)
        session_created = True

    if not socket_path.exists():
        if prior_session_artifacts:
            _raise_daemon_unavailable("socket_missing_after_prior_session")
        if request_action == "shutdown":
            _raise_daemon_unavailable("socket_missing_before_shutdown")
        # Initial session bootstrap should work for all stateful actions, not
        # only status. This is required for flows that intentionally start a new
        # conversation/session key with reset_level (e.g. scored replay).
        _spawn_for_request(f"socket_missing_initial_{request_action}_bootstrap")

    try:
        return _try_send(), session_created
    except (FileNotFoundError, RuntimeError, OSError) as exc:
        if session_created:
            try:
                return _try_send(), session_created
            except Exception as retry_exc:
                _raise_daemon_unavailable("post_spawn_connect_failure", retry_exc)
        _raise_daemon_unavailable("connect_failure_no_respawn", exc)

def _daemon_main(
    cwd: Path,
    conversation_id: str,
    requested_game_id: str,
    *,
    parent_pid: int | None = None,
    parent_start_ticks: int | None = None,
) -> int:
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
        parent_pid=parent_pid,
        parent_start_ticks=parent_start_ticks,
    )

def _parse_daemon_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--daemon", action="store_true")
    parser.add_argument("--cwd", default="")
    parser.add_argument("--conversation-id", default="")
    parser.add_argument("--game-id", default="")
    parser.add_argument("--parent-pid", type=int, default=None)
    parser.add_argument("--parent-start-ticks", type=int, default=None)
    return parser.parse_args(argv)

def main() -> int:
    daemon_args = _parse_daemon_args(sys.argv[1:])
    if daemon_args.daemon:
        cwd = Path(daemon_args.cwd).resolve()
        conversation_id = str(daemon_args.conversation_id).strip() or _session_key()
        requested_game_id = str(daemon_args.game_id).strip()
        try:
            return _daemon_main(
                cwd,
                conversation_id,
                requested_game_id,
                parent_pid=daemon_args.parent_pid,
                parent_start_ticks=daemon_args.parent_start_ticks,
            )
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
    if bool(args.get("enable_history_functions", False)):
        request["enable_history_functions"] = True
    if action == "exec":
        request["script"] = str(args.get("script", ""))
        script_path = str(args.get("script_path", "") or "").strip()
        if script_path:
            request["script_path"] = script_path
        source = str(args.get("source", "") or "").strip()
        if source:
            request["source"] = source

    try:
        result, session_created = _send_request(cwd, conversation_id, request)
        if isinstance(result, dict):
            result.setdefault("schema_version", SCHEMA_VERSION)
            repl = result.get("repl") if isinstance(result.get("repl"), dict) else {}
            repl.setdefault("conversation_id", conversation_id)
            repl["session_created"] = bool(session_created or repl.get("session_created"))
            result["repl"] = repl
        real_game_action = _result_has_real_game_action(action, result)
        idle_intercept_line = None
        if not real_game_action:
            idle_marker = _consume_idle_keepalive_marker(cwd)
            if idle_marker:
                idle_intercept_line = f"{idle_marker} action={action}".strip()
        reset_intercept_line = _reset_level_intercept_line(action, result)
        level_compare_block = (
            _run_level_completion_compare(cwd, result)
            if str(action).strip().lower() == "exec"
            else None
        )
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
            if level_compare_block:
                sys.stdout.write(level_compare_block)
                if not level_compare_block.endswith("\n"):
                    sys.stdout.write("\n")
            if idle_intercept_line:
                sys.stdout.write(f"# {idle_intercept_line}\n")
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

        if isinstance(result, dict):
            intercept_lines: list[str] = []
            if reset_intercept_line:
                intercept_lines.append(reset_intercept_line)
            if idle_intercept_line:
                intercept_lines.append(idle_intercept_line)
            if intercept_lines:
                result["intercept_hint"] = " | ".join(intercept_lines)
                result["intercept_hints"] = intercept_lines
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
