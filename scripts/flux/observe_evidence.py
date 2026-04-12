from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from attempt_snapshot import materialize_attempt_snapshot
from bundles import preferred_solver_surface_dir, visible_action_surface_summary
from common import (
    instance_root,
    load_runtime_meta,
    read_json_stdin,
    summarize_instance_state,
    write_json_stdout,
)
from evidence_bundle import materialize_evidence_bundle_from_snapshot


def main() -> None:
    payload = read_json_stdin()
    workspace_root = str(payload["workspaceRoot"])
    meta = load_runtime_meta(workspace_root)
    instance = payload.get("instance") if isinstance(payload.get("instance"), dict) else {}
    metadata = instance.get("metadata", {}) if isinstance(instance.get("metadata"), dict) else {}
    raw_instance_id = str(payload.get("instanceId") or payload.get("attemptId") or instance.get("instance_id") or "")
    state_dir = Path(str(metadata.get("state_dir", "")))
    solver_dir = Path(str(metadata.get("solver_dir", "")))
    if not state_dir.exists() or not solver_dir.exists():
        if raw_instance_id:
            root = instance_root(workspace_root, raw_instance_id)
            fallback_state_dir = root / "supervisor" / "arc"
            fallback_solver_dir = root / "agent" / Path(str(meta["solver_template_dir"])).name
            if not state_dir.exists():
                state_dir = fallback_state_dir
            if not solver_dir.exists():
                solver_dir = fallback_solver_dir
    summary = summarize_instance_state(state_dir) if state_dir.exists() else {"summary": "missing state dir"}
    surface_dir = preferred_solver_surface_dir(solver_dir=solver_dir, state_dir=state_dir) if solver_dir.exists() and state_dir.exists() else solver_dir
    surface_summary = visible_action_surface_summary(surface_dir) if surface_dir.exists() else {}
    summary.update(surface_summary)
    reported_actions = int(summary.get("action_count", 0) or 0)
    visible_actions = int(surface_summary.get("visible_action_count", 0) or 0)
    handoff_incomplete = reported_actions > max(0, visible_actions)
    if handoff_incomplete:
        summary["artifact_handoff_incomplete"] = {
            "reported_action_count": reported_actions,
            "visible_action_count": visible_actions,
            "latest_visible_action_dir": surface_summary.get("latest_visible_action_dir"),
        }
    snapshot = (
        materialize_attempt_snapshot(
            workspace_root,
            attempt_id=str(payload.get("attemptId") or raw_instance_id or ""),
            instance_id=str(raw_instance_id or payload.get("instanceId") or ""),
            solver_dir=surface_dir,
            state_dir=state_dir,
            extra_copy_paths=[
                (solver_dir / "solver_handoff", "solver_handoff"),
            ],
            workspace_dir_name=solver_dir.name,
            state_summary=summary,
        )
        if surface_dir.exists() and state_dir.exists()
        else None
    )
    bundle = (
        materialize_evidence_bundle_from_snapshot(
            workspace_root,
            snapshot_manifest=snapshot,
        )
        if snapshot
        else None
    )
    if bundle:
        summary["bundle_completeness"] = bundle["bundle_completeness"]
        summary["frontier_level"] = bundle["bundle_completeness"]["frontier_level"]
    write_json_stdout(
        {
            "evidence": [summary],
            "attempt_snapshot_id": snapshot["snapshot_id"] if snapshot else None,
            "attempt_snapshot_path": snapshot["snapshot_path"] if snapshot else None,
            "evidence_bundle_id": bundle["bundle_id"] if bundle else None,
            "evidence_bundle_path": bundle["bundle_path"] if bundle else None,
            "bundle_completeness": bundle["bundle_completeness"] if bundle else None,
        }
    )


if __name__ == "__main__":
    main()
