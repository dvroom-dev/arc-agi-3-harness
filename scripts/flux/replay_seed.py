from __future__ import annotations
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from attempt_snapshot import materialize_attempt_snapshot
from common import (
    load_runtime_meta,
    read_json_stdin,
    summarize_instance_state,
    sync_evidence_bundle_to_model_workspace,
    write_json_stdout,
)
from evidence_bundle import materialize_evidence_bundle_from_snapshot


def _run_shell(cmd: list[str], cwd: Path, env: dict[str, str]) -> dict:
    proc = subprocess.run(cmd, cwd=str(cwd), env=env, text=True, capture_output=True)
    return {
        "tool": "shell",
        "cmd": cmd,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def _write_file(cwd: Path, path_text: str, content: str) -> dict:
    target = (cwd / path_text).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {"tool": "write_file", "path": str(target), "bytes": len(content.encode("utf-8"))}


def _read_file(cwd: Path, path_text: str) -> dict:
    target = (cwd / path_text).resolve()
    return {"tool": "read_file", "path": str(target), "content": target.read_text(encoding="utf-8")}


def main() -> None:
    payload = read_json_stdin()
    workspace_root = str(payload["workspaceRoot"])
    meta = load_runtime_meta(workspace_root)
    seed_bundle = payload.get("seedBundle") if isinstance(payload.get("seedBundle"), dict) else {}
    instance = payload.get("instance") if isinstance(payload.get("instance"), dict) else {}
    working_directory = Path(str(instance.get("working_directory", "")))
    env = instance.get("env") if isinstance(instance.get("env"), dict) else {}
    results: list[dict] = []
    for step in seed_bundle.get("replayPlan", []):
        if not isinstance(step, dict):
            continue
        tool = str(step.get("tool", "")).strip()
        args = step.get("args") if isinstance(step.get("args"), dict) else {}
        if tool == "shell":
            cmd = args.get("cmd")
            if isinstance(cmd, list) and all(isinstance(item, str) for item in cmd):
                results.append(_run_shell(list(cmd), working_directory, env))
        elif tool == "write_file":
            results.append(_write_file(working_directory, str(args.get("path", "")), str(args.get("content", ""))))
        elif tool == "read_file":
            results.append(_read_file(working_directory, str(args.get("path", ""))))
    state_dir = Path(str(instance.get("metadata", {}).get("state_dir", "")))
    bundle = None
    synced: list[str] = []
    if working_directory.exists() and state_dir.exists():
        snapshot = materialize_attempt_snapshot(
            workspace_root,
            attempt_id=str(payload.get("attemptId") or instance.get("instance_id") or ""),
            instance_id=str(instance.get("instance_id") or payload.get("instanceId") or ""),
            solver_dir=working_directory,
            state_dir=state_dir,
            workspace_dir_name=working_directory.name,
            state_summary=summarize_instance_state(state_dir),
        )
        bundle = materialize_evidence_bundle_from_snapshot(
            workspace_root,
            snapshot_manifest=snapshot,
        )
        synced = sync_evidence_bundle_to_model_workspace(meta, Path(str(bundle["bundle_path"])))
    evidence = [summarize_instance_state(state_dir)] if state_dir.exists() else []
    if evidence:
        evidence[0]["synced_artifacts"] = synced
        if bundle:
            evidence[0]["bundle_completeness"] = bundle["bundle_completeness"]
    write_json_stdout({
        "replay_ok": True,
        "tool_results": results,
        "evidence": evidence,
        "evidence_bundle_id": bundle["bundle_id"] if bundle else None,
        "evidence_bundle_path": bundle["bundle_path"] if bundle else None,
    })


if __name__ == "__main__":
    main()
