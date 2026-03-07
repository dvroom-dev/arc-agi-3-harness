from __future__ import annotations

import json
import re


def session_frontmatter_impl(runtime) -> dict[str, str]:
    if not runtime.session_file.exists():
        return {}
    try:
        text = runtime.session_file.read_text()
    except Exception:
        return {}
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}

    frontmatter: dict[str, str] = {}
    for line in lines[1:80]:
        if line.strip() == "---":
            break
        match = re.match(r"^\s*([A-Za-z0-9_-]+)\s*:\s*(.+?)\s*$", line)
        if not match:
            continue
        key = match.group(1).strip()
        value = match.group(2).strip().strip("\"'")
        if key and value:
            frontmatter[key] = value
    return frontmatter


def discover_workspace_conversation_id_impl(runtime) -> str | None:
    conversations_dir = runtime.run_dir / ".ai-supervisor" / "conversations"
    if not conversations_dir.exists():
        return None

    candidates = [path for path in conversations_dir.iterdir() if path.is_dir()]
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0].name

    ranked = sorted(
        candidates,
        key=lambda path: (
            (path / "index.json").stat().st_mtime if (path / "index.json").exists() else path.stat().st_mtime
        ),
        reverse=True,
    )
    chosen = ranked[0]
    runtime.log(
        "[harness] multiple workspace conversations found; "
        f"recovering session from newest={chosen.name}"
    )
    return chosen.name


def recover_session_file_from_workspace_impl(
    runtime,
    *,
    reason: str,
    force: bool = False,
) -> None:
    frontmatter = runtime.session_frontmatter()
    if not force and frontmatter.get("conversation_id") and frontmatter.get("fork_id"):
        return

    conversation_id = (
        frontmatter.get("conversation_id")
        or runtime.active_actual_conversation_id
        or runtime.discover_workspace_conversation_id()
    )
    if not conversation_id:
        raise RuntimeError(
            "session.md is missing required frontmatter and no workspace conversation "
            f"was recoverable (reason={reason})"
        )

    runtime.log(
        "[harness] recovering session.md from workspace conversation store: "
        f"reason={reason} conversation={conversation_id}"
    )
    runtime.deps.run_super(
        [
            "recover",
            "--workspace",
            str(runtime.run_dir),
            "--conversation",
            conversation_id,
            "--output",
            str(runtime.session_file),
            "--quiet",
        ],
        stream=False,
        cwd=runtime.run_dir,
        env=runtime.super_env,
    )

    recovered = runtime.session_frontmatter()
    if not recovered.get("conversation_id") or not recovered.get("fork_id"):
        raise RuntimeError(
            "Recovered session.md still missing required frontmatter "
            f"(reason={reason}, path={runtime.session_file})"
        )


def sync_active_conversation_id_from_session_impl(runtime) -> None:
    parsed = runtime.load_conversation_id(runtime.session_file)
    if not parsed:
        return
    alias = runtime.conversation_aliases.get(parsed)
    if alias is None:
        if (
            runtime.active_actual_conversation_id is None
            and runtime.active_conversation_id == "harness_bootstrap"
        ):
            alias = runtime.active_conversation_id
        else:
            alias = parsed
        runtime.conversation_aliases[parsed] = alias
    if parsed != runtime.active_actual_conversation_id:
        runtime.log(
            "[harness] conversation update: "
            f"actual={parsed} repl_session={alias}"
        )
    runtime.active_actual_conversation_id = parsed
    runtime.active_conversation_id = alias


def load_conversation_head_metadata_impl(runtime) -> dict[str, str | int | None] | None:
    conversation_id = (
        runtime.active_actual_conversation_id
        or runtime.load_conversation_id(runtime.session_file)
        or runtime.discover_workspace_conversation_id()
    )
    if not conversation_id:
        return None

    conversation_dir = runtime.run_dir / ".ai-supervisor" / "conversations" / conversation_id
    index_path = conversation_dir / "index.json"
    if not index_path.exists():
        return None

    try:
        index_payload = json.loads(index_path.read_text())
    except Exception:
        return None

    if not isinstance(index_payload, dict):
        return None
    head_id = str(index_payload.get("headId") or "").strip()
    if not head_id:
        return None

    forks = index_payload.get("forks")
    if not isinstance(forks, list):
        forks = []
    head_summary = next(
        (
            fork
            for fork in forks
            if isinstance(fork, dict) and str(fork.get("id") or "").strip() == head_id
        ),
        None,
    )

    fork_path = conversation_dir / "forks" / f"{head_id}.json"
    fork_payload: dict[str, object] = {}
    if fork_path.exists():
        try:
            loaded = json.loads(fork_path.read_text())
            if isinstance(loaded, dict):
                fork_payload = loaded
        except Exception:
            fork_payload = {}

    summary = head_summary if isinstance(head_summary, dict) else {}
    return {
        "conversation_id": conversation_id,
        "head_id": head_id,
        "doc_hash": str(summary.get("docHash") or fork_payload.get("docHash") or "").strip() or None,
        "provider_thread_id": str(
            summary.get("providerThreadId") or fork_payload.get("providerThreadId") or ""
        ).strip()
        or None,
        "supervisor_thread_id": str(
            summary.get("supervisorThreadId") or fork_payload.get("supervisorThreadId") or ""
        ).strip()
        or None,
        "fork_count": len(forks),
    }
