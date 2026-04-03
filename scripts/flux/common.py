from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from arc_model_runtime.io_utils import copytree_stable, workspace_tree_lock


def read_json_stdin() -> dict:
    raw = sys.stdin.read().strip()
    if not raw:
        return {}
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise RuntimeError("expected JSON object on stdin")
    return payload


def read_json_file_with_retry(path: Path, *, attempts: int = 4, delay_s: float = 0.05):
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            last_error = exc
            if attempt == attempts - 1:
                raise
            time.sleep(delay_s)
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"failed reading JSON from {path}")


def workspace_sync_lock(model_workspace: Path):
    return workspace_tree_lock(model_workspace)


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
    for relative in [
        "model.py",
        "model_lib.py",
        "components.py",
        "artifact_helpers.py",
        "inspect_components.py",
        "inspect_model_sequence.py",
        "inspect_sequence.py",
        "current_compare.json",
        "current_compare.md",
        "model_status.json",
        "analysis_level",
    ]:
        target = destination / relative
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        else:
            target.unlink(missing_ok=True)
    return destination


def copy_model_workspace(meta: dict, destination: Path) -> Path:
    source = Path(str(meta["model_workspace_dir"]))
    with workspace_tree_lock(source):
        if destination.exists():
            shutil.rmtree(destination, ignore_errors=True)
        destination.parent.mkdir(parents=True, exist_ok=True)
        copytree_stable(source, destination)
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
    state = read_json_file_with_retry(state_path) if state_path.exists() else {}
    history = read_json_file_with_retry(history_path) if history_path.exists() else []
    action_history = read_json_file_with_retry(action_history_path) if action_history_path.exists() else []
    history_events = history.get("events", []) if isinstance(history, dict) else history
    if isinstance(action_history, list):
        action_count = len(action_history)
    elif isinstance(action_history, dict):
        records = action_history.get("records")
        action_count = len(records) if isinstance(records, list) else 0
    else:
        action_count = 0
    if action_count == 0 and isinstance(state, dict):
        action_count = int(state.get("current_attempt_steps", 0) or state.get("total_steps", 0) or 0)
    state_payload = state if isinstance(state, dict) else {}
    normalized_last_action = str(state_payload.get("last_action", "") or "")
    action_input_name = str(state_payload.get("action_input_name", "") or "")
    if normalized_last_action.lower().startswith("exec(") and action_input_name:
        normalized_last_action = action_input_name
    if not normalized_last_action and action_input_name:
        normalized_last_action = action_input_name
    if normalized_last_action:
        state_payload = {
            **state_payload,
            "last_action_name": normalized_last_action,
        }
    return {
        "summary": (
            f"state={state.get('state', '?')} "
            f"level={state.get('current_level', '?')} "
            f"completed={state.get('levels_completed', '?')} "
            f"history_events={len(history_events) if isinstance(history_events, list) else 0} "
            f"actions={action_count}"
            + (f" last_action={normalized_last_action}" if normalized_last_action else "")
        ),
        "state": state_payload,
        "history_count": len(history_events) if isinstance(history_events, list) else 0,
        "action_count": action_count,
        "last_action_name": normalized_last_action or None,
    }


def sync_solver_artifacts_to_model_workspace(meta: dict, solver_dir: Path, state_dir: Path | None = None) -> list[str]:
    model_workspace = Path(str(meta["model_workspace_dir"]))
    model_workspace.mkdir(parents=True, exist_ok=True)
    synced: list[str] = []

    def _cleanup_path(target: Path) -> None:
        if target.exists() or target.is_symlink():
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target, ignore_errors=True)
            else:
                target.unlink(missing_ok=True)

    def _is_retryable_copy_error(exc: BaseException) -> bool:
        if isinstance(exc, FileNotFoundError):
            return True
        if not isinstance(exc, shutil.Error):
            return False
        errors = exc.args[0] if exc.args else []
        if not isinstance(errors, list):
            return False
        for record in errors:
            if not isinstance(record, tuple) or len(record) < 3:
                return False
            message = str(record[2])
            if "No such file or directory" not in message:
                return False
        return True

    def _replace_copy(child: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        last_error: BaseException | None = None
        for attempt in range(3):
            temp_target = destination.parent / f".{destination.name}.flux-sync-{uuid.uuid4().hex}"
            backup_target = destination.parent / f".{destination.name}.flux-prev-{uuid.uuid4().hex}"
            _cleanup_path(temp_target)
            _cleanup_path(backup_target)
            try:
                if child.is_dir():
                    copytree_stable(child, temp_target)
                else:
                    shutil.copy2(child, temp_target)
                if destination.exists() or destination.is_symlink():
                    destination.replace(backup_target)
                temp_target.replace(destination)
                _cleanup_path(backup_target)
                synced.append(str(destination))
                return
            except BaseException as exc:
                last_error = exc
                _cleanup_path(temp_target)
                if backup_target.exists() or backup_target.is_symlink():
                    if not (destination.exists() or destination.is_symlink()):
                        try:
                            backup_target.replace(destination)
                        except Exception:
                            pass
                    else:
                        _cleanup_path(backup_target)
                if not _is_retryable_copy_error(exc) or attempt == 2:
                    raise RuntimeError(
                        f"failed to sync artifact {child} -> {destination}: {exc}"
                    ) from exc
                time.sleep(0.05)
        if last_error is not None:
            raise RuntimeError(f"failed to sync artifact {child} -> {destination}: {last_error}")

    with workspace_sync_lock(model_workspace):
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
        copytree_stable(level_current, level_dir)
    elif not any(level_dir.iterdir()):
        for child in level_current.iterdir():
            destination = level_dir / child.name
            if destination.exists() or destination.is_symlink():
                if destination.is_dir() and not destination.is_symlink():
                    shutil.rmtree(destination, ignore_errors=True)
                else:
                    destination.unlink(missing_ok=True)
            if child.is_dir():
                copytree_stable(child, destination)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(child, destination)
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
