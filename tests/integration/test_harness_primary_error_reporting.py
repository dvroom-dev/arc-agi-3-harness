from __future__ import annotations

import json
import sys
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import harness
import pytest


def test_harness_finalize_does_not_mask_primary_super_failure(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "proj"
    (root / "tools").mkdir(parents=True)
    (root / "prompts").mkdir(parents=True)
    (root / "runs").mkdir(parents=True)
    (root / "arc_model_runtime").mkdir(parents=True)
    (root / "super.yaml").write_text("runtime_defaults: {}\n")
    (root / "arc_model_runtime" / "__init__.py").write_text("# runtime\n")
    for f in ("arc_repl.py", "arc_repl_cli.py", "arc_repl_daemon.py", "arc_repl_exec_output.py", "arc_level.py"):
        (root / "tools" / f).write_text("#!/usr/bin/env python3\n")
    (root / "prompts" / "new_game_auto_explore.py").write_text("print('x')\n")

    args = Namespace(
        game_id="ls20",
        max_turns=0,
        operation_mode="NORMAL",
        session_name="t-primary-super-failure",
        verbose=False,
        open_scorecard=False,
        scorecard_id=None,
        provider="mock",
        no_supervisor=True,
        explore_inputs=False,
        max_game_over_resets=1,
        arc_backend="api",
        arc_base_url="http://example.test",
    )

    def fake_subprocess_run(cmd, **kwargs):
        text_input = kwargs.get("input")
        if isinstance(text_input, str):
            req = json.loads(text_input)
            action = req.get("action")
            if action == "status":
                payload = {
                    "ok": True,
                    "game_id": "ls20-cb3b57cc",
                    "state": "NOT_FINISHED",
                    "current_level": 1,
                    "levels_completed": 0,
                    "win_levels": 7,
                    "available_actions": [0, 1, 2, 3, 4],
                }
            elif action == "shutdown":
                payload = {"ok": True, "action": "shutdown"}
            else:
                payload = {"ok": True}
            return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def fake_run_super(_args, **_kwargs):
        raise harness.HarnessSubprocessError(
            "super exited with code 1: primary failure",
            process_name="super",
            return_code=1,
            detail="primary failure",
            stderr_lines=["primary failure"],
        )

    monkeypatch.setattr(harness, "PROJECT_ROOT", root)
    monkeypatch.setattr(harness, "CTXS", root / ".ctxs")
    monkeypatch.setattr(harness, "PROJECT_VENV_PYTHON", Path(sys.executable))
    monkeypatch.setattr(harness, "parse_args", lambda: args)
    monkeypatch.setattr(harness, "cleanup_orphan_repl_daemons", lambda *a, **k: {"killed": 0, "stale_files_removed": 0, "skipped_active": 0})
    monkeypatch.setattr(harness, "cleanup_orphan_run_processes", lambda *a, **k: {"killed": 0, "skipped_active": 0, "scanned": 0})
    monkeypatch.setattr(harness, "run_super", fake_run_super)
    monkeypatch.setattr(harness.subprocess, "run", fake_subprocess_run)

    with pytest.raises(harness.HarnessSubprocessError):
        harness.main()

    last_error_path = root / "runs" / "t-primary-super-failure" / "telemetry" / "last_error.json"
    payload = json.loads(last_error_path.read_text(encoding="utf-8"))
    assert payload["category"] == "super"
    assert payload["name"] == "new"
