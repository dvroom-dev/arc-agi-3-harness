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


def evidence_bundle_root(workspace_root: str, bundle_id: str) -> Path:
    return Path(workspace_root) / "flux" / "evidence_bundles" / safe_instance_name(bundle_id)


def _frontier_level(workspace_dir: Path) -> int:
    level_current_meta = workspace_dir / "level_current" / "meta.json"
    if level_current_meta.exists():
        try:
            payload = json.loads(level_current_meta.read_text())
            return int(payload.get("level", 1) or 1)
        except Exception:
            return 1
    visible_levels = []
    for level_dir in sorted(workspace_dir.glob("level_*")):
        if not level_dir.is_dir() or level_dir.name == "level_current":
            continue
        try:
            visible_levels.append(int(level_dir.name.split("_", 1)[1]))
        except Exception:
            continue
    return max(visible_levels, default=1)


def bundle_completeness(workspace_dir: Path) -> dict:
    frontier_level = _frontier_level(workspace_dir)
    level_dirs = [path for path in workspace_dir.glob("level_*") if path.is_dir() and path.name != "level_current"]
    has_level_sequences = any((level_dir / "sequences").exists() and any((level_dir / "sequences").glob("seq_*.json")) for level_dir in level_dirs)
    frontier_dir = workspace_dir / f"level_{frontier_level}"
    has_frontier_initial_state = frontier_dir.exists() and (frontier_dir / "initial_state.hex").exists() and (frontier_dir / "initial_state.meta.json").exists()
    has_frontier_sequences = frontier_dir.exists() and (frontier_dir / "sequences").exists() and any((frontier_dir / "sequences").glob("seq_*.json"))
    has_compare_surface = has_level_sequences and has_frontier_initial_state
    status = "ready_for_compare" if has_compare_surface else "incomplete_artifacts"
    return {
        "frontier_level": frontier_level,
        "has_level_sequences": has_level_sequences,
        "has_frontier_initial_state": has_frontier_initial_state,
        "has_frontier_sequences": has_frontier_sequences,
        "has_compare_surface": has_compare_surface,
        "status": status,
    }


def materialize_evidence_bundle_from_snapshot(workspace_root: str, *, snapshot_manifest: dict) -> dict:
    bundle_id = f"evidence_{uuid.uuid4()}"
    final_root = evidence_bundle_root(workspace_root, bundle_id)
    temp_root = final_root.parent / f".{bundle_id}.tmp-{uuid.uuid4().hex}"
    shutil.rmtree(temp_root, ignore_errors=True)

    snapshot_workspace = Path(str(snapshot_manifest["workspace_dir"]))
    snapshot_state = Path(str(snapshot_manifest["arc_state_dir"]))
    workspace_leaf = Path(str(snapshot_manifest.get("solver_dir_name") or snapshot_workspace.name)).name
    (temp_root / "workspace").mkdir(parents=True, exist_ok=True)
    with workspace_tree_lock(snapshot_workspace):
        copytree_stable(snapshot_workspace, temp_root / "workspace" / workspace_leaf)
    if snapshot_state.exists():
        copytree_stable(snapshot_state, temp_root / "arc_state")

    completeness = bundle_completeness(temp_root / "workspace" / workspace_leaf)
    manifest = {
        "bundle_id": bundle_id,
        "attempt_snapshot_id": snapshot_manifest["snapshot_id"],
        "attempt_id": snapshot_manifest.get("attempt_id"),
        "instance_id": snapshot_manifest.get("instance_id"),
        "created_at": time.time(),
        "solver_dir_name": workspace_leaf,
        "workspace_dir": str(temp_root / "workspace" / workspace_leaf),
        "arc_state_dir": str(temp_root / "arc_state"),
        "bundle_completeness": completeness,
    }
    (temp_root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    final_root.parent.mkdir(parents=True, exist_ok=True)
    temp_root.rename(final_root)
    manifest["workspace_dir"] = str(final_root / "workspace" / workspace_leaf)
    manifest["arc_state_dir"] = str(final_root / "arc_state")
    manifest["manifest_path"] = str(final_root / "manifest.json")
    manifest["bundle_path"] = str(final_root)
    (final_root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest
