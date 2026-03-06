from __future__ import annotations

import re
from pathlib import Path


def load_conversation_id_impl(doc_path: Path) -> str | None:
    if not doc_path.exists():
        return None
    try:
        text = doc_path.read_text()
    except Exception:
        return None
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:80]:
        if line.strip() == "---":
            break
        match = re.match(r"^\s*conversation_id\s*:\s*(.+?)\s*$", line)
        if match:
            return match.group(1).strip()
    return None
