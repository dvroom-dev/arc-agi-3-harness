from __future__ import annotations

import json


def emit_exec_result_block(result: dict) -> str:
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
