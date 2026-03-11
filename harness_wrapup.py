from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from arc_model_runtime.utils import clear_analysis_level_pin, load_analysis_level_pin, sync_workspace_level_view


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


def load_super_active_mode_impl(runtime) -> str | None:
    payload = _read_json_if_exists(runtime.run_dir / "super" / "state.json")
    if not isinstance(payload, dict):
        return None
    mode = str(payload.get("activeMode") or "").strip()
    return mode or None


def load_super_active_mode_payload_impl(runtime) -> dict[str, str]:
    payload = _read_json_if_exists(runtime.run_dir / "super" / "state.json")
    if not isinstance(payload, dict):
        return {}
    raw = payload.get("activeModePayload")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for key, value in raw.items():
        key_text = str(key or "").strip()
        if not key_text:
            continue
        out[key_text] = str(value or "").strip()
    return out


def load_wrapup_status_impl(runtime) -> dict[str, Any]:
    game_dir = runtime.active_agent_dir()
    pin = load_analysis_level_pin(game_dir)
    pinned_level: int | None = None
    if isinstance(pin, dict):
        try:
            pinned_level = int(pin.get("level"))
        except Exception:
            pinned_level = None

    frontier_state = runtime.load_state() or {}
    frontier_level: int | None = None
    try:
        frontier_level = int(frontier_state.get("current_level"))
    except Exception:
        frontier_level = None

    coverage = _read_json_if_exists(game_dir / "component_coverage.json")
    compare = _read_json_if_exists(game_dir / "current_compare.json")
    component_mismatch = _read_json_if_exists(game_dir / "component_mismatch.json")
    coverage_passed = str((coverage or {}).get("status") or "") == "pass"
    compare_clean = (compare or {}).get("all_match") is True
    compare_level: int | None = None
    try:
        compare_level = int((compare or {}).get("level"))
    except Exception:
        compare_level = None
    component_mismatch_ok = str((component_mismatch or {}).get("status") or "") in {"clean", "mismatch"}
    active = (
        pinned_level is not None
        and frontier_level is not None
        and int(pinned_level) < int(frontier_level)
    )
    compare_ready = bool(compare_clean and compare_level is not None and pinned_level is not None and int(compare_level) == int(pinned_level))
    return {
        "active": bool(active),
        "pinned_level": pinned_level,
        "frontier_level": frontier_level,
        "coverage_passed": bool(coverage_passed),
        "compare_clean": bool(compare_clean),
        "compare_level": compare_level,
        "component_mismatch_ok": bool(component_mismatch_ok),
        "ready_to_certify": bool(active and coverage_passed and compare_ready and component_mismatch_ok),
    }


def validate_wrapup_surfaces_impl(runtime) -> None:
    status = load_wrapup_status_impl(runtime)
    if not bool(status["active"]):
        return

    game_dir = runtime.active_agent_dir()
    pinned_level = int(status["pinned_level"])
    frontier_level = int(status["frontier_level"])

    level_current_meta = _read_json_if_exists(game_dir / "level_current" / "meta.json") or {}
    model_status = _read_json_if_exists(game_dir / "model_status.json") or {}
    model_state = model_status.get("state") if isinstance(model_status.get("state"), dict) else {}
    compare = _read_json_if_exists(game_dir / "current_compare.json") or {}

    level_current_level = _int_or_none(level_current_meta.get("level"))
    level_current_frontier = _int_or_none(level_current_meta.get("frontier_level"))
    level_current_pinned = level_current_meta.get("analysis_level_pinned")
    model_current_level = _int_or_none(model_state.get("current_level"))
    model_levels_completed = _int_or_none(model_state.get("levels_completed"))
    model_available_levels = model_state.get("available_model_levels")
    compare_level = _int_or_none(compare.get("level"))

    errors: list[str] = []
    if level_current_level != pinned_level:
        errors.append(f"level_current.level={level_current_level} expected={pinned_level}")
    if level_current_frontier != frontier_level:
        errors.append(f"level_current.frontier_level={level_current_frontier} expected={frontier_level}")
    if level_current_pinned is not True:
        errors.append(f"level_current.analysis_level_pinned={level_current_pinned} expected=True")
    if model_current_level != pinned_level:
        errors.append(f"model_status.state.current_level={model_current_level} expected={pinned_level}")
    if model_levels_completed != max(0, pinned_level - 1):
        errors.append(
            "model_status.state.levels_completed="
            f"{model_levels_completed} expected={max(0, pinned_level - 1)}"
        )
    if isinstance(model_available_levels, list):
        leaked = [lvl for lvl in model_available_levels if int(lvl) > pinned_level]
        if leaked:
            errors.append(f"model_status.state.available_model_levels leaked frontier levels {leaked}")
    if compare and compare_level != pinned_level:
        errors.append(f"current_compare.level={compare_level} expected={pinned_level}")

    if errors:
        raise RuntimeError(
            "solved-level wrap-up surface validation failed while pin is active: "
            + "; ".join(errors)
        )


def certify_or_block_wrapup_transition_impl(runtime) -> None:
    status = load_wrapup_status_impl(runtime)
    validate_wrapup_surfaces_impl(runtime)
    if not bool(status["active"]):
        return

    target_mode = load_super_active_mode_impl(runtime)
    if not target_mode or target_mode in {"theory", "code_model"}:
        return

    target_mode_payload = load_super_active_mode_payload_impl(runtime)
    if not bool(status["ready_to_certify"]):
        raise RuntimeError(
            "cannot leave solved-level wrap-up while pin is active: "
            f"target_mode={target_mode} "
            f"pinned_level={status['pinned_level']} "
            f"frontier_level={status['frontier_level']} "
            f"coverage_passed={status['coverage_passed']} "
            f"compare_clean={status['compare_clean']} "
            f"compare_level={status['compare_level']} "
            f"component_mismatch_ok={status['component_mismatch_ok']}"
        )

    certified = str(target_mode_payload.get("wrapup_certified") or "").strip().lower() == "true"
    certified_level = _int_or_none(target_mode_payload.get("wrapup_level"))
    if not certified or certified_level != int(status["pinned_level"]):
        raise RuntimeError(
            "cannot leave solved-level wrap-up without explicit supervisor certification: "
            f"target_mode={target_mode} "
            f"wrapup_certified={target_mode_payload.get('wrapup_certified')} "
            f"wrapup_level={target_mode_payload.get('wrapup_level')} "
            f"expected_level={status['pinned_level']}"
        )

    prior_arc_state_dir = os.environ.get("ARC_STATE_DIR")
    os.environ["ARC_STATE_DIR"] = str(runtime.arc_state_dir)
    try:
        clear_analysis_level_pin(runtime.active_agent_dir())
        visible_level = sync_workspace_level_view(
            runtime.active_agent_dir(),
            game_id=runtime.active_game_id or str(runtime.args.game_id).strip(),
            frontier_level=int(status["frontier_level"]),
        )
    finally:
        if prior_arc_state_dir is None:
            os.environ.pop("ARC_STATE_DIR", None)
        else:
            os.environ["ARC_STATE_DIR"] = prior_arc_state_dir

    if visible_level != int(status["frontier_level"]):
        raise RuntimeError(
            "failed to release solved-level wrap-up pin to frontier level: "
            f"expected_frontier={status['frontier_level']} visible_level={visible_level}"
        )
    runtime.refresh_dynamic_super_env()
    runtime.log(
        "[harness] supervisor certified solved-level wrap-up complete: "
        f"pinned_level={status['pinned_level']} frontier_level={status['frontier_level']} "
        f"target_mode={target_mode}"
    )
