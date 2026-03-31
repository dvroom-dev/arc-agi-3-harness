from __future__ import annotations

from common import load_runtime_meta, read_json_stdin, sync_latest_attempt_to_model_workspace, write_json_stdout


def main() -> None:
    payload = read_json_stdin()
    workspace_root = str(payload.get("workspaceRoot", ""))
    meta = load_runtime_meta(workspace_root)
    synced = sync_latest_attempt_to_model_workspace(workspace_root, meta)
    write_json_stdout({"synced": synced, "count": len(synced)})


if __name__ == "__main__":
    main()
