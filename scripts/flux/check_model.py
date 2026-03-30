from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from common import (
    load_runtime_meta,
    read_json_stdin,
    sync_latest_attempt_to_model_workspace,
    write_json_stdout,
)


def main() -> None:
    payload = read_json_stdin()
    model_output = payload.get("modelOutput") if isinstance(payload.get("modelOutput"), dict) else {}
    workspace_root = str(payload.get("workspaceRoot", ""))
    meta = load_runtime_meta(workspace_root)
    model_workspace = Path(str(meta["model_workspace_dir"]))
    sync_latest_attempt_to_model_workspace(workspace_root, meta)
    model_script = model_workspace / "model.py"
    if not model_script.exists():
        write_json_stdout(
            {
                "accepted": False,
                "message": f"missing model.py in durable workspace: {model_workspace}",
                "model_output": model_output,
            }
        )
        return
    child_env = dict(os.environ)
    child_env["ARC_CONFIG_DIR"] = str(meta["run_config_dir"])
    child_env["ARC_STATE_DIR"] = str(Path(workspace_root) / "supervisor" / "arc")
    child_env["PATH"] = f"{meta['run_bin_dir']}:{child_env.get('PATH', '')}"
    proc = subprocess.run(
        ["python3", "model.py", "compare_sequences", "--game-id", str(meta["game_id"])],
        cwd=str(model_workspace),
        text=True,
        capture_output=True,
        env=child_env,
    )
    if proc.returncode != 0:
        write_json_stdout(
            {
                "accepted": False,
                "message": f"compare_sequences failed: {proc.stderr or proc.stdout}",
                "model_output": model_output,
            }
        )
        return
    try:
        compare_payload = json.loads(proc.stdout or "{}")
    except Exception as exc:
        write_json_stdout(
            {
                "accepted": False,
                "message": f"compare_sequences returned non-JSON output: {exc}",
                "model_output": model_output,
            }
        )
        return
    accepted = bool(compare_payload.get("all_match"))
    summary = str(compare_payload.get("summary", "") or model_output.get("summary", "")).strip()
    write_json_stdout(
        {
            "accepted": accepted,
            "message": summary or ("compare_sequences passed" if accepted else "compare_sequences did not pass"),
            "model_output": model_output,
            "compare_payload": compare_payload,
        }
    )


if __name__ == "__main__":
    main()
