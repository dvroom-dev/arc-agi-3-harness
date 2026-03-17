from pathlib import Path

import harness


def test_sync_live_stream_conversation_artifacts_replaces_stale_temp_tree(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    session_dir = tmp_path / ".ctxs" / "t-run"
    output_path = session_dir / "session.md"
    conversation_dir = run_dir / ".ai-supervisor" / "conversations" / "conversation_abc"
    forks_dir = conversation_dir / "forks"
    forks_dir.mkdir(parents=True, exist_ok=True)
    session_dir.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "---\nconversation_id: conversation_abc\nfork_id: fork_a\n---\n"
    )
    (conversation_dir / "index.json").write_text('{"headId":"fork_a"}\n')
    (forks_dir / "fork_a.json").write_text('{"id":"fork_a"}\n')

    stale_temp = session_dir / ".forks.tmp" / "nested"
    stale_temp.mkdir(parents=True, exist_ok=True)
    (stale_temp / "stale.json").write_text('{"stale":true}\n')

    harness._sync_live_stream_conversation_artifacts(output_path, str(run_dir))

    exported_root = session_dir / "forks"
    assert exported_root.exists()
    assert not (session_dir / ".forks.tmp").exists()
    assert (exported_root / "fork_a.json").is_symlink()
    assert (exported_root / "fork_a.json").read_text() == '{"id":"fork_a"}\n'
