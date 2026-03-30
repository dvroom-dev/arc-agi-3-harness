from __future__ import annotations
import subprocess
from pathlib import Path

from common import (
    load_runtime_meta,
    read_json_stdin,
    summarize_instance_state,
    sync_solver_artifacts_to_model_workspace,
    write_json_stdout,
)


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
    synced = sync_solver_artifacts_to_model_workspace(meta, working_directory) if working_directory.exists() else []
    evidence = [summarize_instance_state(state_dir)] if state_dir.exists() else []
    if evidence:
        evidence[0]["synced_artifacts"] = synced
    write_json_stdout({"replay_ok": True, "tool_results": results, "evidence": evidence})


if __name__ == "__main__":
    main()
