from __future__ import annotations

import subprocess
import sys
from pathlib import Path
import json


def _write_component_mismatch_error(cwd: Path, detail: str) -> None:
    payload = {
        "status": "error",
        "message": detail.strip() or "component mismatch refresh failed",
    }
    for path in (cwd / "component_mismatch.json", cwd / "component_mismatch.md"):
        path.parent.mkdir(parents=True, exist_ok=True)
    (cwd / "component_mismatch.json").write_text(json.dumps(payload, indent=2) + "\n")
    (cwd / "component_mismatch.md").write_text(
        "# Component Mismatch\n\n"
        "- status: error\n"
        f"- message: {payload['message']}\n"
    )


def refresh_component_mismatch(cwd: Path) -> str | None:
    inspect_script = cwd / "inspect_components.py"
    if not inspect_script.exists():
        detail = f"missing component helper: {inspect_script}"
        _write_component_mismatch_error(cwd, detail)
        return detail
    proc = subprocess.run(
        [sys.executable, str(inspect_script), "--current-mismatch"],
        cwd=str(cwd),
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        _write_component_mismatch_error(cwd, detail)
        return detail
    return None
