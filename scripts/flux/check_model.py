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


def _classify_infrastructure_failure(message: str) -> dict | None:
    text = str(message or "")
    lowered = text.lower()
    if "visible_sequence_surface.py" in text or "preserve_local_sequence_surface" in text:
        return {
            "type": "sequence_surface_race",
            "message": text,
        }
    if "shutil.error" in lowered and "no such file or directory" in lowered:
        return {
            "type": "snapshot_copy_race",
            "message": text,
        }
    if '"type": "missing_sequence"' in text or "sequence not found under:" in text:
        return {
            "type": "missing_sequence_surface",
            "message": text,
        }
    if '"type": "missing_sequences"' in text or "missing sequences dir:" in text:
        return {
            "type": "missing_sequence_surface",
            "message": text,
        }
    return None


def _read_frontier_level(model_workspace: Path) -> int:
    level_meta = model_workspace / "level_current" / "meta.json"
    try:
        payload = json.loads(level_meta.read_text()) if level_meta.exists() else {}
        return int(payload.get("level", 1) or 1)
    except Exception:
        return 1


def _frontier_level_ready(model_workspace: Path, frontier_level: int) -> bool:
    level_dir = model_workspace / f"level_{frontier_level}"
    if not level_dir.exists() or not level_dir.is_dir():
        return False
    required = [
        level_dir / "initial_state.hex",
        level_dir / "initial_state.meta.json",
    ]
    return all(path.exists() for path in required)


def _run_compare(model_workspace: Path, meta: dict, child_env: dict[str, str], frontier_level: int | None = None) -> tuple[int, dict]:
    command = ["python3", "model.py", "compare_sequences", "--game-id", str(meta["game_id"])]
    if frontier_level is not None:
        command.extend(["--level", str(frontier_level)])
    proc = subprocess.run(
        command,
        cwd=str(model_workspace),
        text=True,
        capture_output=True,
        env=child_env,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout)
    payload = json.loads(proc.stdout or "{}")
    if not isinstance(payload, dict):
        raise RuntimeError("compare_sequences returned non-object JSON")
    return proc.returncode, payload


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
    child_env["ARC_MODEL_DISABLE_CANONICAL_ARTIFACTS"] = "1"
    child_env["PATH"] = f"{meta['run_bin_dir']}:{child_env.get('PATH', '')}"
    frontier_level = _read_frontier_level(model_workspace)
    try:
        _default_code, compare_payload = _run_compare(model_workspace, meta, child_env, frontier_level=None)
    except Exception as exc:
        infra = _classify_infrastructure_failure(str(exc))
        write_json_stdout(
            {
                "accepted": False,
                "message": f"compare_sequences failed: {exc}",
                "model_output": model_output,
                "infrastructure_failure": infra,
            }
        )
        return

    compare_level = int(compare_payload.get("level", 1) or 1)
    frontier_compare_payload = None
    frontier_ready = _frontier_level_ready(model_workspace, frontier_level)
    if frontier_level > compare_level and frontier_ready:
        try:
            _frontier_code, frontier_compare_payload = _run_compare(model_workspace, meta, child_env, frontier_level=frontier_level)
        except Exception as exc:
            infra = _classify_infrastructure_failure(str(exc))
            write_json_stdout(
                {
                    "accepted": False,
                    "message": f"frontier compare_sequences failed: {exc}",
                    "model_output": model_output,
                    "compare_payload": compare_payload,
                    "infrastructure_failure": infra,
                }
            )
            return
    elif frontier_level > compare_level and not frontier_ready:
        compare_payload = {
            **compare_payload,
            "frontier_sync_pending": True,
            "frontier_snapshot": {
                "level": frontier_level,
                "level_dir": str(model_workspace / f"level_{frontier_level}"),
                "ready": False,
            },
        }

    compare_for_acceptance = frontier_compare_payload or compare_payload
    error_payload = compare_for_acceptance.get("error") if isinstance(compare_for_acceptance.get("error"), dict) else {}
    error_type = str(error_payload.get("type", "") or "")
    eligible_sequences = int(compare_for_acceptance.get("eligible_sequences", 0) or 0)
    frontier_snapshot = {
        "level": frontier_level,
        "meta_file": str(model_workspace / "level_current" / "meta.json"),
        "current_compare_file": str(model_workspace / "level_current" / "sequence_compare" / "current_compare.json"),
    }

    accepted = bool(compare_for_acceptance.get("all_match"))
    if not accepted and frontier_level > 1 and frontier_compare_payload and error_type == "no_eligible_sequences" and eligible_sequences == 0:
        accepted = True
        compare_for_acceptance = {
            **frontier_compare_payload,
            "frontier_snapshot": frontier_snapshot,
            "frontier_discovery": True,
        }

    summary = str(compare_for_acceptance.get("summary", "") or model_output.get("summary", "")).strip()
    if not summary and accepted and frontier_compare_payload and error_type == "no_eligible_sequences":
        summary = f"frontier level {frontier_level} synced with no eligible sequences yet"
    write_json_stdout(
        {
            "accepted": accepted,
            "message": summary or ("compare_sequences passed" if accepted else "compare_sequences did not pass"),
            "model_output": model_output,
            "compare_payload": compare_for_acceptance,
        }
    )


if __name__ == "__main__":
    main()
