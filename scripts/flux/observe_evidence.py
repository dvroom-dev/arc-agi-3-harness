from __future__ import annotations

from pathlib import Path

from common import (
    instance_root,
    load_runtime_meta,
    read_json_stdin,
    summarize_instance_state,
    sync_solver_artifacts_to_model_workspace,
    write_json_stdout,
)


def main() -> None:
    payload = read_json_stdin()
    workspace_root = str(payload["workspaceRoot"])
    meta = load_runtime_meta(workspace_root)
    instance = payload.get("instance") if isinstance(payload.get("instance"), dict) else {}
    metadata = instance.get("metadata", {}) if isinstance(instance.get("metadata"), dict) else {}
    state_dir = Path(str(metadata.get("state_dir", "")))
    solver_dir = Path(str(metadata.get("solver_dir", "")))
    if not state_dir.exists() or not solver_dir.exists():
        raw_instance_id = str(payload.get("instanceId") or payload.get("attemptId") or instance.get("instance_id") or "")
        if raw_instance_id:
            root = instance_root(workspace_root, raw_instance_id)
            fallback_state_dir = root / "supervisor" / "arc"
            fallback_solver_dir = root / "agent" / Path(str(meta["solver_template_dir"])).name
            if not state_dir.exists():
                state_dir = fallback_state_dir
            if not solver_dir.exists():
                solver_dir = fallback_solver_dir
    synced = (
        sync_solver_artifacts_to_model_workspace(meta, solver_dir, state_dir=state_dir)
        if solver_dir.exists()
        else []
    )
    summary = summarize_instance_state(state_dir) if state_dir.exists() else {"summary": "missing state dir"}
    summary["synced_artifacts"] = synced
    write_json_stdout({"evidence": [summary]})


if __name__ == "__main__":
    main()
