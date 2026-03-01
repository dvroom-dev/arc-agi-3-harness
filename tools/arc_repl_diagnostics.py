from __future__ import annotations

import os
import re
from pathlib import Path


def is_socket_permission_error(exc: BaseException) -> bool:
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if isinstance(cur, PermissionError):
            return True
        if isinstance(cur, OSError) and getattr(cur, "errno", None) in {
            1,   # EPERM
            13,  # EACCES
        }:
            return True
        msg = str(cur).lower()
        if "operation not permitted" in msg or "permission denied" in msg:
            return True
        cur = cur.__cause__ or cur.__context__
    return False


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text()
    except Exception:
        return ""


def _tail_lines(path: Path, *, n: int = 40) -> str:
    text = _safe_read_text(path)
    if not text:
        return ""
    return "\n".join(text.splitlines()[-max(1, int(n)):])


def daemon_unavailable_diagnostics(
    *,
    session_dir: Path,
    socket_path: Path,
    pid_file: Path,
    meta_file: Path,
    lifecycle_file: Path,
    log_file: Path,
) -> str:
    pid_raw = _safe_read_text(pid_file).strip() if pid_file.exists() else ""
    pid = int(pid_raw) if re.fullmatch(r"\d+", pid_raw) else None
    pid_alive = False
    if pid is not None:
        try:
            os.kill(pid, 0)
            pid_alive = True
        except Exception:
            pid_alive = False

    lifecycle_tail = _tail_lines(lifecycle_file, n=20)
    log_tail = _tail_lines(log_file, n=80)
    if len(log_tail) > 8000:
        log_tail = log_tail[-8000:]

    parts = [
        "arc_repl session diagnostics:",
        f"session_dir={session_dir}",
        f"socket_exists={socket_path.exists()} socket={socket_path}",
        f"pid={pid if pid is not None else 'missing'} pid_alive={pid_alive}",
        (
            "meta_exists="
            f"{meta_file.exists()} lifecycle_exists={lifecycle_file.exists()} "
            f"log_exists={log_file.exists()}"
        ),
    ]
    if lifecycle_tail:
        parts.append("lifecycle_tail:")
        parts.append(lifecycle_tail)
    if log_tail:
        parts.append("daemon_log_tail:")
        parts.append(log_tail)
    return "\n".join(parts)


def has_prior_session_artifacts(
    *,
    session_dir: Path,
    pid_file: Path,
    meta_file: Path,
    lifecycle_file: Path,
    log_file: Path,
) -> bool:
    if not session_dir.exists():
        return False
    markers = (pid_file, meta_file, lifecycle_file, log_file)
    return any(path.exists() for path in markers)
