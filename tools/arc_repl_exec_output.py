from __future__ import annotations

import json
from pathlib import Path

from arc_model_runtime.utils import effective_analysis_level, visible_levels_completed_for_level


def sanitize_result_for_agent_visibility(*, cwd: Path, result: dict) -> dict:
    frontier_level = result.get("current_level")
    try:
        frontier_level_int = int(frontier_level)
    except Exception:
        frontier_level_int = None
    visible_level = effective_analysis_level(cwd, frontier_level=frontier_level_int)
    if visible_level is None:
        return dict(result)
    if frontier_level_int is None or int(visible_level) >= frontier_level_int:
        return dict(result)

    sanitized = dict(result)
    sanitized["current_level"] = int(visible_level)
    sanitized["levels_completed"] = visible_levels_completed_for_level(int(visible_level))
    sanitized["analysis_level_pinned"] = True
    artifacts = result.get("artifacts")
    if isinstance(artifacts, dict):
        safe_artifacts: dict[str, object] = {}
        for key in ("level", "tool_turn", "changed_pixels"):
            if key in artifacts:
                safe_artifacts[key] = artifacts.get(key)
        safe_artifacts["analysis_level_boundary_redacted"] = True
        sanitized["artifacts"] = safe_artifacts
    return sanitized


def emit_exec_result_block(*, cwd: Path, result: dict) -> str:
    result = sanitize_result_for_agent_visibility(cwd=cwd, result=result)
    payload = {
        "ok": bool(result.get("ok")),
        "action": "exec",
        "state": result.get("state"),
        "current_level": result.get("current_level"),
        "levels_completed": result.get("levels_completed"),
        "steps_executed": result.get("steps_executed"),
        "transitions": result.get("transitions"),
        "trace_file": result.get("trace_file"),
        "artifacts": result.get("artifacts"),
    }
    return "\n".join(
        [
            "<arc_repl_result>",
            json.dumps(payload, indent=2),
            "</arc_repl_result>",
        ]
    )
