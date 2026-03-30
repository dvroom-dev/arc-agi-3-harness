from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def read_json_stdin() -> dict:
    raw = sys.stdin.read().strip()
    if not raw:
        return {}
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise RuntimeError("expected JSON object on stdin")
    return payload


def write_json_stdout(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload) + "\n")


def load_runtime_meta(workspace_root: str) -> dict:
    meta_path = Path(os.environ.get("ARC_FLUX_META_PATH") or Path(workspace_root) / "flux_runtime.json")
    return json.loads(meta_path.read_text())


def safe_instance_name(value: str) -> str:
    out = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in str(value))
    return out.strip("._") or "instance"


def instance_root(workspace_root: str, instance_id: str) -> Path:
    return Path(workspace_root) / "flux_instances" / safe_instance_name(instance_id)


def build_instance_env(meta: dict, state_dir: Path, conversation_id: str) -> dict[str, str]:
    env = dict(os.environ)
    env["PATH"] = f"{meta['run_bin_dir']}:{env.get('PATH', '')}"
    env["ARC_OPERATION_MODE"] = str(meta["operation_mode"])
    env["ARC_BACKEND"] = str(meta["arc_backend"])
    env["ARC_BASE_URL"] = str(meta["arc_base_url"])
    env["ARC_CONFIG_DIR"] = str(meta["run_config_dir"])
    env["ARC_ENVIRONMENTS_DIR"] = str(meta["arc_env_dir"])
    env["ARC_STATE_DIR"] = str(state_dir)
    env["ARC_ACTIVE_GAME_ID"] = str(meta["game_id"])
    env["ARC_PROMPT_GAME_ID"] = str(meta["arc_prompt_game_id"])
    env["ARC_PROMPT_GAME_SLUG"] = str(meta["arc_prompt_game_slug"])
    env["ARC_PROMPT_GAME_DIR"] = str(meta["arc_prompt_game_dir"])
    env["ARC_PROMPT_ACTIONS_BLOCK"] = str(meta["arc_prompt_actions_block"])
    env["ARC_PROMPT_AVAILABLE_ACTIONS"] = ",".join(str(x) for x in meta.get("arc_prompt_available_actions", []))
    env["ARC_CONVERSATION_ID"] = conversation_id
    env["ARC_REPL_SESSION_KEY"] = conversation_id
    env["ONLY_RESET_LEVELS"] = "true"
    if meta.get("scorecard_id"):
        env["ARC_SCORECARD_ID"] = str(meta["scorecard_id"])
    return env


def copy_solver_template(meta: dict, destination: Path) -> Path:
    source = Path(meta["solver_template_dir"])
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)
    return destination


def run_arc_repl_status(meta: dict, env: dict[str, str], cwd: Path) -> dict:
    proc = subprocess.run(
        [meta["python_executable"], meta["run_arc_repl_tool"]],
        input=json.dumps({"action": "status", "game_id": meta["game_id"]}),
        text=True,
        capture_output=True,
        cwd=str(cwd),
        env=env,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"arc_repl status failed: {proc.stderr or proc.stdout}")
    parsed = json.loads(proc.stdout or "{}")
    if not isinstance(parsed, dict):
        raise RuntimeError("arc_repl status returned non-object JSON")
    return parsed


def summarize_instance_state(state_dir: Path) -> dict:
    state_path = state_dir / "state.json"
    history_path = state_dir / "tool-engine-history.json"
    action_history_path = state_dir / "action-history.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    history = json.loads(history_path.read_text()) if history_path.exists() else []
    action_history = json.loads(action_history_path.read_text()) if action_history_path.exists() else []
    return {
        "summary": (
            f"state={state.get('state', '?')} "
            f"level={state.get('current_level', '?')} "
            f"completed={state.get('levels_completed', '?')} "
            f"history_events={len(history) if isinstance(history, list) else 0} "
            f"actions={len(action_history) if isinstance(action_history, list) else 0}"
        ),
        "state": state if isinstance(state, dict) else {},
        "history_count": len(history) if isinstance(history, list) else 0,
        "action_count": len(action_history) if isinstance(action_history, list) else 0,
    }
