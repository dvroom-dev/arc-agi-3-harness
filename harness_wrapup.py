from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
from typing import Any

from arc_model_runtime.utils import (
    clear_analysis_level_pin,
    sync_workspace_level_view,
)
from arc_model_runtime.visible_artifacts import sanitize_visible_level_tree
from arc_model_runtime.visible_compare_surface import compare_placeholder_payload


def _read_json_if_exists(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _int_or_none(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except Exception:
        return None


def _remove_path(path: Path) -> None:
    if not path.exists() and not path.is_symlink():
        return
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
        return
    shutil.rmtree(path, ignore_errors=True)


def load_super_process_state_impl(runtime) -> dict[str, str]:
    payload = _read_json_if_exists(runtime.run_dir / "super" / "state.json")
    if not isinstance(payload, dict):
        return {}
    out: dict[str, str] = {}
    for key in ("activeMode", "activeProcessStage", "activeTaskProfile"):
        text = str(payload.get(key) or "").strip()
        if text:
            out[key] = text
    return out


def load_super_transition_payload_impl(runtime) -> dict[str, str]:
    payload = _read_json_if_exists(runtime.run_dir / "super" / "state.json")
    if not isinstance(payload, dict):
        return {}
    raw = payload.get("activeTransitionPayload")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for key, value in raw.items():
        key_text = str(key or "").strip()
        value_text = str(value or "").strip()
        if key_text and value_text:
            out[key_text] = value_text
    return out


def load_explicit_level_state_impl(runtime) -> dict[str, Any]:
    transition = load_super_transition_payload_impl(runtime)
    frontier_state = runtime.load_state() or {}
    frontier_level = _int_or_none(transition.get("frontier_level"))
    if frontier_level is None:
        frontier_level = _int_or_none(frontier_state.get("current_level"))
    analysis_level = _int_or_none(transition.get("analysis_level"))
    if analysis_level is None:
        analysis_level = frontier_level
    analysis_scope = str(transition.get("analysis_scope") or "").strip()
    if not analysis_scope:
        analysis_scope = "frontier" if analysis_level == frontier_level else "level"
    return {
        "analysis_scope": analysis_scope or "frontier",
        "analysis_level": analysis_level,
        "frontier_level": frontier_level,
        "transition_payload": transition,
    }


def load_wrapup_status_impl(runtime) -> dict[str, Any]:
    state = load_explicit_level_state_impl(runtime)
    analysis_level = _int_or_none(state.get("analysis_level"))
    frontier_level = _int_or_none(state.get("frontier_level"))
    compare = _read_json_if_exists(runtime.active_agent_dir() / "current_compare.json")
    compare_level = _int_or_none((compare or {}).get("level"))
    compare_clean = (compare or {}).get("all_match") is True
    active = (
        analysis_level is not None
        and frontier_level is not None
        and int(analysis_level) < int(frontier_level)
    )
    return {
        "active": bool(active),
        "analysis_scope": str(state.get("analysis_scope") or "frontier"),
        "analysis_level": analysis_level,
        "frontier_level": frontier_level,
        "compare_clean": bool(compare_clean),
        "compare_level": compare_level,
    }


def repair_stale_wrapup_mode_impl(runtime) -> str | None:
    return None


def _sync_analysis_state_file(runtime, *, analysis_scope: str, analysis_level: int, frontier_level: int) -> None:
    game_dir = runtime.active_agent_dir()
    payload = {
        "schema_version": "arc.analysis_state.v2",
        "analysis_scope": str(analysis_scope),
        "analysis_level": int(analysis_level),
        "frontier_level": int(frontier_level),
        "analysis_level_dir": "analysis_level" if int(analysis_level) != int(frontier_level) else None,
        "level_current_dir": "level_current",
    }
    (game_dir / "analysis_state.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _copy_root_compare_for_analysis_level(game_dir: Path, *, analysis_level: int) -> None:
    root_compare_json = game_dir / "current_compare.json"
    root_compare_md = game_dir / "current_compare.md"
    analysis_compare_dir = game_dir / "analysis_level" / "sequence_compare"
    analysis_compare_json = analysis_compare_dir / "current_compare.json"
    analysis_compare_md = analysis_compare_dir / "current_compare.md"
    if analysis_compare_json.exists():
        shutil.copy2(analysis_compare_json, root_compare_json)
        if analysis_compare_md.exists():
            shutil.copy2(analysis_compare_md, root_compare_md)
        else:
            root_compare_md.unlink(missing_ok=True)
        return
    json_text, md_text = compare_placeholder_payload(visible_level=int(analysis_level))
    root_compare_json.write_text(json_text, encoding="utf-8")
    root_compare_md.write_text(md_text, encoding="utf-8")


def _sync_analysis_level_surface(
    runtime,
    *,
    analysis_level: int,
    frontier_level: int,
    analysis_scope: str,
) -> None:
    game_dir = runtime.active_agent_dir()
    safe_game = runtime.active_game_id or str(runtime.args.game_id).strip()
    visible_level = sync_workspace_level_view(
        game_dir,
        game_id=safe_game,
        frontier_level=int(frontier_level),
    )
    if visible_level is None and int(analysis_level) == int(frontier_level):
        _sync_analysis_state_file(
            runtime,
            analysis_scope=str(analysis_scope),
            analysis_level=int(analysis_level),
            frontier_level=int(frontier_level),
        )
        return
    if visible_level is not None and visible_level != int(frontier_level):
        raise RuntimeError(
            "frontier workspace level drifted while syncing explicit analysis state: "
            f"expected_frontier={frontier_level} visible_level={visible_level}"
        )
    analysis_dir = game_dir / "analysis_level"
    _remove_path(analysis_dir)
    if int(analysis_level) == int(frontier_level):
        _sync_analysis_state_file(
            runtime,
            analysis_scope=str(analysis_scope),
            analysis_level=int(analysis_level),
            frontier_level=int(frontier_level),
        )
        return

    safe_game = str(runtime.active_game_id or runtime.args.game_id).strip()
    artifacts_root = runtime.arc_state_dir / "game_artifacts" / f"game_{safe_game}"
    src = artifacts_root / f"level_{int(analysis_level)}"
    if not src.exists() or not src.is_dir():
        raise RuntimeError(
            "missing canonical artifacts for explicit analysis level: "
            f"analysis_level={analysis_level} src={src}"
        )
    temp = game_dir / ".analysis_level.tmp"
    _remove_path(temp)
    shutil.copytree(src, temp)
    sanitize_visible_level_tree(temp, visible_level=int(analysis_level))
    (temp / "meta.json").write_text(
        json.dumps(
            {
                "schema_version": "arc.analysis_level_surface.v2",
                "game_id": str(safe_game),
                "level": int(analysis_level),
                "analysis_scope": str(analysis_scope),
                "frontier_level": int(frontier_level),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    temp.rename(analysis_dir)
    _copy_root_compare_for_analysis_level(game_dir, analysis_level=int(analysis_level))
    _sync_analysis_state_file(
        runtime,
        analysis_scope=str(analysis_scope),
        analysis_level=int(analysis_level),
        frontier_level=int(frontier_level),
    )


def force_recover_mode_impl(
    runtime,
    *,
    reason: str,
    frontier_level: int | None,
    levels_completed: int | None,
) -> None:
    state_path = runtime.run_dir / "super" / "state.json"
    state_payload = _read_json_if_exists(state_path) or {}
    if not isinstance(state_payload, dict):
        state_payload = {}

    state_payload["activeMode"] = "recover"
    state_payload["activeModePayload"] = {
        "recover": "game_over_restart",
        "user_message": (
            "GAME_OVER occurred and the same run was reset in place. "
            "Start in recover mode, replay previously solved levels, and return to the latest unsolved frontier. "
            f"Frontier before GAME_OVER was level={frontier_level!r}, levels_completed={levels_completed!r}. "
            f"Reason: {reason}"
        ),
    }
    state_payload["activeTransitionPayload"] = {}
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state_payload, indent=2) + "\n")


def validate_wrapup_surfaces_impl(runtime) -> None:
    status = load_wrapup_status_impl(runtime)
    game_dir = runtime.active_agent_dir()
    frontier_level = _int_or_none(status["frontier_level"])
    analysis_level = _int_or_none(status["analysis_level"])
    errors: list[str] = []
    if (game_dir / ".analysis_level_pin.json").exists():
        errors.append(".analysis_level_pin.json must not exist on the active v2 level-state path")
    analysis_state = _read_json_if_exists(game_dir / "analysis_state.json") or {}
    if frontier_level is not None and _int_or_none(analysis_state.get("frontier_level")) != frontier_level:
        errors.append(
            "analysis_state.frontier_level="
            f"{_int_or_none(analysis_state.get('frontier_level'))} expected={frontier_level}"
        )
    if analysis_level is not None and _int_or_none(analysis_state.get("analysis_level")) != analysis_level:
        errors.append(
            "analysis_state.analysis_level="
            f"{_int_or_none(analysis_state.get('analysis_level'))} expected={analysis_level}"
        )
    level_current_meta = _read_json_if_exists(game_dir / "level_current" / "meta.json") or {}
    if level_current_meta and frontier_level is not None and _int_or_none(level_current_meta.get("level")) != frontier_level:
        errors.append(
            f"level_current.level={_int_or_none(level_current_meta.get('level'))} expected={frontier_level}"
        )
    if bool(status["active"]):
        analysis_meta = _read_json_if_exists(game_dir / "analysis_level" / "meta.json") or {}
        if analysis_level is None:
            errors.append("analysis_level missing while explicit non-frontier analysis is active")
        elif _int_or_none(analysis_meta.get("level")) != analysis_level:
            errors.append(
                "analysis_level.level="
                f"{_int_or_none(analysis_meta.get('level'))} expected={analysis_level}"
            )
        compare = _read_json_if_exists(game_dir / "current_compare.json") or {}
        if analysis_level is not None and _int_or_none(compare.get("level")) != analysis_level:
            errors.append(
                f"current_compare.level={_int_or_none(compare.get('level'))} expected={analysis_level}"
            )
    elif (game_dir / "analysis_level").exists():
        errors.append("analysis_level surface should not exist when analysis_level == frontier_level")

    if errors:
        raise RuntimeError("explicit analysis-level surface validation failed: " + "; ".join(errors))


def certify_or_block_wrapup_transition_impl(runtime) -> None:
    state = load_explicit_level_state_impl(runtime)
    analysis_level = _int_or_none(state.get("analysis_level"))
    frontier_level = _int_or_none(state.get("frontier_level"))
    if analysis_level is None or frontier_level is None:
        return
    prior_arc_state_dir = os.environ.get("ARC_STATE_DIR")
    os.environ["ARC_STATE_DIR"] = str(runtime.arc_state_dir)
    try:
        clear_analysis_level_pin(runtime.active_agent_dir())
        _sync_analysis_level_surface(
            runtime,
            analysis_level=int(analysis_level),
            frontier_level=int(frontier_level),
            analysis_scope=str(state.get("analysis_scope") or "frontier"),
        )
    finally:
        if prior_arc_state_dir is None:
            os.environ.pop("ARC_STATE_DIR", None)
        else:
            os.environ["ARC_STATE_DIR"] = prior_arc_state_dir
    validate_wrapup_surfaces_impl(runtime)
    runtime.refresh_dynamic_super_env()
    runtime.log(
        "[harness] synced explicit analysis state from supervisor transition payload: "
        f"analysis_scope={state['analysis_scope']} analysis_level={analysis_level} "
        f"frontier_level={frontier_level}"
    )
