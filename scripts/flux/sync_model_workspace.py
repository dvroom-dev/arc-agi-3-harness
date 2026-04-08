from __future__ import annotations

from pathlib import Path

from common import (
    load_runtime_meta,
    read_json_stdin,
    sync_evidence_bundle_to_model_workspace,
    sync_latest_attempt_to_model_workspace,
    write_json_stdout,
)


def main() -> None:
    payload = read_json_stdin()
    workspace_root = str(payload.get("workspaceRoot", ""))
    evidence_bundle_path = str(payload.get("evidenceBundlePath") or "").strip()
    meta = load_runtime_meta(workspace_root)
    if evidence_bundle_path:
        synced = sync_evidence_bundle_to_model_workspace(meta, Path(evidence_bundle_path))
    else:
        synced = sync_latest_attempt_to_model_workspace(workspace_root, meta)
    write_json_stdout({"synced": synced, "count": len(synced)})


if __name__ == "__main__":
    main()
