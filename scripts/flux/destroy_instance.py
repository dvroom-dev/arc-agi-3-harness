from __future__ import annotations

import shutil
from pathlib import Path

from common import load_runtime_meta, read_json_stdin, write_json_stdout


def main() -> None:
    payload = read_json_stdin()
    workspace_root = str(payload["workspaceRoot"])
    load_runtime_meta(workspace_root)
    instance = payload.get("instance") if isinstance(payload.get("instance"), dict) else {}
    instance_root = Path(str(instance.get("metadata", {}).get("instance_root", "")))
    if instance_root.exists():
        shutil.rmtree(instance_root, ignore_errors=True)
    write_json_stdout({"ok": True})


if __name__ == "__main__":
    main()
