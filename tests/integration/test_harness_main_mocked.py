from __future__ import annotations

import json
import sys
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import harness
import pytest


def _fake_super_write_session(cmd: list[str]) -> None:
    if "--output" not in cmd:
        return
    out = Path(cmd[cmd.index("--output") + 1])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        "---\nconversation_id: conv-1\nfork_id: fork-1\n---\n```chat role=assistant\nok\n```\n"
    )


def test_harness_main_smoke_no_llm_calls(tmp_path: Path, monkeypatch) -> None:
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
        session_name="t-run",
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
    phase_log = root / "runs" / "t-run" / "telemetry" / "harness_phases.ndjson"
    assert phase_log.exists()
    categories = {
        json.loads(line)["category"]
        for line in phase_log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    assert "setup" in categories
    assert "tool" in categories
    assert "super" in categories


def test_harness_sets_only_reset_levels_in_child_and_super_envs(
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
        explore_inputs=False,
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


def test_harness_recovers_session_md_from_workspace_store_before_resume(
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

    args = Namespace(
        game_id="ls20",
        max_turns=1,
        operation_mode="NORMAL",
        session_name="t-recover",
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

    recovered_doc = {
        "text": "---\nconversation_id: conversation_abc\nfork_id: fork-1\n---\n```chat role=assistant\nok\n```\n"
    }
    seen_resume_doc = {"text": ""}

    def write_workspace_conversation(doc_text: str) -> None:
        conversations_dir = (
            root
            / "runs"
            / "t-recover"
            / ".ai-supervisor"
            / "conversations"
            / "conversation_abc"
        )
        forks_dir = conversations_dir / "forks"
        forks_dir.mkdir(parents=True, exist_ok=True)
        (conversations_dir / "index.json").write_text(
            json.dumps(
                {
                    "conversationId": "conversation_abc",
                    "headId": "fork_store_head",
                    "headIds": ["fork_store_head"],
                    "forks": [{"id": "fork_store_head", "storage": "snapshot"}],
                }
            )
        )
        (forks_dir / "fork_store_head.json").write_text(
            json.dumps(
                {
                    "id": "fork_store_head",
                    "storage": "snapshot",
                    "documentText": doc_text,
                }
            )
        )

    def fake_subprocess_run(cmd, **kwargs):
        text_input = kwargs.get("input")
        arc_state_dir = root / "runs" / "t-recover" / "supervisor" / "arc"
        arc_state_dir.mkdir(parents=True, exist_ok=True)
        if isinstance(text_input, str):
            req = json.loads(text_input)
            action = req.get("action")
            if action == "status":
                state_payload = {
                    "ok": True,
                    "game_id": "ls20-cb3b57cc",
                    "state": "NOT_FINISHED",
                    "current_level": 1,
                    "levels_completed": 0,
                    "win_levels": 7,
                    "available_actions": [0, 1, 2, 3, 4],
                    "last_action": "status",
                    "action_input_name": "ACTION1",
                    "full_reset": False,
                    "telemetry": {"steps_since_last_reset": 0},
                }
            elif action == "shutdown":
                state_payload = {"ok": True, "action": "shutdown"}
            else:
                state_payload = {"ok": True}
            return SimpleNamespace(returncode=0, stdout=json.dumps(state_payload), stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def fake_run_super(args, **kwargs):
        mode = args[0]
        if mode == "new":
            write_workspace_conversation(recovered_doc["text"])
            return ""
        if mode == "recover":
            out = Path(args[args.index("--output") + 1])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(recovered_doc["text"])
            return ""
        if mode == "resume":
            session_path = root / ".ctxs" / "t-recover" / "session.md"
            seen_resume_doc["text"] = session_path.read_text()
            arc_state_dir = root / "runs" / "t-recover" / "supervisor" / "arc"
            (arc_state_dir / "state.json").write_text(
                json.dumps(
                    {
                        "game_id": "ls20-cb3b57cc",
                        "state": "WIN",
                        "current_level": 1,
                        "levels_completed": 7,
                        "win_levels": 7,
                        "last_action": "exec",
                        "action_input_name": "ACTION1",
                        "full_reset": False,
                        "telemetry": {"steps_since_last_reset": 1},
                    }
                )
            )
            (arc_state_dir / "tool-engine-history.json").write_text(
                json.dumps({"turn": 2, "events": [{"kind": "step", "action": "ACTION1"}]})
            )
            recovered_doc["text"] = (
                "---\nconversation_id: conversation_abc\nfork_id: fork-2\n---\n"
                "```chat role=assistant\nupdated\n```\n"
            )
            write_workspace_conversation(recovered_doc["text"])
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

    assert "fork_id: fork-1" in seen_resume_doc["text"]
    session_text = (root / ".ctxs" / "t-recover" / "session.md").read_text()
    assert "fork_id: fork-2" in session_text
    assert (root / ".ctxs" / "t-recover" / "forks" / "index.json").exists()
    assert (root / ".ctxs" / "t-recover" / "forks" / "fork_store_head.json").exists()


def test_harness_fails_loudly_on_noop_provider_cycle(
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

    args = Namespace(
        game_id="ls20",
        max_turns=2,
        operation_mode="NORMAL",
        session_name="t-noop",
        verbose=False,
        open_scorecard=False,
        scorecard_id=None,
        provider="mock",
        no_supervisor=True,
        explore_inputs=False,
        max_game_over_resets=0,
        arc_backend="api",
        arc_base_url="http://example.test",
    )

    current_doc = {
        "text": "---\nconversation_id: conversation_noop\nfork_id: fork-1\n---\n```chat role=user\nhello\n```\n"
    }
    current_head = {"id": "fork_store_1", "parent": None}

    def write_workspace_conversation() -> None:
        conversation_dir = (
            root
            / "runs"
            / "t-noop"
            / ".ai-supervisor"
            / "conversations"
            / "conversation_noop"
        )
        forks_dir = conversation_dir / "forks"
        forks_dir.mkdir(parents=True, exist_ok=True)
        (conversation_dir / "index.json").write_text(
            json.dumps(
                {
                    "conversationId": "conversation_noop",
                    "headId": current_head["id"],
                    "headIds": [current_head["id"]],
                    "forks": [
                        {
                            "id": current_head["id"],
                            "parentId": current_head["parent"],
                            "storage": "snapshot",
                            "docHash": "same-doc-hash",
                        }
                    ],
                }
            )
        )
        (forks_dir / f"{current_head['id']}.json").write_text(
            json.dumps(
                {
                    "id": current_head["id"],
                    "parentId": current_head["parent"],
                    "storage": "snapshot",
                    "documentText": current_doc["text"],
                    "docHash": "same-doc-hash",
                }
            )
        )

    def fake_subprocess_run(cmd, **kwargs):
        text_input = kwargs.get("input")
        arc_state_dir = root / "runs" / "t-noop" / "supervisor" / "arc"
        arc_state_dir.mkdir(parents=True, exist_ok=True)
        (arc_state_dir / "tool-engine-history.json").write_text(json.dumps({"turn": 1, "events": []}))
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
                    "last_action": "status",
                    "action_input_name": "RESET",
                    "full_reset": False,
                    "telemetry": {"steps_since_last_reset": 0},
                }
                (arc_state_dir / "state.json").write_text(json.dumps(payload))
            elif action == "shutdown":
                payload = {"ok": True, "action": "shutdown"}
            else:
                payload = {"ok": True}
            return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def fake_run_super(args, **kwargs):
        mode = args[0]
        if mode == "new":
            write_workspace_conversation()
            return ""
        if mode == "recover":
            out = Path(args[args.index("--output") + 1])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(current_doc["text"])
            return ""
        if mode == "resume":
            current_head["parent"] = current_head["id"]
            current_head["id"] = "fork_store_2"
            write_workspace_conversation()
            return ""
        return ""

    monkeypatch.setattr(harness, "PROJECT_ROOT", root)
    monkeypatch.setattr(harness, "CTXS", root / ".ctxs")
    monkeypatch.setattr(harness, "PROJECT_VENV_PYTHON", Path(sys.executable))
    monkeypatch.setattr(harness, "parse_args", lambda: args)
    monkeypatch.setattr(harness, "cleanup_orphan_repl_daemons", lambda *a, **k: {"killed": 0, "stale_files_removed": 0, "skipped_active": 0})
    monkeypatch.setattr(harness, "run_super", fake_run_super)
    monkeypatch.setattr(harness.subprocess, "run", fake_subprocess_run)

    with pytest.raises(RuntimeError, match="no-op provider cycle"):
        harness.main()
