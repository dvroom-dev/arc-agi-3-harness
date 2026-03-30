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


def sync_solver_artifacts_to_model_workspace(meta: dict, solver_dir: Path, state_dir: Path | None = None) -> list[str]:
    model_workspace = Path(str(meta["model_workspace_dir"]))
    model_workspace.mkdir(parents=True, exist_ok=True)
    synced: list[str] = []
    def _replace_copy(child: Path, destination: Path) -> None:
        if destination.exists() or destination.is_symlink():
            if destination.is_dir() and not destination.is_symlink():
                shutil.rmtree(destination, ignore_errors=True)
            else:
                destination.unlink(missing_ok=True)
        if child.is_dir():
            shutil.copytree(child, destination)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(child, destination)
        synced.append(str(destination))

    for child in solver_dir.iterdir():
        name = child.name
        should_sync = (
            name == "level_current"
            or name == "analysis_level"
            or name.startswith("level_")
            or name in {
                "current_compare.json",
                "current_compare.md",
                "component_coverage.json",
                "component_coverage.md",
                "analysis_state.json",
                ".analysis_level_pin.json",
                "model_status.json",
            }
        )
        if not should_sync:
            continue
        destination = model_workspace / name
        _replace_copy(child, destination)

    if state_dir is not None:
        game_artifacts_root = state_dir / "game_artifacts"
        if game_artifacts_root.exists():
            for game_root in sorted(game_artifacts_root.iterdir()):
                if not game_root.is_dir():
                    continue
                for child in sorted(game_root.iterdir()):
                    if not child.is_dir():
                        continue
                    if child.name.startswith("level_"):
                        _replace_copy(child, model_workspace / child.name)

    _ensure_sequence_surface(meta, model_workspace)
    return synced


def _ensure_sequence_surface(meta: dict, model_workspace: Path) -> None:
    level_current = model_workspace / "level_current"
    if not level_current.exists():
        return
    meta_path = level_current / "meta.json"
    try:
        level_payload = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        level_num = int(level_payload.get("level", 1) or 1)
    except Exception:
        level_num = 1
    level_dir = model_workspace / f"level_{level_num}"
    if not level_dir.exists():
        shutil.copytree(level_current, level_dir)
    turn_meta_candidates: list[tuple[int, Path, dict]] = []
    for candidate in sorted(level_dir.glob("turn_*")):
        turn_meta_path = candidate / "meta.json"
        if not turn_meta_path.exists():
            continue
        try:
            turn_meta = json.loads(turn_meta_path.read_text())
        except Exception:
            continue
        try:
            turn_num = int(str(candidate.name).split("_")[-1])
        except Exception:
            turn_num = 0
        turn_meta_candidates.append((turn_num, candidate, turn_meta))
    if not turn_meta_candidates:
        return
    actionable = [
        item
        for item in turn_meta_candidates
        if int(item[2].get("steps_executed", 0) or 0) > 0
        or str(item[2].get("action_label", "") or "").strip().lower() != "status"
    ]
    if not actionable:
        return
    _turn_num, turn_dir, turn_meta = actionable[-1]
    turn_rel = turn_dir.name
    sequence_dir = level_dir / "sequences"
    sequence_dir.mkdir(parents=True, exist_ok=True)
    sequence_path = sequence_dir / "seq_0001.json"
    if sequence_path.exists():
        return
    game_id = str(turn_meta.get("game_id", meta.get("game_id", "")) or "")
    action_name = str(turn_meta.get("action_label", "") or "").upper()
    if action_name.startswith("EXEC("):
        action_name = "ACTION1"
    levels_completed_before = int(turn_meta.get("levels_completed_before", 0) or 0)
    levels_completed_after = int(turn_meta.get("levels_completed_after", 0) or 0)
    level_complete_after = bool(turn_meta.get("level_complete_after", False))
    game_over_after = bool(turn_meta.get("game_over_after", False))
    end_reason = "open"
    if game_over_after:
        end_reason = "game_over"
    elif levels_completed_after > levels_completed_before or level_complete_after:
        end_reason = "level_change"
    sequence_payload = {
        "schema_version": "arc_repl.level_sequence.v1",
        "game_id": game_id,
        "level": int(level_num),
        "sequence_id": "seq_0001",
        "sequence_number": 1,
        "start_action_index": 1,
        "end_action_index": 1,
        "start_recorded_at_utc": "",
        "end_recorded_at_utc": "",
        "end_reason": end_reason,
        "action_count": 1,
        "actions": [
            {
                "local_step": 1,
                "action_index": 1,
                "tool_turn": int(turn_meta.get("tool_turn", 1) or 1),
                "step_in_call": 1,
                "call_action": "exec",
                "action_name": action_name,
                "action_data": {},
                "recorded_at_utc": "",
                "state_before": str(turn_meta.get("state_before_action", "") or ""),
                "state_after": str(turn_meta.get("state_after_action", "") or ""),
                "level_before": int(turn_meta.get("level_before", level_num) or level_num),
                "level_after": int(turn_meta.get("level_after", level_num) or level_num),
                "levels_completed_before": levels_completed_before,
                "levels_completed_after": levels_completed_after,
                "level_complete_before": bool(turn_meta.get("level_complete_before", False)),
                "level_complete_after": level_complete_after,
                "game_over_before": bool(turn_meta.get("game_over_before", False)),
                "game_over_after": game_over_after,
                "files": {
                    "before_state_hex": f"{turn_rel}/before_state.hex",
                    "after_state_hex": f"{turn_rel}/after_state.hex",
                    "meta_json": f"{turn_rel}/meta.json",
                },
            }
        ],
    }
    sequence_path.write_text(json.dumps(sequence_payload, indent=2) + "\n", encoding="utf-8")


def sync_latest_attempt_to_model_workspace(workspace_root: str, meta: dict) -> list[str]:
    attempts_root = Path(workspace_root) / "flux_instances"
    if not attempts_root.exists():
        return []
    attempts = [path for path in attempts_root.iterdir() if path.is_dir()]
    if not attempts:
        return []
    latest = max(attempts, key=lambda path: path.stat().st_mtime)
    solver_dir = latest / "agent" / Path(str(meta["solver_template_dir"])).name
    state_dir = latest / "supervisor" / "arc"
    if not solver_dir.exists():
        return []
    return sync_solver_artifacts_to_model_workspace(meta, solver_dir, state_dir=state_dir)
