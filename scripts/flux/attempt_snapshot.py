from __future__ import annotations

import json
import shutil
import sys
import time
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from arc_model_runtime.io_utils import copytree_stable, workspace_tree_lock


def safe_instance_name(value: str) -> str:
    out = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in str(value))
    return out.strip("._") or "instance"


def attempt_snapshot_root(workspace_root: str, snapshot_id: str) -> Path:
    return Path(workspace_root) / "flux" / "attempt_snapshots" / safe_instance_name(snapshot_id)


def materialize_attempt_snapshot(
    workspace_root: str,
    *,
    attempt_id: str,
    instance_id: str,
    solver_dir: Path,
    state_dir: Path,
    extra_copy_paths: list[tuple[Path, str]] | None = None,
    workspace_dir_name: str | None = None,
    state_summary: dict | None = None,
) -> dict:
    snapshot_id = f"attempt_snapshot_{uuid.uuid4()}"
    final_root = attempt_snapshot_root(workspace_root, snapshot_id)
    temp_root = final_root.parent / f".{snapshot_id}.tmp-{uuid.uuid4().hex}"
    shutil.rmtree(temp_root, ignore_errors=True)
    (temp_root / "workspace").mkdir(parents=True, exist_ok=True)
    workspace_leaf = workspace_dir_name or solver_dir.name
    with workspace_tree_lock(solver_dir):
        copytree_stable(solver_dir, temp_root / "workspace" / workspace_leaf)
        for source_path, relative_path in extra_copy_paths or []:
            if not source_path.exists():
                continue
            destination = temp_root / "workspace" / workspace_leaf / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            if source_path.is_dir():
                copytree_stable(source_path, destination)
            else:
                shutil.copy2(source_path, destination)
    if state_dir.exists():
        copytree_stable(state_dir, temp_root / "arc_state")
    manifest = {
        "snapshot_id": snapshot_id,
        "attempt_id": attempt_id,
        "instance_id": instance_id,
        "created_at": time.time(),
        "solver_dir_name": workspace_leaf,
        "workspace_dir": str(temp_root / "workspace" / workspace_leaf),
        "arc_state_dir": str(temp_root / "arc_state"),
        "state_summary": state_summary or {},
    }
    (temp_root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    final_root.parent.mkdir(parents=True, exist_ok=True)
    temp_root.rename(final_root)
    manifest["workspace_dir"] = str(final_root / "workspace" / workspace_leaf)
    manifest["arc_state_dir"] = str(final_root / "arc_state")
    manifest["manifest_path"] = str(final_root / "manifest.json")
    manifest["snapshot_path"] = str(final_root)
    (final_root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest
