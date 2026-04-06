from __future__ import annotations

from pathlib import Path

from bundles import materialize_evidence_bundle, visible_action_surface_summary
from common import (
    instance_root,
    load_runtime_meta,
    read_json_stdin,
    summarize_instance_state,
    write_json_stdout,
)


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
    surface_summary = visible_action_surface_summary(solver_dir) if solver_dir.exists() else {}
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
    bundle = (
        materialize_evidence_bundle(
            workspace_root,
            attempt_id=str(payload.get("attemptId") or raw_instance_id or ""),
            instance_id=str(raw_instance_id or payload.get("instanceId") or ""),
            solver_dir=solver_dir,
            state_dir=state_dir,
        )
        if solver_dir.exists() and state_dir.exists()
        else None
    )
    if bundle:
        # Keep bundle references out of the evidence payload fingerprint. The runtime
        # receives them as top-level fields and uses them separately for modeler input.
        pass
    write_json_stdout(
        {
            "evidence": [summary],
            "evidence_bundle_id": bundle["bundle_id"] if bundle else None,
            "evidence_bundle_path": bundle["bundle_path"] if bundle else None,
        }
    )


if __name__ == "__main__":
    main()
