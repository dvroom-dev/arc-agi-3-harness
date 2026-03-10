from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import harness
import harness_runtime_session


def test_run_super_streaming_preserves_existing_session_export(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    transcript = "assistant output\n"
    exported = "---\nconversation_id: conversation_abc\nfork_id: fork_abc\n---\n```chat role=assistant\nok\n```\n"

    class FakeProc:
        def __init__(self):
            self.stdout = io.StringIO(transcript)
            self.stderr = io.StringIO("")
            self.returncode = 0

        def wait(self):
            return 0

    monkeypatch.setattr(harness.subprocess, "Popen", lambda *a, **k: FakeProc())
    out_path = tmp_path / "session.md"
    out_path.write_text(exported)
    last = harness._run_super_streaming(["super"], out_path, cwd=".")
    assert last == ""
    assert out_path.read_text() == exported
    _ = capsys.readouterr().err


def test_recover_session_file_reconstructs_patch_only_head_without_super_recover(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "t-patch"
    conversation_dir = run_dir / ".ai-supervisor" / "conversations" / "conversation_abc"
    forks_dir = conversation_dir / "forks"
    session_dir = tmp_path / ".ctxs" / "t-patch"
    session_file = session_dir / "session.md"
    forks_dir.mkdir(parents=True, exist_ok=True)
    session_dir.mkdir(parents=True, exist_ok=True)

    stale_text = "---\nconversation_id: conversation_abc\nfork_id: fork_old\n---\n```chat role=assistant\nstale\n```\n"
    session_file.write_text(stale_text)
    (conversation_dir / "index.json").write_text(
        json.dumps({"headId": "fork_patch", "headIds": ["fork_patch"]}) + "\n"
    )

    parent_text = (
        "---\nconversation_id: conversation_abc\nfork_id: fork_old\n---\n"
        "```chat role=assistant\nfresh\n```\n"
    )
    (forks_dir / "fork_old.json").write_text(
        json.dumps({"id": "fork_old", "storage": "snapshot", "documentText": parent_text}) + "\n"
    )
    (forks_dir / "fork_patch.json").write_text(
        json.dumps(
            {
                "id": "fork_patch",
                "storage": "patch",
                "parentId": "fork_old",
                "patch": {
                    "ops": [
                        {
                            "op": "equal",
                            "lines": parent_text.splitlines(),
                        }
                    ]
                },
            }
        ) + "\n"
    )

    run_super_calls: list[list[str]] = []

    runtime = SimpleNamespace(
        session_file=session_file,
        run_dir=run_dir,
        session_dir=session_dir,
        active_actual_conversation_id=None,
        super_env={},
        deps=SimpleNamespace(run_super=lambda args, **kwargs: run_super_calls.append(args)),
        log=lambda _msg: None,
    )
    runtime.session_frontmatter = lambda: harness_runtime_session.session_frontmatter_impl(runtime)
    runtime.discover_workspace_conversation_id = (
        lambda: harness_runtime_session.discover_workspace_conversation_id_impl(runtime)
    )

    harness_runtime_session.recover_session_file_from_workspace_impl(
        runtime,
        reason="unit-test-patch",
        force=False,
    )

    assert run_super_calls == []
    assert session_file.read_text() == parent_text
