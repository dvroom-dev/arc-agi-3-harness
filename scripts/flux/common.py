from __future__ import annotations

import json
import os
import re
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
from scripts.flux.feature_boxes import generate_feature_boxes


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


ALLOWED_REPLAY_SHELL_PROGRAMS = {"arc_action", "arc_repl", "arc_level"}


def validate_replay_shell_cmd(cmd: object) -> list[str]:
    if not isinstance(cmd, list) or not cmd or not all(isinstance(item, str) and item for item in cmd):
        raise RuntimeError("replay shell step must use args.cmd as a non-empty string array")
    argv = [str(item) for item in cmd]
    program = argv[0].strip()
    if not program:
        raise RuntimeError("replay shell step args.cmd[0] must be a non-empty program name")
    if any(ch.isspace() for ch in program):
        raise RuntimeError("replay shell step args.cmd[0] must be a direct program token, not a shell snippet")
    if program not in ALLOWED_REPLAY_SHELL_PROGRAMS:
        allowed = ", ".join(sorted(ALLOWED_REPLAY_SHELL_PROGRAMS))
        raise RuntimeError(f"replay shell step args.cmd[0] must be one of {allowed}")
    return argv


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
        records = [rec for rec in action_history if isinstance(rec, dict)]
    elif isinstance(action_history, dict):
        raw_records = action_history.get("records")
        records = [rec for rec in raw_records if isinstance(rec, dict)] if isinstance(raw_records, list) else []
    else:
        records = []
    total_action_records = len(records)
    reset_action_count = sum(
        1
        for rec in records
        if str(rec.get("action_name", "")).strip().upper() == "RESET_LEVEL"
        or str(rec.get("call_action", "")).strip().lower() == "reset_level"
        or str(rec.get("source", "")).strip().lower() == "reset_level"
    )
    action_count = total_action_records - reset_action_count
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
        "total_action_records": total_action_records,
        "reset_action_count": reset_action_count,
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
            if (
                child.is_dir()
                and re.fullmatch(r"level_\d+", name)
                and destination.exists()
                and destination.is_dir()
                and not (child / "sequences").exists()
                and (destination / "sequences").exists()
            ):
                synced.append(str(destination))
                continue
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

    return synced


def sync_evidence_bundle_to_model_workspace(meta: dict, bundle_path: Path, *, target_workspace: Path | None = None) -> list[str]:
    manifest_path = bundle_path / "manifest.json"
    if not manifest_path.exists():
        raise RuntimeError(f"missing evidence bundle manifest: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text())
    except Exception as exc:
        raise RuntimeError(f"failed to read evidence bundle manifest {manifest_path}: {exc}") from exc
    workspace_dir = Path(str(manifest.get("workspace_dir") or "")).resolve()
    if not workspace_dir.exists():
        raise RuntimeError(f"evidence bundle workspace_dir is missing: {workspace_dir}")
    model_workspace = Path(str(target_workspace or meta["model_workspace_dir"]))
    synced: list[str] = []
    bundle_completeness = manifest.get("bundle_completeness") if isinstance(manifest.get("bundle_completeness"), dict) else {}

    def _cleanup_path(target: Path) -> None:
        if target.exists() or target.is_symlink():
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target, ignore_errors=True)
            else:
                target.unlink(missing_ok=True)

    def _replace_copy(child: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
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
            synced.append(str(destination))
        finally:
            _cleanup_path(temp_target)
            _cleanup_path(backup_target)

    with workspace_sync_lock(model_workspace):
        model_workspace.mkdir(parents=True, exist_ok=True)
        for child in sorted(workspace_dir.iterdir()):
            name = child.name
            should_sync = (
                name == "level_current"
                or name == "analysis_level"
                or name == "solver_handoff"
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
        solver_handoff_path = model_workspace / "solver_handoff" / "untrusted_theories.md"
        frontier_level = int(bundle_completeness.get("frontier_level", 0) or 0)
        theory_level = max(0, frontier_level - 1)
        if theory_level > 0 and solver_handoff_path.exists():
            theory_json_path = model_workspace / f"untrusted_theories_level_{theory_level}.json"
            theory_payload = {
                "schema_version": "flux.solver_untrusted_theory_handoff.v1",
                "level": theory_level,
                "frontier_level": frontier_level,
                "attempt_id": manifest.get("attempt_id"),
                "instance_id": manifest.get("instance_id"),
                "evidence_bundle_id": manifest.get("bundle_id"),
                "solver_handoff_markdown_path": "solver_handoff/untrusted_theories.md",
            }
            theory_json_path.write_text(json.dumps(theory_payload, indent=2) + "\n", encoding="utf-8")
            synced.append(str(theory_json_path))
        for level_dir in sorted(model_workspace.glob("level_*")):
            if not level_dir.is_dir():
                continue
            name = level_dir.name
            if name == "level_current" or name == "analysis_level" or not name.startswith("level_"):
                continue
            try:
                feature_boxes = generate_feature_boxes(level_dir)
            except Exception:
                continue
            level_num = int(feature_boxes.get("level", 0) or 0)
            if level_num <= 0:
                continue
            feature_boxes_path = model_workspace / f"feature_boxes_level_{level_num}.json"
            feature_boxes_path.write_text(json.dumps(feature_boxes, indent=2) + "\n", encoding="utf-8")
            synced.append(str(feature_boxes_path))
    return synced
