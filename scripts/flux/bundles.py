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


def visible_action_surface_summary(solver_dir: Path) -> dict:
    max_action_index = 0
    latest_action_dir = None
    sequence_files = 0
    for level_dir in sorted(solver_dir.glob("level_*")):
        if not level_dir.is_dir():
            continue
        sequence_root = level_dir / "sequences"
        if not sequence_root.exists():
            continue
        for sequence_path in sorted(sequence_root.glob("seq_*.json")):
            sequence_files += 1
            try:
                payload = json.loads(sequence_path.read_text())
            except Exception:
                continue
            actions = payload.get("actions") if isinstance(payload.get("actions"), list) else []
            for action in actions:
                if not isinstance(action, dict):
                    continue
                try:
                    action_index = int(action.get("action_index", 0) or 0)
                except Exception:
                    action_index = 0
                if action_index <= max_action_index:
                    continue
                max_action_index = action_index
                files = action.get("files") if isinstance(action.get("files"), dict) else {}
                meta_rel = files.get("meta_json")
                latest_action_dir = str((level_dir / str(meta_rel)).parent) if isinstance(meta_rel, str) else str(level_dir)
    return {
        "visible_action_count": max_action_index,
        "visible_sequence_files": sequence_files,
        "latest_visible_action_dir": latest_action_dir,
    }


def materialize_evidence_bundle(
    workspace_root: str,
    *,
    attempt_id: str,
    instance_id: str,
    solver_dir: Path,
    state_dir: Path,
) -> dict:
    bundle_id = f"evidence_{uuid.uuid4()}"
    final_root = evidence_bundle_root(workspace_root, bundle_id)
    temp_root = final_root.parent / f".{bundle_id}.tmp-{uuid.uuid4().hex}"
    shutil.rmtree(temp_root, ignore_errors=True)
    (temp_root / "workspace").mkdir(parents=True, exist_ok=True)
    with workspace_tree_lock(solver_dir):
        copytree_stable(solver_dir, temp_root / "workspace" / solver_dir.name)
    if state_dir.exists():
        copytree_stable(state_dir, temp_root / "arc_state")
    manifest = {
        "bundle_id": bundle_id,
        "attempt_id": attempt_id,
        "instance_id": instance_id,
        "created_at": time.time(),
        "solver_dir_name": solver_dir.name,
        "workspace_dir": str(temp_root / "workspace" / solver_dir.name),
        "arc_state_dir": str(temp_root / "arc_state"),
    }
    (temp_root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    final_root.parent.mkdir(parents=True, exist_ok=True)
    temp_root.rename(final_root)
    manifest["workspace_dir"] = str(final_root / "workspace" / solver_dir.name)
    manifest["arc_state_dir"] = str(final_root / "arc_state")
    manifest["manifest_path"] = str(final_root / "manifest.json")
    manifest["bundle_path"] = str(final_root)
    return manifest
