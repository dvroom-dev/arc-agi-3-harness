from __future__ import annotations

import json
import subprocess
from pathlib import Path

from common import load_runtime_meta, read_json_stdin, write_json_stdout


def main() -> None:
    payload = read_json_stdin()
    model_output = payload.get("modelOutput") if isinstance(payload.get("modelOutput"), dict) else {}
    workspace_root = str(payload.get("workspaceRoot", ""))
    meta = load_runtime_meta(workspace_root)
    model_workspace = Path(str(meta["model_workspace_dir"]))
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
    proc = subprocess.run(
        ["python3", "model.py", "compare_sequences", "--game-id", str(meta["game_id"])],
        cwd=str(model_workspace),
        text=True,
        capture_output=True,
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
