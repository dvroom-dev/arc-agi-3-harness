from __future__ import annotations

import sys
from argparse import Namespace
from pathlib import Path

import harness
import pytest


def test_harness_rejects_legacy_wrapup_contract_in_super_config(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "proj"
    (root / "tools").mkdir(parents=True)
    (root / "prompts").mkdir(parents=True)
    (root / "runs").mkdir(parents=True)
    (root / "arc_model_runtime").mkdir(parents=True)
    (root / "super.yaml").write_text(
        "runtime_defaults: {}\n"
        "supervisor:\n"
        "  instructions:\n"
        "    operation: append\n"
        "    values:\n"
        "      - \"use --wrapup-certified and --wrapup-level\"\n"
    )
    (root / "arc_model_runtime" / "__init__.py").write_text("# runtime\n")
    for name in ("arc_repl.py", "arc_repl_cli.py", "arc_repl_daemon.py", "arc_repl_exec_output.py", "arc_level.py"):
        (root / "tools" / name).write_text("#!/usr/bin/env python3\n")
    (root / "prompts" / "new_game_auto_explore.py").write_text("print('x')\n")

    args = Namespace(
        game_id="ls20",
        max_turns=0,
        operation_mode="NORMAL",
        session_name="t-legacy-wrapup",
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

    monkeypatch.setattr(harness, "PROJECT_ROOT", root)
    monkeypatch.setattr(harness, "CTXS", root / ".ctxs")
    monkeypatch.setattr(harness, "PROJECT_VENV_PYTHON", Path(sys.executable))
    monkeypatch.setattr(harness, "parse_args", lambda: args)
    monkeypatch.setattr(
        harness,
        "cleanup_orphan_repl_daemons",
        lambda *a, **k: {"killed": 0, "stale_files_removed": 0, "skipped_active": 0},
    )

    with pytest.raises(RuntimeError, match="legacy solved-level wrap-up contract markers"):
        harness.main()
