from __future__ import annotations

import fcntl
import json
import os
import shutil
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

_TRANSIENT_COPY_PREFIXES = (
    ".level_",
)
_TRANSIENT_COPY_FRAGMENTS = (
    ".flux-sync-",
    ".flux-prev-",
    ".tmp-",
)
_TRANSIENT_COPY_NAMES = {
    ".flux-sync.lock",
    ".workspace-tree.lock",
    ".level_current.tmp",
}


def _tmp_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + f".tmp-{os.getpid()}-{time.time_ns()}")


def write_text_atomic(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = _tmp_path(path)
    tmp.write_text(text, encoding=encoding)
    tmp.replace(path)


def write_json_atomic(path: Path, payload: Any, *, encoding: str = "utf-8") -> None:
    write_text_atomic(path, json.dumps(payload, indent=2) + "\n", encoding=encoding)


def write_jsonl_atomic(path: Path, rows: list[Any], *, encoding: str = "utf-8") -> None:
    text = "".join(json.dumps(row, ensure_ascii=True) + "\n" for row in rows)
    write_text_atomic(path, text, encoding=encoding)


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
        return
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


def _should_ignore_transient_name(name: str) -> bool:
    if name in _TRANSIENT_COPY_NAMES:
        return True
    if any(fragment in name for fragment in _TRANSIENT_COPY_FRAGMENTS):
        return True
    return any(name.startswith(prefix) and ".flux-" in name for prefix in _TRANSIENT_COPY_PREFIXES)


def _ignore_transient_entries(_src: str, names: list[str]) -> list[str]:
    return [name for name in names if _should_ignore_transient_name(name)]


def _is_retryable_copy_error(error: BaseException) -> bool:
    if isinstance(error, FileNotFoundError):
        return True
    if isinstance(error, shutil.Error):
        return all("No such file or directory" in str(entry[2]) for entry in error.args[0])
    return False


def copytree_stable(src: Path, dst: Path, *, attempts: int = 8, delay_s: float = 0.05) -> None:
    last_error: BaseException | None = None
    for _ in range(max(1, int(attempts))):
        _remove_path(dst)
        try:
            shutil.copytree(src, dst, ignore=_ignore_transient_entries)
            return
        except BaseException as error:
            if not _is_retryable_copy_error(error):
                raise
            last_error = error
            time.sleep(delay_s)
    if last_error is not None:
        raise last_error


@contextmanager
def workspace_tree_lock(root: Path):
    lock_path = root / ".workspace-tree.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
