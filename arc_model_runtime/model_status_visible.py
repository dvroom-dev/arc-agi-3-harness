from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .visible_artifacts import visible_levels_completed_for_level


def rewrite_model_status_payload_for_visible_level(
    *,
    path: Path,
    frontier_level: int,
    visible_level: int,
) -> None:
    try:
        payload = json.loads(path.read_text()) if path.exists() else None
    except Exception:
        return
    if not isinstance(payload, dict):
        return
    visible_level = int(visible_level)
    state = dict(payload.get("state")) if isinstance(payload.get("state"), dict) else {}
    state["current_level"] = visible_level
    state["levels_completed"] = visible_levels_completed_for_level(visible_level)
    if isinstance(state.get("available_model_levels"), list):
        filtered: list[int] = []
        for value in state["available_model_levels"]:
            try:
                level = int(value)
            except Exception:
                continue
            if level <= visible_level:
                filtered.append(level)
        state["available_model_levels"] = filtered
    elif visible_level < int(frontier_level):
        state["available_model_levels"] = list(range(1, visible_level + 1))
    payload["state"] = state
    payload["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n")
    tmp.replace(path)
