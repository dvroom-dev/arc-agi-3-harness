from __future__ import annotations

from pathlib import Path

from common import (
    load_runtime_meta,
    read_json_stdin,
    sync_evidence_bundle_to_model_workspace,
    write_json_stdout,
)


def main() -> None:
    payload = read_json_stdin()
    workspace_root = str(payload.get("workspaceRoot", ""))
    evidence_bundle_path = str(payload.get("evidenceBundlePath") or "").strip()
    target_workspace_dir = str(payload.get("targetWorkspaceDir") or "").strip()
    if not evidence_bundle_path:
        raise RuntimeError("sync_model_workspace.py now requires evidenceBundlePath")
    meta = load_runtime_meta(workspace_root)
    synced = sync_evidence_bundle_to_model_workspace(
        meta,
        Path(evidence_bundle_path),
        target_workspace=Path(target_workspace_dir) if target_workspace_dir else None,
    )
    write_json_stdout({"synced": synced, "count": len(synced)})


if __name__ == "__main__":
    main()
