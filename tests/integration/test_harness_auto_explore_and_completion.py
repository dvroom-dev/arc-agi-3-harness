from __future__ import annotations

import json
import sys
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import numpy as np

import harness


def _seed_project(root: Path) -> None:
    (root / "tools").mkdir(parents=True)
    (root / "prompts").mkdir(parents=True)
    (root / "runs").mkdir(parents=True)
    (root / "super.yaml").write_text("runtime_defaults: {}\n")
    for f in ("arc_repl.py", "arc_repl_cli.py", "arc_repl_daemon.py"):
        (root / "tools" / f).write_text("#!/usr/bin/env python3\n")
    (root / "prompts" / "new_game_auto_explore.py").write_text("print('x')\n")


def test_harness_runs_auto_explore_once(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "proj"
    _seed_project(root)

    args = Namespace(
        game_id="ls20",
        max_turns=0,
        operation_mode="NORMAL",
        session_name="t-auto",
        verbose=False,
        open_scorecard=False,
        scorecard_id=None,
        provider="mock",
        no_supervisor=True,
        no_explore=False,
        max_game_over_resets=1,
        arc_backend="api",
        arc_base_url="http://example.test",
    )

    counters = {"turn": 0}
    base_grid = np.zeros((64, 64), dtype=np.int8)
    base_grid[10:12, 10:12] = 9
    base_grid[20:22, 20:22] = 5

    def fake_subprocess_run(cmd, **kwargs):
        text_input = kwargs.get("input")
        env = kwargs.get("env", {})
        arc_state_dir = Path(env.get("ARC_STATE_DIR", root / "runs" / "t-auto" / "supervisor" / "arc"))
        arc_state_dir.mkdir(parents=True, exist_ok=True)
        if isinstance(text_input, str):
            req = json.loads(text_input)
            action = req.get("action")
            if action == "exec":
                grid = base_grid.copy()
                grid[30, 30] = (counters["turn"] % 15) + 1
            else:
                grid = base_grid.copy()
            np.save(arc_state_dir / "current_grid.npy", grid.astype(np.int8))
            state = {
                "game_id": "ls20-cb3b57cc",
                "state": "NOT_FINISHED",
                "current_level": 1,
                "levels_completed": 0,
                "win_levels": 7,
                "last_action": action,
                "action_input_name": "ACTION1",
                "full_reset": False,
                "telemetry": {"steps_since_last_reset": counters["turn"]},
            }
            (arc_state_dir / "state.json").write_text(json.dumps(state))
            counters["turn"] += 1
            (arc_state_dir / "tool-engine-history.json").write_text(
                json.dumps({"turn": counters["turn"], "events": []})
            )
            payload = {
                "ok": True,
                **state,
                "available_actions": [0, 1, 2, 3, 4, 6],
                "game_id": "ls20-cb3b57cc",
            }
            if action == "shutdown":
                payload = {"ok": True, "action": "shutdown"}
            return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def fake_run_super(args_list, **kwargs):
        out = Path(args_list[args_list.index("--output") + 1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("---\nconversation_id: conv-1\n---\n")
        if args_list and args_list[0] != "resume":
            return "assistant"
        arc_state_dir = root / "runs" / "t-complete" / "supervisor" / "arc"
        arc_state_dir.mkdir(parents=True, exist_ok=True)
        (arc_state_dir / "state.json").write_text(
            json.dumps(
                {
                    "game_id": "ls20-cb3b57cc",
                    "state": "NOT_FINISHED",
                    "current_level": 2,
                    "levels_completed": 1,
                    "win_levels": 7,
                    "last_action": "exec",
                    "action_input_name": "ACTION1",
                    "full_reset": False,
                    "telemetry": {"steps_since_last_reset": 2},
                }
            )
        )
        (arc_state_dir / "tool-engine-history.json").write_text(
            json.dumps(
                {
                    "turn": counters["turn"] + 1,
                    "events": [
                        {"kind": "step", "action": "ACTION1", "levels_completed": 0},
                        {"kind": "step", "action": "ACTION2", "levels_completed": 1},
                    ],
                }
            )
        )
        return "assistant"

    monkeypatch.setattr(harness, "PROJECT_ROOT", root)
    monkeypatch.setattr(harness, "CTXS", root / ".ctxs")
    monkeypatch.setattr(harness, "PROJECT_VENV_PYTHON", Path(sys.executable))
    monkeypatch.setattr(harness, "parse_args", lambda: args)
    monkeypatch.setattr(harness, "cleanup_orphan_repl_daemons", lambda *a, **k: {"killed": 0, "stale_files_removed": 0, "skipped_active": 0})
    monkeypatch.setattr(harness, "run_super", fake_run_super)
    monkeypatch.setattr(harness.subprocess, "run", fake_subprocess_run)

    harness.main()
    marker = root / "runs" / "t-auto" / "supervisor" / "arc" / "auto_explore_once_ls20.done"
    assert marker.exists()


def test_harness_records_level_completion(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "proj"
    _seed_project(root)

    args = Namespace(
        game_id="ls20",
        max_turns=1,
        operation_mode="NORMAL",
        session_name="t-complete",
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

    counters = {"status": 0, "turn": 0}

    def fake_subprocess_run(cmd, **kwargs):
        text_input = kwargs.get("input")
        env = kwargs.get("env", {})
        arc_state_dir = Path(env.get("ARC_STATE_DIR", root / "runs" / "t-complete" / "supervisor" / "arc"))
        arc_state_dir.mkdir(parents=True, exist_ok=True)
        if isinstance(text_input, str):
            req = json.loads(text_input)
            action = req.get("action")
            counters["turn"] += 1
            if action == "status":
                counters["status"] += 1
                completed = 0 if counters["status"] == 1 else 1
            else:
                completed = 1
            state = {
                "game_id": "ls20-cb3b57cc",
                "state": "NOT_FINISHED",
                "current_level": completed + 1,
                "levels_completed": completed,
                "win_levels": 7,
                "last_action": action,
                "action_input_name": "ACTION1",
                "full_reset": False,
                "telemetry": {"steps_since_last_reset": 1},
            }
            (arc_state_dir / "state.json").write_text(json.dumps(state))
            (arc_state_dir / "tool-engine-history.json").write_text(
                json.dumps(
                    {
                        "turn": counters["turn"],
                        "events": [
                            {"kind": "step", "action": "ACTION1", "levels_completed": completed},
                        ],
                    }
                )
            )
            payload = {"ok": True, **state, "available_actions": [0, 1, 2, 3, 4]}
            if action == "shutdown":
                payload = {"ok": True, "action": "shutdown"}
            return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def fake_run_super(args_list, **kwargs):
        out = Path(args_list[args_list.index("--output") + 1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("---\nconversation_id: conv-1\n---\n")
        if args_list and args_list[0] != "resume":
            return "assistant"
        arc_state_dir = root / "runs" / "t-complete" / "supervisor" / "arc"
        arc_state_dir.mkdir(parents=True, exist_ok=True)
        (arc_state_dir / "state.json").write_text(
            json.dumps(
                {
                    "game_id": "ls20-cb3b57cc",
                    "state": "NOT_FINISHED",
                    "current_level": 2,
                    "levels_completed": 1,
                    "win_levels": 7,
                    "last_action": "exec",
                    "action_input_name": "ACTION1",
                    "full_reset": False,
                    "telemetry": {"steps_since_last_reset": 2},
                }
            )
        )
        (arc_state_dir / "tool-engine-history.json").write_text(
            json.dumps(
                {
                    "turn": counters["turn"] + 1,
                    "events": [
                        {"kind": "step", "action": "ACTION1", "levels_completed": 0},
                        {"kind": "step", "action": "ACTION2", "levels_completed": 1},
                    ],
                }
            )
        )
        return "assistant"

    monkeypatch.setattr(harness, "PROJECT_ROOT", root)
    monkeypatch.setattr(harness, "CTXS", root / ".ctxs")
    monkeypatch.setattr(harness, "PROJECT_VENV_PYTHON", Path(sys.executable))
    monkeypatch.setattr(harness, "parse_args", lambda: args)
    monkeypatch.setattr(harness, "cleanup_orphan_repl_daemons", lambda *a, **k: {"killed": 0, "stale_files_removed": 0, "skipped_active": 0})
    monkeypatch.setattr(harness, "run_super", fake_run_super)
    monkeypatch.setattr(harness.subprocess, "run", fake_subprocess_run)

    harness.main()
    completions = root / "runs" / "t-complete" / "supervisor" / "arc" / "level_completions.md"
    assert completions.exists()
    assert "Level 1 Completion" in completions.read_text()
