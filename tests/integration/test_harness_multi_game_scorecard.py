from __future__ import annotations

import json
import sys
from argparse import Namespace
from pathlib import Path
from types import ModuleType, SimpleNamespace

import harness
import requests.utils


def _seed_project(root: Path) -> None:
    (root / "tools").mkdir(parents=True)
    (root / "prompts").mkdir(parents=True)
    (root / "runs").mkdir(parents=True)
    (root / "super.yaml").write_text("runtime_defaults: {}\n")
    for f in ("arc_repl.py", "arc_repl_cli.py", "arc_repl_daemon.py"):
        (root / "tools" / f).write_text("#!/usr/bin/env python3\n")
    (root / "prompts" / "new_game_auto_explore.py").write_text("print('x')\n")


def test_harness_runs_multiple_games_under_one_shared_scorecard(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("ARC_API_KEY", "test-key")
    root = tmp_path / "proj"
    _seed_project(root)

    args = Namespace(
        game_id="ls20",
        game_ids="ls20,ft09",
        max_turns=0,
        operation_mode="ONLINE",
        session_name="batch",
        verbose=False,
        open_scorecard=True,
        scorecard_id=None,
        provider="mock",
        no_supervisor=True,
        explore_inputs=False,
        max_game_over_resets=1,
        arc_backend="api",
        arc_base_url="http://example.test",
    )

    calls = {
        "open": 0,
        "close": 0,
        "get": 0,
    }
    observed_status_requests: list[str] = []
    observed_scorecard_env: list[str | None] = []
    observed_scorecard_cookies_env: list[str | None] = []

    class FakeOperationMode:
        @classmethod
        def __class_getitem__(cls, key):
            return key

    class FakeArcadeClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self._session = SimpleNamespace(
                cookies=requests.utils.cookiejar_from_dict(
                    {"GAMESESSION": "cookie-batch"},
                    overwrite=True,
                )
            )

        def open_scorecard(self, tags, opaque):
            calls["open"] += 1
            return "sc-batch"

        def get_scorecard(self, scorecard_id):
            calls["get"] += 1
            return {"id": scorecard_id}

        def close_scorecard(self, scorecard_id):
            calls["close"] += 1
            return SimpleNamespace(score=111)

    fake_arc = ModuleType("arc_agi")
    fake_arc.Arcade = FakeArcadeClient
    fake_arc.OperationMode = FakeOperationMode
    monkeypatch.setitem(sys.modules, "arc_agi", fake_arc)

    def fake_subprocess_run(cmd, **kwargs):
        text_input = kwargs.get("input")
        env = kwargs.get("env", {})
        observed_scorecard_env.append(env.get("ARC_SCORECARD_ID"))
        observed_scorecard_cookies_env.append(env.get("ARC_SCORECARD_COOKIES"))
        arc_state_dir = Path(env.get("ARC_STATE_DIR", root / "runs" / "batch" / "supervisor" / "arc"))
        arc_state_dir.mkdir(parents=True, exist_ok=True)
        if isinstance(text_input, str):
            req = json.loads(text_input)
            action = req.get("action")
            req_game = str(req.get("game_id", "") or "").strip()
            if action == "status":
                observed_status_requests.append(req_game)
                payload = {
                    "ok": True,
                    "game_id": f"{req_game}-gamehash",
                    "state": "NOT_FINISHED",
                    "current_level": 1,
                    "levels_completed": 0,
                    "win_levels": 7,
                    "available_actions": [0, 1, 2, 3, 4],
                    "scorecard_id": "sc-batch",
                }
                state_payload = {
                    "game_id": payload["game_id"],
                    "state": "NOT_FINISHED",
                    "current_level": 1,
                    "levels_completed": 0,
                    "win_levels": 7,
                    "last_action": "status",
                    "action_input_name": "ACTION1",
                    "full_reset": False,
                    "telemetry": {"steps_since_last_reset": 0},
                }
                (arc_state_dir / "state.json").write_text(json.dumps(state_payload))
                (arc_state_dir / "tool-engine-history.json").write_text(
                    json.dumps({"turn": 1, "events": []})
                )
            elif action == "shutdown":
                payload = {"ok": True, "action": "shutdown"}
            else:
                payload = {"ok": True}
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

    assert calls["open"] == 1
    assert calls["close"] == 1
    # One GET validation is performed immediately after shared scorecard creation.
    assert calls["get"] == 1
    assert observed_status_requests == ["ls20", "ft09"]
    assert observed_scorecard_env
    assert all(v == "sc-batch" for v in observed_scorecard_env)
    assert observed_scorecard_cookies_env
    assert all(v and "GAMESESSION" in v for v in observed_scorecard_cookies_env)
    assert (root / ".ctxs" / "batch-01-ls20").exists()
    assert (root / ".ctxs" / "batch-02-ft09").exists()
    first_arc = root / "runs" / "batch-01-ls20" / "supervisor" / "arc"
    assert not (first_arc / "game-knowledge.md").exists()
    assert not (first_arc / "level-knowledge.md").exists()


def test_harness_multi_game_reused_scorecard_validates_per_game(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("ARC_API_KEY", "test-key")
    root = tmp_path / "proj"
    _seed_project(root)

    args = Namespace(
        game_id="ls20",
        game_ids="ls20,ft09,vc33",
        max_turns=0,
        operation_mode="ONLINE",
        session_name="batch-reuse",
        verbose=False,
        open_scorecard=False,
        scorecard_id="sc-reuse",
        provider="mock",
        no_supervisor=True,
        explore_inputs=False,
        max_game_over_resets=1,
        arc_backend="api",
        arc_base_url="http://example.test",
    )

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
            return SimpleNamespace(score=111)

    fake_arc = ModuleType("arc_agi")
    fake_arc.Arcade = FakeArcadeClient
    fake_arc.OperationMode = FakeOperationMode
    monkeypatch.setitem(sys.modules, "arc_agi", fake_arc)

    def fake_subprocess_run(cmd, **kwargs):
        text_input = kwargs.get("input")
        env = kwargs.get("env", {})
        arc_state_dir = Path(env.get("ARC_STATE_DIR", root / "runs" / "batch-reuse" / "supervisor" / "arc"))
        arc_state_dir.mkdir(parents=True, exist_ok=True)
        if isinstance(text_input, str):
            req = json.loads(text_input)
            action = req.get("action")
            req_game = str(req.get("game_id", "") or "").strip()
            payload = {
                "ok": True,
                "game_id": f"{req_game}-gamehash",
                "state": "NOT_FINISHED",
                "current_level": 1,
                "levels_completed": 0,
                "win_levels": 7,
                "available_actions": [0, 1, 2, 3, 4],
                "scorecard_id": "sc-reuse",
            }
            if action == "shutdown":
                payload = {"ok": True, "action": "shutdown"}
            (arc_state_dir / "state.json").write_text(
                json.dumps(
                    {
                        "game_id": payload.get("game_id", "ls20-cb3b57cc"),
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
            (arc_state_dir / "tool-engine-history.json").write_text(
                json.dumps({"turn": 1, "events": []})
            )
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
    monkeypatch.setattr(
        harness,
        "cleanup_orphan_repl_daemons",
        lambda *a, **k: {"killed": 0, "stale_files_removed": 0, "skipped_active": 0},
    )
    monkeypatch.setattr(harness, "run_super", fake_run_super)
    monkeypatch.setattr(harness.subprocess, "run", fake_subprocess_run)

    harness.main()

    # Reused scorecard must be validated in each per-game session.
    assert calls["get"] == 3
    assert calls["close"] == 0
