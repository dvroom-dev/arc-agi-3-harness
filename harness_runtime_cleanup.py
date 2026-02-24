from __future__ import annotations

import json
import os
import signal
import time
from pathlib import Path


def _session_pid_file(rt, session_key: str) -> Path:
    return rt.arc_state_dir / "repl-sessions" / session_key / "daemon.pid"


def _shutdown_repl_session(rt, session_key: str) -> None:
    skey = str(session_key or "").strip()
    if not skey:
        return
    pid_file = _session_pid_file(rt, skey)
    if not pid_file.exists():
        return
    prev_conversation_id = rt.active_conversation_id
    prev_repl_session_key = getattr(rt, "active_repl_session_key", None)
    try:
        rt.active_conversation_id = skey
        if prev_repl_session_key is not None:
            rt.active_repl_session_key = skey
        result, stdout, rc = rt.run_arc_repl({"action": "shutdown", "game_id": rt.args.game_id})
        if rc == 0:
            rt.log(f"[harness] arc_repl shutdown sent for session={skey}")
        else:
            detail = stdout.strip() if stdout.strip() else "no stdout"
            rt.log(
                "[harness] arc_repl shutdown failed for "
                f"session={skey}: rc={rc} detail={detail}"
            )
        if result and isinstance(result, dict) and not bool(result.get("ok", False)):
            err = result.get("error")
            rt.log(f"[harness] arc_repl shutdown response error session={skey}: {err}")
    except Exception as exc:
        rt.log(f"[harness] arc_repl shutdown exception session={skey}: {exc}")
    finally:
        rt.active_conversation_id = prev_conversation_id
        if prev_repl_session_key is not None:
            rt.active_repl_session_key = prev_repl_session_key


def _terminate_pid_local(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return True
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return True
    deadline = time.time() + 1.5
    while time.time() < deadline:
        try:
            os.kill(pid, 0)
        except OSError:
            return True
        time.sleep(0.05)
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        return True
    time.sleep(0.05)
    try:
        os.kill(pid, 0)
        return False
    except OSError:
        return True


def cleanup_repl_daemons_impl(rt) -> None:
    cids: set[str] = set()
    cids.update(k for k in rt.conversation_aliases.keys() if k)
    cids.update(v for v in rt.conversation_aliases.values() if v)
    if rt.active_actual_conversation_id:
        cids.add(rt.active_actual_conversation_id)
    if rt.active_conversation_id:
        cids.add(rt.active_conversation_id)
    repl_session_key = str(getattr(rt, "active_repl_session_key", "") or "").strip()
    if repl_session_key:
        cids.add(repl_session_key)

    sessions_root = rt.arc_state_dir / "repl-sessions"
    if sessions_root.exists():
        for path in sessions_root.iterdir():
            if path.is_dir():
                cids.add(path.name)

    for cid in sorted(cids):
        _shutdown_repl_session(rt, cid)

    if not sessions_root.exists():
        return
    for pid_file in sessions_root.glob("*/daemon.pid"):
        try:
            raw = pid_file.read_text().strip()
            pid = int(raw)
        except Exception:
            continue
        if _terminate_pid_local(pid):
            rt.log(f"[harness] cleaned repl daemon pid={pid} ({pid_file.parent.name})")
        else:
            rt.log(f"[harness] WARNING: failed to terminate repl daemon pid={pid}")


def close_scorecard_if_needed_impl(rt) -> None:
    if not (rt.scorecard_created_here and rt.active_scorecard_id):
        return
    try:
        if rt.scorecard_client is None:
            rt.scorecard_client = rt._build_scorecard_client()
        final_scorecard = rt.scorecard_client.close_scorecard(rt.active_scorecard_id)
        if final_scorecard is not None:
            score = getattr(final_scorecard, "score", None)
            rt.log(
                "[harness] scorecard closed: "
                f"id={rt.active_scorecard_id} score={score}"
            )
            rt.scorecard_meta_path.write_text(
                json.dumps(
                    {
                        "scorecard_id": rt.active_scorecard_id,
                        "api_url": rt.scorecard_api_url,
                        "web_url": rt.scorecard_web_url,
                        "created_here": True,
                        "closed": True,
                        "final_score": score,
                        "operation_mode": rt.operation_mode_name,
                        "arc_base_url": rt.arc_base_url,
                    },
                    indent=2,
                )
                + "\n"
            )
        else:
            rt.log(
                "[harness] WARNING: close_scorecard returned no data "
                f"for id={rt.active_scorecard_id}"
            )
    except Exception as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        if status_code == 404:
            rt.log(
                "[harness] scorecard already closed before explicit close "
                f"(id={rt.active_scorecard_id}, status=404)"
            )
            try:
                rt.scorecard_meta_path.write_text(
                    json.dumps(
                        {
                            "scorecard_id": rt.active_scorecard_id,
                            "api_url": rt.scorecard_api_url,
                            "web_url": rt.scorecard_web_url,
                            "created_here": True,
                            "closed": True,
                            "close_status": "already_closed",
                            "operation_mode": rt.operation_mode_name,
                            "arc_base_url": rt.arc_base_url,
                        },
                        indent=2,
                    )
                    + "\n"
                )
            except Exception:
                pass
        else:
            rt.log(
                "[harness] WARNING: failed to close scorecard "
                f"id={rt.active_scorecard_id}: {exc}"
            )
