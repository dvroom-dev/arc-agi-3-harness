from __future__ import annotations

from pathlib import Path

from common import (
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
    state_dir = Path(str(instance.get("metadata", {}).get("state_dir", "")))
    solver_dir = Path(str(instance.get("metadata", {}).get("solver_dir", "")))
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
