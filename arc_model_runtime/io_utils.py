from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Any


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
            shutil.copytree(src, dst)
            return
        except BaseException as error:
            if not _is_retryable_copy_error(error):
                raise
            last_error = error
            time.sleep(delay_s)
    if last_error is not None:
        raise last_error
