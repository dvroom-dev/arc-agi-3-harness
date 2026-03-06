from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _run_arc_level(*args: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "tools/arc_level.py", *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def test_arc_level_defaults_and_fields(tmp_path: Path) -> None:
    state_dir = tmp_path / "arc"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "state.json").write_text(
        json.dumps({"current_level": 3, "levels_completed": 2, "state": "NOT_FINISHED"}),
        encoding="utf-8",
    )
    env = dict(os.environ)
    env["ARC_STATE_DIR"] = str(state_dir)

    proc_default = _run_arc_level(env=env)
    assert proc_default.returncode == 0
    assert proc_default.stdout.strip() == "3"

    proc_levels = _run_arc_level("--field", "levels_completed", env=env)
    assert proc_levels.returncode == 0
    assert proc_levels.stdout.strip() == "2"

    proc_state = _run_arc_level("--field", "state", env=env)
    assert proc_state.returncode == 0
    assert proc_state.stdout.strip() == "NOT_FINISHED"

    proc_json = _run_arc_level("--json", env=env)
    assert proc_json.returncode == 0
    payload = json.loads(proc_json.stdout)
    assert payload["current_level"] == 3
    assert payload["levels_completed"] == 2
    assert payload["state"] == "NOT_FINISHED"


def test_arc_level_errors_without_state_dir(tmp_path: Path) -> None:
    env = dict(os.environ)
    env.pop("ARC_STATE_DIR", None)
    proc = _run_arc_level(env=env)
    assert proc.returncode == 2
    assert "ARC_STATE_DIR is not set" in proc.stderr
