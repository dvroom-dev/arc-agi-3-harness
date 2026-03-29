from __future__ import annotations

import json
import sys
from argparse import Namespace
from pathlib import Path
from types import ModuleType, SimpleNamespace

import harness


def _seed_level_start_artifacts(root: Path, session_name: str, game_id: str = "ls20", level: int = 1) -> None:
    level_current = root / "runs" / session_name / "agent" / f"game_{game_id}" / "level_current"
    level_current.mkdir(parents=True, exist_ok=True)
    (level_current / "meta.json").write_text(json.dumps({"level": level}) + "\n", encoding="utf-8")
    (level_current / "initial_state.hex").write_text("0123\n4567\n", encoding="utf-8")


def test_harness_open_and_close_scorecard_mocked(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ARC_API_KEY", "test-key")
    root = tmp_path / "proj"
    (root / "tools").mkdir(parents=True)
    (root / "prompts").mkdir(parents=True)
    (root / "runs").mkdir(parents=True)
    (root / "arc_model_runtime").mkdir(parents=True)
    (root / "super.yaml").write_text("runtime_defaults: {}\n")
    (root / "arc_model_runtime" / "__init__.py").write_text("# runtime\n")
    for f in ("arc_repl.py", "arc_repl_cli.py", "arc_repl_daemon.py", "arc_level.py"):
        (root / "tools" / f).write_text("#!/usr/bin/env python3\n")
    (root / "prompts" / "new_game_auto_explore.py").write_text("print('x')\n")

    args = Namespace(
        game_id="ls20",
        max_turns=0,
        operation_mode="ONLINE",
        session_name="t-score",
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

    class FakeOperationMode:
        @classmethod
        def __class_getitem__(cls, key):
            return key

    class FakeArcadeClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def open_scorecard(self, tags, opaque):
            return "sc-1"

        def close_scorecard(self, scorecard_id):
            return SimpleNamespace(score=123)

    fake_arc = ModuleType("arc_agi")
    fake_arc.Arcade = FakeArcadeClient
    fake_arc.OperationMode = FakeOperationMode
    monkeypatch.setitem(sys.modules, "arc_agi", fake_arc)

    def fake_subprocess_run(cmd, **kwargs):
        text_input = kwargs.get("input")
        env = kwargs.get("env", {})
        arc_state_dir = Path(env.get("ARC_STATE_DIR", root / "runs" / "t-score" / "supervisor" / "arc"))
        arc_state_dir.mkdir(parents=True, exist_ok=True)
        _seed_level_start_artifacts(root, "t-score")
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
                "scorecard_id": "sc-1",
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
        out.write_text("---\nconversation_id: conv-1\nfork_id: fork-1\n---\n")
        return "assistant"

    monkeypatch.setattr(harness, "PROJECT_ROOT", root)
    monkeypatch.setattr(harness, "CTXS", root / ".ctxs")
    monkeypatch.setattr(harness, "PROJECT_VENV_PYTHON", Path(sys.executable))
    monkeypatch.setattr(harness, "parse_args", lambda: args)
    monkeypatch.setattr(harness, "cleanup_orphan_repl_daemons", lambda *a, **k: {"killed": 0, "stale_files_removed": 0, "skipped_active": 0})
    monkeypatch.setattr(harness, "run_super", fake_run_super)
    monkeypatch.setattr(harness.subprocess, "run", fake_subprocess_run)

    harness.main()
    score_meta = root / ".ctxs" / "t-score" / "scorecard.json"
    assert score_meta.exists()
    payload = json.loads(score_meta.read_text())
    assert payload["scorecard_id"] == "sc-1"
    assert payload["closed"] is True


def test_harness_score_after_solve_opens_mid_run_and_uses_start_mode(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("ARC_API_KEY", "test-key")
    root = tmp_path / "proj"
    (root / "tools").mkdir(parents=True)
    (root / "prompts").mkdir(parents=True)
    (root / "runs").mkdir(parents=True)
    (root / "arc_model_runtime").mkdir(parents=True)
    (root / "super.yaml").write_text("runtime_defaults: {}\n")
    (root / "arc_model_runtime" / "__init__.py").write_text("# runtime\n")
    for f in ("arc_repl.py", "arc_repl_cli.py", "arc_repl_daemon.py", "arc_level.py"):
        (root / "tools" / f).write_text("#!/usr/bin/env python3\n")
    (root / "prompts" / "new_game_auto_explore.py").write_text("print('x')\n")

    args = Namespace(
        game_id="ls20",
        game_ids=None,
        max_turns=None,
        operation_mode="ONLINE",
        session_name="t-score-after-solve",
        verbose=False,
        open_scorecard=False,
        scorecard_id=None,
        provider="mock",
        no_supervisor=True,
        explore_inputs=False,
        max_game_over_resets=1,
        arc_backend="api",
        arc_base_url="http://example.test",
        score_after_solve=True,
        score_after_solve_start_mode="recover",
        scorecard_owner_check_id=None,
        scorecard_session_preflight=False,
    )

    class FakeOperationMode:
        @classmethod
        def __class_getitem__(cls, key):
            return key

    class FakeArcadeClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self._opened = 0

        def open_scorecard(self, tags, opaque):
            self._opened += 1
            return f"sc-mid-{self._opened}"

        def close_scorecard(self, scorecard_id):
            return SimpleNamespace(score=77)

    fake_arc = ModuleType("arc_agi")
    fake_arc.Arcade = FakeArcadeClient
    fake_arc.OperationMode = FakeOperationMode
    monkeypatch.setitem(sys.modules, "arc_agi", fake_arc)

    history_turn = {"n": 0}

    def _write_state(arc_state_dir: Path, *, state: str, current_level: int, levels_completed: int) -> None:
        arc_state_dir.mkdir(parents=True, exist_ok=True)
        (arc_state_dir / "state.json").write_text(
            json.dumps(
                {
                    "game_id": "ls20-cb3b57cc",
                    "state": state,
                    "current_level": current_level,
                    "levels_completed": levels_completed,
                    "win_levels": 7,
                    "last_action": "status",
                    "action_input_name": "ACTION1",
                    "full_reset": False,
                    "telemetry": {"steps_since_last_reset": 0},
                }
            )
        )
        history_turn["n"] += 1
        (arc_state_dir / "tool-engine-history.json").write_text(
            json.dumps({"turn": history_turn["n"], "events": []})
        )

    def fake_subprocess_run(cmd, **kwargs):
        text_input = kwargs.get("input")
        env = kwargs.get("env", {})
        arc_state_dir = Path(env.get("ARC_STATE_DIR", root / "runs" / "t-score-after-solve" / "supervisor" / "arc"))
        _seed_level_start_artifacts(root, "t-score-after-solve")
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
                    "scorecard_id": env.get("ARC_SCORECARD_ID"),
                }
                _write_state(arc_state_dir, state="NOT_FINISHED", current_level=1, levels_completed=0)
            elif action == "reset_level":
                payload = {
                    "ok": True,
                    "game_id": "ls20-cb3b57cc",
                    "state": "NOT_FINISHED",
                    "current_level": 1,
                    "levels_completed": 0,
                    "win_levels": 7,
                    "available_actions": [0, 1, 2, 3, 4],
                    "scorecard_id": env.get("ARC_SCORECARD_ID"),
                }
                _write_state(arc_state_dir, state="NOT_FINISHED", current_level=1, levels_completed=0)
            elif action == "shutdown":
                payload = {"ok": True, "action": "shutdown"}
            else:
                payload = {"ok": True}
            return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    new_calls: list[list[str]] = []

    def fake_run_super(args_list, **kwargs):
        out = Path(args_list[args_list.index("--output") + 1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("---\nconversation_id: conv-1\nfork_id: fork-1\n---\n")
        if args_list and args_list[0] == "new":
            new_calls.append(list(args_list))
            arc_state_dir = Path((kwargs.get("env") or {}).get("ARC_STATE_DIR"))
            # Make each phase immediately appear solved.
            _seed_level_start_artifacts(root, "t-score-after-solve", level=8)
            _write_state(arc_state_dir, state="WIN", current_level=8, levels_completed=7)
        return "assistant"

    monkeypatch.setattr(harness, "PROJECT_ROOT", root)
    monkeypatch.setattr(harness, "CTXS", root / ".ctxs")
    monkeypatch.setattr(harness, "PROJECT_VENV_PYTHON", Path(sys.executable))
    monkeypatch.setattr(harness, "parse_args", lambda: args)
    monkeypatch.setattr(harness, "cleanup_orphan_repl_daemons", lambda *a, **k: {"killed": 0, "stale_files_removed": 0, "skipped_active": 0})
    monkeypatch.setattr(harness, "run_super", fake_run_super)
    monkeypatch.setattr(harness.subprocess, "run", fake_subprocess_run)

    harness.main()

    assert len(new_calls) == 2
    assert "--start-mode" not in new_calls[0]
    assert "--start-mode" in new_calls[1]
    idx = new_calls[1].index("--start-mode")
    assert new_calls[1][idx + 1] == "recover"

    score_meta = root / ".ctxs" / "t-score-after-solve" / "scorecard.json"
    assert score_meta.exists()
    payload = json.loads(score_meta.read_text())
    assert payload["scorecard_id"].startswith("sc-mid-")
    assert payload["closed"] is True
