from __future__ import annotations

import json
import os
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
