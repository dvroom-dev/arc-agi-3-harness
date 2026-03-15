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
        "---\nconversation_id: conv-1\nfork_id: fork-1\n---\n```chat role=assistant\nok\n```\n"
    )


def test_harness_continue_run_resumes_existing_supervisor_session(
    tmp_path: Path,
    monkeypatch,
) -> None:
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

    run_id = "t-continue"
    run_dir = root / "runs" / run_id
    conversation_id = "conversation_existing"
    fork_id = "fork_existing"
    conversation_dir = run_dir / ".ai-supervisor" / "conversations" / conversation_id
    forks_dir = conversation_dir / "forks"
    forks_dir.mkdir(parents=True, exist_ok=True)
    (conversation_dir / "index.json").write_text(
        json.dumps(
            {
                "conversationId": conversation_id,
                "headId": fork_id,
                "headIds": [fork_id],
                "forks": [{"id": fork_id, "storage": "snapshot", "actionSummary": "stop:rate_limit"}],
            }
        )
    )
    doc_text = (
        f"---\nconversation_id: {conversation_id}\nfork_id: {fork_id}\n---\n"
        "```chat role=user\nResume me\n```\n"
    )
    (forks_dir / f"{fork_id}.json").write_text(
        json.dumps({"id": fork_id, "storage": "snapshot", "documentText": doc_text})
    )
    (run_dir / "super").mkdir(parents=True, exist_ok=True)
    (run_dir / "super" / "state.json").write_text(
        json.dumps(
            {
                "conversationId": conversation_id,
                "activeForkId": fork_id,
                "activeMode": "theory",
                "activeModePayload": {"user_message": "Continue from existing state."},
            }
        )
    )

    args = Namespace(
        game_id="ls20",
        game_ids=None,
        max_turns=1,
        operation_mode="NORMAL",
        session_name=run_id,
        continue_run=True,
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

    super_invocations: list[list[str]] = []

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

    def fake_run_super(args_list, **kwargs):
        super_invocations.append(list(args_list))
        _fake_super_write_session(["super", *args_list])
        return ""

    monkeypatch.setattr(harness, "PROJECT_ROOT", root)
    monkeypatch.setattr(harness, "CTXS", root / ".ctxs")
    monkeypatch.setattr(harness, "PROJECT_VENV_PYTHON", Path(sys.executable))
    monkeypatch.setattr(harness, "parse_args", lambda: args)
    monkeypatch.setattr(harness, "cleanup_orphan_repl_daemons", lambda *a, **k: {"killed": 0, "stale_files_removed": 0, "skipped_active": 0})
    monkeypatch.setattr(harness, "cleanup_orphan_run_processes", lambda *a, **k: {"killed": 0, "skipped_active": 0, "scanned": 0})
    monkeypatch.setattr(harness, "run_super", fake_run_super)
    monkeypatch.setattr(harness.subprocess, "run", fake_subprocess_run)

    harness.main()

    assert super_invocations
    assert all("new" not in invocation for invocation in super_invocations)
    assert any("resume" in invocation for invocation in super_invocations)
