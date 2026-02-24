from __future__ import annotations

import json
import sys
from argparse import Namespace
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

import harness


def _seed_project(root: Path) -> None:
    (root / "tools").mkdir(parents=True)
    (root / "prompts").mkdir(parents=True)
    (root / "runs").mkdir(parents=True)
    (root / "super.yaml").write_text("runtime_defaults: {}\n")
    for f in ("arc_repl.py", "arc_repl_cli.py", "arc_repl_daemon.py"):
        (root / "tools" / f).write_text("#!/usr/bin/env python3\n")
    (root / "prompts" / "new_game_auto_explore.py").write_text("print('x')\n")


def test_harness_reuses_existing_scorecard_without_closing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ARC_API_KEY", "test-key")
    root = tmp_path / "proj"
    _seed_project(root)

    calls = {"get": 0, "close": 0}

    class FakeOperationMode:
        @classmethod
        def __class_getitem__(cls, key):
            return key

    class FakeArcadeClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def get_scorecard(self, scorecard_id):
            calls["get"] += 1
            return {"id": scorecard_id}

        def close_scorecard(self, scorecard_id):
            calls["close"] += 1
            return SimpleNamespace(score=999)

    fake_arc = ModuleType("arc_agi")
    fake_arc.Arcade = FakeArcadeClient
    fake_arc.OperationMode = FakeOperationMode
    monkeypatch.setitem(sys.modules, "arc_agi", fake_arc)

    args = Namespace(
        game_id="ls20",
        max_turns=0,
        operation_mode="ONLINE",
        session_name="t-reuse-score",
        verbose=False,
        open_scorecard=False,
        scorecard_id="sc-existing",
        provider="mock",
        no_supervisor=True,
        no_explore=True,
        max_game_over_resets=1,
        arc_backend="api",
        arc_base_url="http://example.test",
    )

    def fake_subprocess_run(cmd, **kwargs):
        text_input = kwargs.get("input")
        env = kwargs.get("env", {})
        arc_state_dir = Path(env.get("ARC_STATE_DIR", root / "runs" / "t-reuse-score" / "supervisor" / "arc"))
        arc_state_dir.mkdir(parents=True, exist_ok=True)
        if isinstance(text_input, str):
            req = json.loads(text_input)
            action = req.get("action")
            payload = {
                "ok": True,
                "game_id": "ls20-cb3b57cc",
                "state": "NOT_FINISHED",
                "current_level": 1,
                "levels_completed": 0,
                "win_levels": 7,
                "available_actions": [0, 1, 2, 3, 4],
                "scorecard_id": "sc-existing",
            }
            if action == "shutdown":
                payload = {"ok": True, "action": "shutdown"}
            (arc_state_dir / "state.json").write_text(
                json.dumps(
                    {
                        "game_id": "ls20-cb3b57cc",
                        "state": "NOT_FINISHED",
                        "current_level": 1,
                        "levels_completed": 0,
                        "win_levels": 7,
                        "last_action": action,
                        "action_input_name": "ACTION1",
                        "full_reset": False,
                        "telemetry": {"steps_since_last_reset": 0},
                    }
                )
            )
            (arc_state_dir / "tool-engine-history.json").write_text(json.dumps({"turn": 1, "events": []}))
            return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def fake_run_super(args_list, **kwargs):
        out = Path(args_list[args_list.index("--output") + 1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("---\nconversation_id: conv-1\n---\n")
        return "assistant"

    monkeypatch.setattr(harness, "PROJECT_ROOT", root)
    monkeypatch.setattr(harness, "CTXS", root / ".ctxs")
    monkeypatch.setattr(harness, "PROJECT_VENV_PYTHON", Path(sys.executable))
    monkeypatch.setattr(harness, "parse_args", lambda: args)
    monkeypatch.setattr(harness, "cleanup_orphan_repl_daemons", lambda *a, **k: {"killed": 0, "stale_files_removed": 0, "skipped_active": 0})
    monkeypatch.setattr(harness, "run_super", fake_run_super)
    monkeypatch.setattr(harness.subprocess, "run", fake_subprocess_run)

    harness.main()

    assert calls["get"] == 1
    assert calls["close"] == 0
    score_meta = root / ".ctxs" / "t-reuse-score" / "scorecard.json"
    assert score_meta.exists()
    payload = json.loads(score_meta.read_text())
    assert payload["created_here"] is False


def test_harness_scorecard_requires_online_mode(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "proj"
    _seed_project(root)

    args = Namespace(
        game_id="ls20",
        max_turns=0,
        operation_mode="NORMAL",
        session_name="t-score-err",
        verbose=False,
        open_scorecard=True,
        scorecard_id=None,
        provider="mock",
        no_supervisor=True,
        no_explore=True,
        max_game_over_resets=1,
        arc_backend="api",
        arc_base_url="http://example.test",
    )

    monkeypatch.setattr(harness, "PROJECT_ROOT", root)
    monkeypatch.setattr(harness, "CTXS", root / ".ctxs")
    monkeypatch.setattr(harness, "PROJECT_VENV_PYTHON", Path(sys.executable))
    monkeypatch.setattr(harness, "parse_args", lambda: args)
    monkeypatch.setattr(harness, "cleanup_orphan_repl_daemons", lambda *a, **k: {"killed": 0, "stale_files_removed": 0, "skipped_active": 0})

    with pytest.raises(RuntimeError, match="Scorecards require ONLINE mode"):
        harness.main()


def test_harness_scored_run_requires_api_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("ARC_API_KEY", raising=False)
    monkeypatch.setattr("harness_runtime.resolve_arc_api_key", lambda **kwargs: "")
    root = tmp_path / "proj"
    _seed_project(root)

    args = Namespace(
        game_id="ls20",
        max_turns=0,
        operation_mode="ONLINE",
        session_name="t-score-key-required",
        verbose=False,
        open_scorecard=True,
        scorecard_id=None,
        provider="mock",
        no_supervisor=True,
        no_explore=True,
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

    with pytest.raises(RuntimeError, match="ARC_API_KEY is required"):
        harness.main()


def test_harness_owner_check_rejects_wrong_account_scorecard_id(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ARC_API_KEY", "test-key")
    root = tmp_path / "proj"
    _seed_project(root)

    calls = {"open": 0, "get": 0}

    class FakeOperationMode:
        @classmethod
        def __class_getitem__(cls, key):
            return key

    class FakeArcadeClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def get_scorecard(self, scorecard_id):
            calls["get"] += 1
            raise RuntimeError("404 not found")

        def open_scorecard(self, tags, opaque):
            calls["open"] += 1
            return "sc-new"

    fake_arc = ModuleType("arc_agi")
    fake_arc.Arcade = FakeArcadeClient
    fake_arc.OperationMode = FakeOperationMode
    monkeypatch.setitem(sys.modules, "arc_agi", fake_arc)

    args = Namespace(
        game_id="ls20",
        game_ids="ls20,ft09",
        max_turns=0,
        operation_mode="ONLINE",
        session_name="t-owner-check-fail",
        verbose=False,
        open_scorecard=True,
        scorecard_id=None,
        scorecard_owner_check_id="known-good-scorecard",
        provider="mock",
        no_supervisor=True,
        no_explore=True,
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

    with pytest.raises(RuntimeError, match="Scorecard owner check failed"):
        harness.main()

    assert calls["get"] == 1
    assert calls["open"] == 0
