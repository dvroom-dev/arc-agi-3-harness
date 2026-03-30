from __future__ import annotations

import shutil
from pathlib import Path

from common import instance_root, load_runtime_meta, read_json_stdin, write_json_stdout


def main() -> None:
    payload = read_json_stdin()
    workspace_root = str(payload["workspaceRoot"])
    load_runtime_meta(workspace_root)
    instance = payload.get("instance") if isinstance(payload.get("instance"), dict) else {}
    instance_root_path = Path(str(instance.get("metadata", {}).get("instance_root", ""))).expanduser()
    if not str(instance_root_path).strip() or str(instance_root_path) == ".":
        fallback_id = str(payload.get("instanceId") or payload.get("attemptId") or "").strip()
        if fallback_id:
            instance_root_path = instance_root(workspace_root, fallback_id)
    if str(instance_root_path).strip() and str(instance_root_path) != "." and instance_root_path.exists():
        shutil.rmtree(instance_root_path, ignore_errors=True)
    write_json_stdout({"ok": True})


if __name__ == "__main__":
    main()
