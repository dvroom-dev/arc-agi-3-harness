from __future__ import annotations

import subprocess
from pathlib import Path

from common import (
    load_runtime_meta,
    read_json_stdin,
    summarize_instance_state,
    sync_solver_artifacts_to_model_workspace,
    validate_replay_shell_cmd,
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


def _resolve_replay_path(working_directory: Path, raw_path: str) -> Path:
    raw_text = str(raw_path or "").strip()
    raw = Path(raw_text)
    if raw.is_absolute():
        return raw
    workspace_name = working_directory.name
    parts = [part for part in raw.parts if part not in {"", "."}]
    candidates: list[list[str]] = [parts]
    if len(parts) >= 2 and parts[0] == "agent":
        if parts[1] == workspace_name:
            candidates.append(parts[2:])
        else:
            candidates.append(parts[1:])
    if parts[:1] == [workspace_name]:
        candidates.append(parts[1:])
    seen: set[tuple[str, ...]] = set()
    for candidate in candidates:
        key = tuple(candidate)
        if key in seen:
            continue
        seen.add(key)
        target = working_directory.joinpath(*candidate).resolve()
        if target.exists():
            return target
    if parts[:2] == ["agent", workspace_name]:
        return working_directory.joinpath(*parts[2:]).resolve()
    if parts[:1] == [workspace_name]:
        return working_directory.joinpath(*parts[1:]).resolve()
    return working_directory.joinpath(*parts).resolve()


def _read_file(cwd: Path, path_text: str) -> dict:
    target = _resolve_replay_path(cwd, path_text)
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
    replay_ok = True
    error = None
    for index, step in enumerate(seed_bundle.get("replayPlan", []), start=1):
        if not isinstance(step, dict):
            continue
        tool = str(step.get("tool", "")).strip()
        args = step.get("args") if isinstance(step.get("args"), dict) else {}
        result = None
        if tool == "shell":
            try:
                cmd = validate_replay_shell_cmd(args.get("cmd"))
                result = _run_shell(cmd, working_directory, env)
            except RuntimeError as exc:
                result = {"tool": "shell", "returncode": 1, "stdout": "", "stderr": str(exc)}
        elif tool == "write_file":
            result = _write_file(working_directory, str(args.get("path", "")), str(args.get("content", "")))
        elif tool == "read_file":
            result = _read_file(working_directory, str(args.get("path", "")))
        else:
            result = {"tool": tool, "returncode": 1, "stdout": "", "stderr": f"unsupported replay tool: {tool}"}
        results.append(result)
        if int(result.get("returncode", 0) or 0) != 0:
            replay_ok = False
            error = {"stepIndex": index, "step": step, "result": result}
            break
    state_dir = Path(str(instance.get("metadata", {}).get("state_dir", "")))
    synced = (
        sync_solver_artifacts_to_model_workspace(meta, working_directory, state_dir=state_dir)
        if working_directory.exists()
        else []
    )
    evidence = [summarize_instance_state(state_dir)] if state_dir.exists() else []
    if evidence:
        evidence[0]["synced_artifacts"] = synced
    write_json_stdout(
        {
            "replay_ok": replay_ok,
            "error": error,
            "tool_results": results,
            "evidence": evidence,
        }
    )


if __name__ == "__main__":
    main()
