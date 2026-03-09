from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def refresh_component_mismatch(cwd: Path) -> None:
    inspect_script = cwd / "inspect_components.py"
    if not inspect_script.exists():
        raise RuntimeError(f"missing component helper: {inspect_script}")
    proc = subprocess.run(
        [sys.executable, str(inspect_script), "--current-mismatch"],
        cwd=str(cwd),
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"inspect_components --current-mismatch failed: {detail}")
