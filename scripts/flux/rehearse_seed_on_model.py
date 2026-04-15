from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from common import (
    copy_model_workspace,
    load_runtime_meta,
    read_json_stdin,
    safe_instance_name,
    validate_replay_shell_cmd,
    write_json_stdout,
)


def _model_env(meta: dict, model_workspace: Path, arc_state_dir: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["ARC_CONFIG_DIR"] = str(meta["run_config_dir"])
    env["ARC_STATE_DIR"] = str(arc_state_dir)
    env["ARC_MODEL_DISABLE_CANONICAL_ARTIFACTS"] = "1"
    env["PATH"] = f"{meta['run_bin_dir']}:{env.get('PATH', '')}"
    return env


def _run_model_command(model_workspace: Path, env: dict[str, str], args: list[str], stdin_text: str | None = None) -> dict:
    proc = subprocess.run(
        ["python3", "model.py", *args],
        cwd=str(model_workspace),
        env=env,
        text=True,
        input=stdin_text,
        capture_output=True,
    )
    parsed = None
    try:
        parsed = json.loads(proc.stdout or "{}")
    except Exception:
        parsed = None
    return {
        "cmd": ["python3", "model.py", *args],
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "parsed": parsed,
    }


def _run_shell(cmd: list[str], cwd: Path, env: dict[str, str]) -> dict:
    proc = subprocess.run(cmd, cwd=str(cwd), env=env, text=True, capture_output=True)
    parsed = None
    try:
        parsed = json.loads(proc.stdout or "{}")
    except Exception:
        parsed = None
    return {
        "cmd": cmd,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "parsed": parsed,
    }


def _resolve_rehearsal_path(model_workspace: Path, raw_path: str) -> Path:
    raw_text = str(raw_path or "").strip()
    raw = Path(raw_text)
    if raw.is_absolute():
        return raw
    workspace_name = model_workspace.name
    parts = [part for part in raw.parts if part not in {"", "."}]
    candidates: list[list[str]] = [parts]
    if len(parts) >= 2 and parts[0] == "agent":
        if parts[1] == workspace_name:
            candidates.append(parts[2:])
        else:
            candidates.append(parts[1:])
    if parts and parts[0] == workspace_name:
        candidates.append(parts[1:])
    seen: set[tuple[str, ...]] = set()
    for candidate in candidates:
        key = tuple(candidate)
        if key in seen:
            continue
        seen.add(key)
        target = model_workspace.joinpath(*candidate).resolve()
        if target.exists():
            return target
    if parts[:2] == ["agent", workspace_name]:
        return model_workspace.joinpath(*parts[2:]).resolve()
    if parts[:1] == [workspace_name]:
        return model_workspace.joinpath(*parts[1:]).resolve()
    return model_workspace.joinpath(*parts).resolve()


def _translated_model_step(model_workspace: Path, env: dict[str, str], cmd: list[str]) -> dict:
    if cmd and cmd[0] == "arc_action" and len(cmd) >= 2:
        action_name = str(cmd[1]).strip().upper()
        script = (
            "from arcengine import GameAction\n"
            f"env.step(GameAction.{action_name})\n"
        )
        result = _run_model_command(model_workspace, env, ["exec", "--game-id", str(env.get("ARC_ACTIVE_GAME_ID", ""))], script)
        result["translated_from"] = cmd
        result["translation"] = f"model.py exec GameAction.{action_name}"
        return result
    if cmd[:1] == ["arc_level"]:
        result = _run_model_command(model_workspace, env, ["status", "--game-id", str(env.get("ARC_ACTIVE_GAME_ID", ""))])
        result["translated_from"] = cmd
        result["translation"] = "model.py status"
        return result
    if cmd[:2] == ["arc_repl", "status"]:
        result = _run_model_command(model_workspace, env, ["status", "--game-id", str(env.get("ARC_ACTIVE_GAME_ID", ""))])
        result["translated_from"] = cmd
        result["translation"] = "model.py status"
        return result
    if cmd[:2] == ["arc_repl", "reset_level"]:
        result = _run_model_command(model_workspace, env, ["reset_level", "--game-id", str(env.get("ARC_ACTIVE_GAME_ID", ""))])
        result["translated_from"] = cmd
        result["translation"] = "model.py reset_level"
        return result
    if cmd[:2] == ["arc_repl", "shutdown"]:
        result = _run_model_command(model_workspace, env, ["shutdown", "--game-id", str(env.get("ARC_ACTIVE_GAME_ID", ""))])
        result["translated_from"] = cmd
        result["translation"] = "model.py shutdown"
        return result
    result = _run_shell(cmd, model_workspace, env)
    result["translated_from"] = cmd
    result["translation"] = "shell_passthrough"
    return result


def _reached_expected_frontier(parsed: dict | None, expected_frontier_level: int | None) -> bool:
    if not isinstance(parsed, dict):
        return False
    if not expected_frontier_level or expected_frontier_level <= 0:
        return False
    current_level = int(parsed.get("current_level", 0) or 0)
    levels_completed = int(parsed.get("levels_completed", 0) or 0)
    return levels_completed >= expected_frontier_level or current_level > expected_frontier_level


def main() -> None:
    payload = read_json_stdin()
    workspace_root = str(payload["workspaceRoot"])
    meta = load_runtime_meta(workspace_root)
    seed_bundle = payload.get("seedBundle") if isinstance(payload.get("seedBundle"), dict) else {}
    model_revision_id = str(payload.get("modelRevisionId") or "").strip()
    expected_frontier_level = int(payload.get("expectedFrontierLevel", 0) or 0) or None
    seed_key = safe_instance_name(str(payload.get("seedRevisionId") or payload.get("seedHash") or "seed"))
    rehearsal_root = Path(workspace_root) / "flux_model_rehearsals" / seed_key
    model_workspace = rehearsal_root / Path(str(meta["model_workspace_dir"])).name
    arc_state_dir = rehearsal_root / "arc_state"
    if rehearsal_root.exists():
        shutil.rmtree(rehearsal_root, ignore_errors=True)
    arc_state_dir.mkdir(parents=True, exist_ok=True)
    if model_revision_id:
        snapshot_source = Path(workspace_root) / "flux" / "model" / "revisions" / model_revision_id / "workspace" / model_workspace.name
        if not snapshot_source.exists():
            raise FileNotFoundError(f"missing model revision workspace: {snapshot_source}")
        if model_workspace.exists():
            shutil.rmtree(model_workspace, ignore_errors=True)
        model_workspace.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(snapshot_source, model_workspace)
    else:
        copy_model_workspace(meta, model_workspace)
    env = _model_env(meta, model_workspace, arc_state_dir)
    env["ARC_ACTIVE_GAME_ID"] = str(meta["game_id"])

    _run_model_command(model_workspace, env, ["shutdown", "--game-id", str(meta["game_id"])])
    status_before = _run_model_command(model_workspace, env, ["status", "--game-id", str(meta["game_id"])])

    tool_results: list[dict] = []
    rehearsal_ok = True
    error = None
    for step in seed_bundle.get("replayPlan", []):
        if not isinstance(step, dict):
            continue
        tool = str(step.get("tool", "")).strip()
        args = step.get("args") if isinstance(step.get("args"), dict) else {}
        if tool == "shell":
            try:
                cmd = validate_replay_shell_cmd(args.get("cmd"))
            except RuntimeError as exc:
                rehearsal_ok = False
                error = {"type": "invalid_shell_step", "step": step, "message": str(exc)}
                break
            result = _translated_model_step(model_workspace, env, cmd)
            tool_results.append({"tool": "shell", **result})
            parsed = result.get("parsed") if isinstance(result.get("parsed"), dict) else {}
            if int(result["returncode"]) != 0 or (parsed and not bool(parsed.get("ok", True))):
                rehearsal_ok = False
                error = {"type": "shell_step_failed", "cmd": cmd, "result": result}
                break
            if _reached_expected_frontier(parsed, expected_frontier_level):
                break
            continue
        if tool == "write_file":
            target = _resolve_rehearsal_path(model_workspace, str(args.get("path", "")))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(str(args.get("content", "")), encoding="utf-8")
            tool_results.append({"tool": "write_file", "path": str(target), "bytes": len(str(args.get("content", "")).encode("utf-8"))})
            continue
        if tool == "read_file":
            target = _resolve_rehearsal_path(model_workspace, str(args.get("path", "")))
            if not target.exists():
                raise FileNotFoundError(
                    f"rehearsal path missing: requested={args.get('path', '')!r} resolved={str(target)!r}"
                )
            tool_results.append({"tool": "read_file", "path": str(target), "content": target.read_text(encoding="utf-8")})
            continue
        rehearsal_ok = False
        error = {"type": "unsupported_replay_tool", "tool": tool}
        break

    status_after = _run_model_command(model_workspace, env, ["status", "--game-id", str(meta["game_id"])])
    status_payload = status_after.get("parsed") if isinstance(status_after.get("parsed"), dict) else {}
    compare_level = int(status_payload.get("current_level", 1) or 1)
    if expected_frontier_level and expected_frontier_level > 0:
        compare_level = expected_frontier_level
    compare_result = _run_model_command(
        model_workspace,
        env,
        ["compare_sequences", "--game-id", str(meta["game_id"]), "--level", str(compare_level), "--include-reset-ended"],
    )
    compare_payload = compare_result.get("parsed") if isinstance(compare_result.get("parsed"), dict) else {}
    compare_ok = bool(compare_payload.get("ok", False)) if isinstance(compare_payload, dict) else False
    if not compare_ok and rehearsal_ok:
        rehearsal_ok = False
        if error is None:
            error = {
                "type": "compare_failed",
                "message": "compare_sequences did not return ok",
                "compare_payload": compare_payload,
            }
    write_json_stdout(
        {
            "rehearsal_ok": rehearsal_ok,
            "error": error,
            "status_before": status_before.get("parsed"),
            "status_after": status_payload,
            "compare_payload": compare_payload,
            "tool_results": tool_results,
            "model_workspace": str(model_workspace),
        }
    )


if __name__ == "__main__":
    main()
