from __future__ import annotations

import json
import re
import shutil
from pathlib import Path


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


def _load_workspace_head_document(
    runtime,
    *,
    conversation_id: str,
) -> tuple[str, str] | None:
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
    head_id = str(
        index_payload.get("headId")
        or ((index_payload.get("headIds") or [None])[-1] if isinstance(index_payload.get("headIds"), list) else "")
        or ""
    ).strip()
    if not head_id:
        return None
    forks_dir = conversation_dir / "forks"
    document_text = _reconstruct_fork_document(forks_dir, head_id, {})
    if not document_text or not document_text.strip():
        return None
    return head_id, document_text


def _load_super_state_document(
    runtime,
) -> tuple[str, str, str] | None:
    state_path = runtime.run_dir / "super" / "state.json"
    if not state_path.exists():
        return None
    try:
        state_payload = json.loads(state_path.read_text())
    except Exception:
        return None
    if not isinstance(state_payload, dict):
        return None
    conversation_id = str(state_payload.get("conversationId") or "").strip()
    fork_id = str(state_payload.get("activeForkId") or "").strip()
    if not conversation_id or not fork_id:
        return None
    forks_dir = runtime.run_dir / ".ai-supervisor" / "conversations" / conversation_id / "forks"
    document_text = _reconstruct_fork_document(forks_dir, fork_id, {})
    if not document_text or not document_text.strip():
        return None
    return conversation_id, fork_id, document_text


def _load_fork_payload(forks_dir: Path, fork_id: str) -> dict | None:
    fork_path = forks_dir / f"{fork_id}.json"
    if not fork_path.exists():
        return None
    try:
        fork_payload = json.loads(fork_path.read_text())
    except Exception:
        return None
    return fork_payload if isinstance(fork_payload, dict) else None


def _apply_fork_patch(base_text: str, patch_payload: dict) -> str | None:
    patch = patch_payload.get("patch")
    if not isinstance(patch, dict):
        return None
    ops = patch.get("ops")
    if not isinstance(ops, list):
        return None

    base_lines = base_text.splitlines()
    rebuilt_lines: list[str] = []
    cursor = 0
    for op in ops:
        if not isinstance(op, dict):
            return None
        kind = str(op.get("op") or "").strip()
        lines = op.get("lines")
        if not isinstance(lines, list) or any(not isinstance(line, str) for line in lines):
            return None
        if kind == "equal":
            expected = base_lines[cursor : cursor + len(lines)]
            if expected != lines:
                return None
            rebuilt_lines.extend(lines)
            cursor += len(lines)
        elif kind == "insert":
            rebuilt_lines.extend(lines)
        elif kind == "delete":
            expected = base_lines[cursor : cursor + len(lines)]
            if expected != lines:
                return None
            cursor += len(lines)
        else:
            return None

    if cursor != len(base_lines):
        rebuilt_lines.extend(base_lines[cursor:])
    return "\n".join(rebuilt_lines) + ("\n" if base_text.endswith("\n") else "")


def _reconstruct_fork_document(
    forks_dir: Path,
    fork_id: str,
    memo: dict[str, str | None],
) -> str | None:
    if fork_id in memo:
        return memo[fork_id]

    fork_payload = _load_fork_payload(forks_dir, fork_id)
    if not fork_payload:
        memo[fork_id] = None
        return None

    document_text = str(fork_payload.get("documentText") or "")
    if document_text.strip():
        memo[fork_id] = document_text
        return document_text

    parent_id = str(fork_payload.get("parentId") or "").strip()
    if not parent_id:
        memo[fork_id] = None
        return None

    parent_text = _reconstruct_fork_document(forks_dir, parent_id, memo)
    if parent_text is None:
        memo[fork_id] = None
        return None

    patched_text = _apply_fork_patch(parent_text, fork_payload)
    memo[fork_id] = patched_text
    return patched_text


def _normalize_session_file_to_workspace_head(
    runtime,
    *,
    conversation_id: str,
    reason: str,
) -> bool:
    head_document = _load_workspace_head_document(runtime, conversation_id=conversation_id)
    if not head_document:
        return False
    head_id, document_text = head_document
    current_text = ""
    if runtime.session_file.exists():
        try:
            current_text = runtime.session_file.read_text()
        except Exception:
            current_text = ""
    if current_text == document_text:
        return False
    runtime.session_file.parent.mkdir(parents=True, exist_ok=True)
    runtime.session_file.write_text(document_text)
    runtime.log(
        "[harness] normalized session.md to workspace head: "
        f"reason={reason} conversation={conversation_id} fork={head_id}"
    )
    return True


def recover_session_file_from_workspace_impl(
    runtime,
    *,
    reason: str,
    force: bool = False,
) -> None:
    frontmatter = runtime.session_frontmatter()
    super_state_document = _load_super_state_document(runtime)
    if super_state_document:
        conversation_id, fork_id, document_text = super_state_document
        current_text = ""
        if runtime.session_file.exists():
            try:
                current_text = runtime.session_file.read_text()
            except Exception:
                current_text = ""
        if current_text != document_text:
            runtime.session_file.parent.mkdir(parents=True, exist_ok=True)
            runtime.session_file.write_text(document_text)
            runtime.log(
                "[harness] exported session.md from super state: "
                f"reason={reason} conversation={conversation_id} fork={fork_id}"
            )
        export_workspace_conversation_artifacts_impl(
            runtime,
            conversation_id=conversation_id,
            reason=reason,
        )
        return

    conversation_id = (
        frontmatter.get("conversation_id")
        or runtime.active_actual_conversation_id
        or runtime.discover_workspace_conversation_id()
    )
    if conversation_id and not force and frontmatter.get("conversation_id") and frontmatter.get("fork_id"):
        normalized = _normalize_session_file_to_workspace_head(
            runtime,
            conversation_id=conversation_id,
            reason=reason,
        )
        if normalized:
            export_workspace_conversation_artifacts_impl(
                runtime,
                conversation_id=conversation_id,
                reason=reason,
            )
            return

    if not conversation_id:
        raise RuntimeError(
            "session.md is missing required frontmatter and no workspace conversation "
            f"was recoverable (reason={reason})"
        )

    normalized = _normalize_session_file_to_workspace_head(
        runtime,
        conversation_id=conversation_id,
        reason=reason,
    )
    if not normalized and not runtime.session_file.exists():
        raise RuntimeError(
            "Unable to export session.md from workspace conversation store "
            f"(reason={reason}, conversation={conversation_id})"
        )
    recovered = runtime.session_frontmatter()
    if not recovered.get("conversation_id") or not recovered.get("fork_id"):
        raise RuntimeError(
            "Exported session.md still missing required frontmatter "
            f"(reason={reason}, path={runtime.session_file})"
        )
    export_workspace_conversation_artifacts_impl(
        runtime,
        conversation_id=conversation_id,
        reason=reason,
    )


def _remove_path(path: Path) -> None:
    if not path.exists() and not path.is_symlink():
        return
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
        return
    shutil.rmtree(path, ignore_errors=True)


def _ensure_symlink(link_path: Path, target_path: Path) -> None:
    if link_path.is_symlink():
        try:
            if link_path.resolve() == target_path.resolve():
                return
        except Exception:
            pass
    _remove_path(link_path)
    link_path.symlink_to(target_path)


def sync_live_workspace_conversation_artifacts_impl(
    runtime,
    *,
    conversation_id: str | None = None,
) -> None:
    resolved_conversation_id = (
        str(conversation_id or "").strip()
        or runtime.active_actual_conversation_id
        or runtime.discover_workspace_conversation_id()
    )
    if not resolved_conversation_id:
        return

    source_dir = runtime.run_dir / ".ai-supervisor" / "conversations" / resolved_conversation_id
    forks_src = source_dir / "forks"
    if not source_dir.exists() or not forks_src.exists():
        return

    export_root = runtime.session_dir / "forks"
    temp_root = runtime.session_dir / ".forks.tmp"
    _remove_path(temp_root)
    temp_root.mkdir(parents=True, exist_ok=True)

    index_src = source_dir / "index.json"
    if index_src.exists():
        _ensure_symlink(temp_root / "index.json", index_src)
    for fork_path in sorted(forks_src.glob("*.json")):
        _ensure_symlink(temp_root / fork_path.name, fork_path)

    _remove_path(export_root)
    temp_root.rename(export_root)


def export_workspace_conversation_artifacts_impl(
    runtime,
    *,
    conversation_id: str | None = None,
    reason: str,
) -> None:
    resolved_conversation_id = (
        str(conversation_id or "").strip()
        or runtime.active_actual_conversation_id
        or runtime.discover_workspace_conversation_id()
    )
    if not resolved_conversation_id:
        return

    source_dir = runtime.run_dir / ".ai-supervisor" / "conversations" / resolved_conversation_id
    if not source_dir.exists():
        runtime.log(
            "[harness] conversation artifact export skipped: "
            f"missing source conversation dir for {resolved_conversation_id}"
        )
        return

    sync_live_workspace_conversation_artifacts_impl(
        runtime,
        conversation_id=resolved_conversation_id,
    )
    forks_src = source_dir / "forks"
    exported = len(list(sorted(forks_src.glob("*.json")))) if forks_src.exists() else 0
    runtime.log(
        "[harness] exported conversation artifacts: "
        f"reason={reason} conversation={resolved_conversation_id} forks={exported}"
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
    sync_live_workspace_conversation_artifacts_impl(runtime, conversation_id=parsed)


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
        "parent_id": str(summary.get("parentId") or fork_payload.get("parentId") or "").strip() or None,
        "action_summary": str(summary.get("actionSummary") or fork_payload.get("actionSummary") or "").strip() or None,
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
