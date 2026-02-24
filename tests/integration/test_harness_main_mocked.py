from __future__ import annotations

import json
import sys
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import harness


def _fake_super_write_session(cmd: list[str]) -> None:
    if "--output" not in cmd:
        return
    out = Path(cmd[cmd.index("--output") + 1])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        "---\nconversation_id: conv-1\n---\n```chat role=assistant\nok\n```\n"
    )


def test_harness_main_smoke_no_llm_calls(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "proj"
    (root / "tools").mkdir(parents=True)
    (root / "prompts").mkdir(parents=True)
    (root / "runs").mkdir(parents=True)
    (root / "super.yaml").write_text("runtime_defaults: {}\n")
    for f in ("arc_repl.py", "arc_repl_cli.py", "arc_repl_daemon.py"):
        (root / "tools" / f).write_text("#!/usr/bin/env python3\n")
    (root / "prompts" / "new_game_auto_explore.py").write_text("print('x')\n")

    args = Namespace(
        game_id="ls20",
        max_turns=0,
        operation_mode="NORMAL",
        session_name="t-run",
        verbose=False,
        open_scorecard=False,
        scorecard_id=None,
        provider="mock",
        no_supervisor=True,
        no_explore=True,
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

    def fake_run_super(args, **kwargs):
        _fake_super_write_session(["super", *args])
        return ""

    monkeypatch.setattr(harness, "PROJECT_ROOT", root)
    monkeypatch.setattr(harness, "CTXS", root / ".ctxs")
    monkeypatch.setattr(harness, "PROJECT_VENV_PYTHON", Path(sys.executable))
    monkeypatch.setattr(harness, "parse_args", lambda: args)
    monkeypatch.setattr(harness, "cleanup_orphan_repl_daemons", lambda *a, **k: {"killed": 0, "stale_files_removed": 0, "skipped_active": 0})
    monkeypatch.setattr(harness, "run_super", fake_run_super)
    monkeypatch.setattr(harness.subprocess, "run", fake_subprocess_run)

    harness.main()

    assert (root / "runs" / "t-run" / "agent").exists()
    assert (root / ".ctxs" / "t-run" / "session.md").exists()


def test_harness_sets_only_reset_levels_in_child_and_super_envs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "proj"
    (root / "tools").mkdir(parents=True)
    (root / "prompts").mkdir(parents=True)
    (root / "runs").mkdir(parents=True)
    (root / "super.yaml").write_text("runtime_defaults: {}\n")
    for f in ("arc_repl.py", "arc_repl_cli.py", "arc_repl_daemon.py"):
        (root / "tools" / f).write_text("#!/usr/bin/env python3\n")
    (root / "prompts" / "new_game_auto_explore.py").write_text("print('x')\n")

    args = Namespace(
        game_id="ls20",
        game_ids=None,
        max_turns=0,
        operation_mode="NORMAL",
        session_name="t-env",
        verbose=False,
        open_scorecard=False,
        scorecard_id=None,
        provider="mock",
        no_supervisor=True,
        no_explore=True,
        max_game_over_resets=1,
        arc_backend="api",
        arc_base_url="http://example.test",
    )

    observed_child_env_values: list[str | None] = []
    observed_super_env_values: list[str | None] = []

    def fake_subprocess_run(cmd, **kwargs):
        text_input = kwargs.get("input")
        env = kwargs.get("env", {})
        observed_child_env_values.append(env.get("ONLY_RESET_LEVELS"))
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

    def fake_run_super(args, **kwargs):
        observed_super_env_values.append((kwargs.get("env") or {}).get("ONLY_RESET_LEVELS"))
        _fake_super_write_session(["super", *args])
        return ""

    monkeypatch.setattr(harness, "PROJECT_ROOT", root)
    monkeypatch.setattr(harness, "CTXS", root / ".ctxs")
    monkeypatch.setattr(harness, "PROJECT_VENV_PYTHON", Path(sys.executable))
    monkeypatch.setattr(harness, "parse_args", lambda: args)
    monkeypatch.setattr(harness, "cleanup_orphan_repl_daemons", lambda *a, **k: {"killed": 0, "stale_files_removed": 0, "skipped_active": 0})
    monkeypatch.setattr(harness, "run_super", fake_run_super)
    monkeypatch.setattr(harness.subprocess, "run", fake_subprocess_run)

    harness.main()

    assert observed_child_env_values
    assert all(value == "true" for value in observed_child_env_values)
    assert observed_super_env_values
    assert all(value == "true" for value in observed_super_env_values)
