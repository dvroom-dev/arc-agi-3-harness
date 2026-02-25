from __future__ import annotations

import json
import sys
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import harness


def _write_session_file(path: Path, conversation_id: str = "conv-1") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nconversation_id: {conversation_id}\n---\n```chat role=assistant\nok\n```\n"
    )


def test_harness_main_handles_game_over_then_reset(tmp_path: Path, monkeypatch) -> None:
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
        max_turns=2,
        operation_mode="NORMAL",
        session_name="t-loop",
        verbose=False,
        open_scorecard=False,
        scorecard_id=None,
        provider="mock",
        no_supervisor=True,
        explore_inputs=False,
        max_game_over_resets=2,
        arc_backend="api",
        arc_base_url="http://example.test",
    )

    state_counter = {"status_calls": 0}
    seen_repl_session_keys: list[str] = []

    def fake_subprocess_run(cmd, **kwargs):
        text_input = kwargs.get("input")
        env = kwargs.get("env", {})
        seen_repl_session_keys.append(str(env.get("ARC_REPL_SESSION_KEY", "")))
        arc_state_dir = Path(env.get("ARC_STATE_DIR", root / "runs" / "t-loop" / "supervisor" / "arc"))
        arc_state_dir.mkdir(parents=True, exist_ok=True)
        history_file = arc_state_dir / "tool-engine-history.json"
        turn = 0
        if history_file.exists():
            try:
                turn = int(json.loads(history_file.read_text()).get("turn", 0))
            except Exception:
                turn = 0

        if isinstance(text_input, str):
            req = json.loads(text_input)
            action = req.get("action")
            if action == "status":
                state_counter["status_calls"] += 1
                if state_counter["status_calls"] == 1:
                    state = "NOT_FINISHED"
                elif state_counter["status_calls"] == 2:
                    state = "GAME_OVER"
                else:
                    state = "WIN"
                state_payload = {
                    "game_id": "ls20-cb3b57cc",
                    "state": state,
                    "current_level": 1,
                    "levels_completed": 0,
                    "win_levels": 7,
                    "last_action": "status",
                    "action_input_name": "ACTION1",
                    "full_reset": False,
                    "telemetry": {"steps_since_last_reset": 1},
                }
                (arc_state_dir / "state.json").write_text(json.dumps(state_payload))
                payload = {"ok": True, **state_payload, "available_actions": [0, 1, 2, 3, 4]}
            elif action == "reset_level":
                state_payload = {
                    "game_id": "ls20-cb3b57cc",
                    "state": "NOT_FINISHED",
                    "current_level": 1,
                    "levels_completed": 0,
                    "win_levels": 7,
                    "last_action": "reset_level",
                    "action_input_name": "RESET",
                    "full_reset": False,
                    "telemetry": {"steps_since_last_reset": 0},
                }
                (arc_state_dir / "state.json").write_text(json.dumps(state_payload))
                payload = {"ok": True, **state_payload, "available_actions": [0, 1, 2, 3, 4]}
            elif action == "shutdown":
                payload = {"ok": True, "action": "shutdown"}
            else:
                payload = {"ok": True}
            turn += 1
            history_file.write_text(json.dumps({"turn": turn, "events": []}))
            return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def fake_run_super(args_list, **kwargs):
        if "new" in args_list:
            out = Path(args_list[args_list.index("--output") + 1])
            _write_session_file(out, conversation_id="conv-1")
            return "assistant"
        if "resume" in args_list:
            out = Path(args_list[args_list.index("--output") + 1])
            _write_session_file(out, conversation_id="conv-2")
            return "assistant"
        return ""

    monkeypatch.setattr(harness, "PROJECT_ROOT", root)
    monkeypatch.setattr(harness, "CTXS", root / ".ctxs")
    monkeypatch.setattr(harness, "PROJECT_VENV_PYTHON", Path(sys.executable))
    monkeypatch.setattr(harness, "parse_args", lambda: args)
    monkeypatch.setattr(harness, "cleanup_orphan_repl_daemons", lambda *a, **k: {"killed": 0, "stale_files_removed": 0, "skipped_active": 0})
    monkeypatch.setattr(harness, "run_super", fake_run_super)
    monkeypatch.setattr(harness.subprocess, "run", fake_subprocess_run)

    harness.main()
    assert (root / ".ctxs" / "t-loop" / "session.md").exists()
    assert seen_repl_session_keys
    assert all(k == "t-loop__ls20" for k in seen_repl_session_keys)
