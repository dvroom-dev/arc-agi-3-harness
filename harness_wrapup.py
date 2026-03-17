from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from arc_model_runtime.utils import (
    clear_analysis_level_pin,
    load_analysis_level_pin,
    load_visible_level_status,
    sync_workspace_level_view,
)


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


def _parse_iso_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None


def _iter_visible_json_payloads(level_current_dir: Path) -> list[tuple[Path, dict[str, Any]]]:
    payloads: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(level_current_dir.rglob("*.json")):
        payload = _read_json_if_exists(path)
        if isinstance(payload, dict):
            payloads.append((path, payload))
    for path in sorted(level_current_dir.rglob("*.jsonl")):
        if not path.exists():
            continue
        for idx, line in enumerate(path.read_text().splitlines(), start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except Exception:
                continue
            if isinstance(payload, dict):
                payloads.append((path.with_name(f"{path.name}:{idx}"), payload))
    return payloads


def load_super_active_mode_impl(runtime) -> str | None:
    payload = _read_json_if_exists(runtime.run_dir / "super" / "state.json")
    if not isinstance(payload, dict):
        return None
    mode = str(payload.get("activeMode") or "").strip()
    return mode or None


def load_super_active_transition_payload_impl(runtime) -> dict[str, str]:
    payload = _read_json_if_exists(runtime.run_dir / "super" / "state.json")
    if not isinstance(payload, dict):
        return {}
    raw = payload.get("activeTransitionPayload")
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
    coverage_passed = str((coverage or {}).get("status") or "") == "pass"
    compare_clean = (compare or {}).get("all_match") is True
    compare_level: int | None = None
    try:
        compare_level = int((compare or {}).get("level"))
    except Exception:
        compare_level = None
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
        "ready_to_certify": bool(active and coverage_passed and compare_ready),
    }


def repair_stale_wrapup_mode_impl(runtime) -> str | None:
    status = load_wrapup_status_impl(runtime)
    if not bool(status["active"]):
        return None

    state_path = runtime.run_dir / "super" / "state.json"
    state_payload = _read_json_if_exists(state_path)
    if not isinstance(state_payload, dict):
        return None

    active_mode = str(state_payload.get("activeMode") or "").strip()
    if not active_mode or active_mode in {"theory", "code_model"}:
        return None

    transition_payload = state_payload.get("activeTransitionPayload")
    if isinstance(transition_payload, dict):
        certified = str(transition_payload.get("wrapup_certified") or "").strip().lower()
        if certified == "true":
            return None

    pin_payload = load_analysis_level_pin(runtime.active_agent_dir())
    pin_updated_at = _parse_iso_timestamp((pin_payload or {}).get("updated_at_utc"))
    state_updated_at = _parse_iso_timestamp(state_payload.get("updatedAt"))
    if pin_updated_at is None or state_updated_at is None or state_updated_at >= pin_updated_at:
        return None

    state_payload["activeMode"] = "theory"
    state_payload["activeModePayload"] = {}
    state_payload["activeTransitionPayload"] = {}
    state_path.write_text(json.dumps(state_payload, indent=2) + "\n")
    return active_mode


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
    if not bool(status["active"]):
        return

    game_dir = runtime.active_agent_dir()
    pinned_level = int(status["pinned_level"])
    frontier_level = int(status["frontier_level"])

    level_current_meta = _read_json_if_exists(game_dir / "level_current" / "meta.json") or {}
    level_status = load_visible_level_status(game_dir) or {}
    model_status = _read_json_if_exists(game_dir / "model_status.json") or {}
    model_state = model_status.get("state") if isinstance(model_status.get("state"), dict) else {}
    compare = _read_json_if_exists(game_dir / "current_compare.json") or {}
    visible_compare = _read_json_if_exists(
        game_dir / "level_current" / "sequence_compare" / "current_compare.json"
    ) or {}

    level_current_level = _int_or_none(level_current_meta.get("level"))
    level_current_pinned = level_current_meta.get("analysis_level_pinned")
    model_current_level = _int_or_none(model_state.get("current_level"))
    model_levels_completed = _int_or_none(model_state.get("levels_completed"))
    model_available_levels = model_state.get("available_model_levels")
    compare_level = _int_or_none(compare.get("level"))

    errors: list[str] = []
    if level_current_level != pinned_level:
        errors.append(f"level_current.level={level_current_level} expected={pinned_level}")
    if "frontier_level" in level_current_meta:
        errors.append("level_current.frontier_level must not be visible while pin is active")
    if level_current_pinned is not True:
        errors.append(f"level_current.analysis_level_pinned={level_current_pinned} expected=True")
    if not isinstance(level_status, dict) or not level_status:
        errors.append("level_current.analysis_level_status.json missing while pin is active")
    else:
        if _int_or_none(level_status.get("visible_level")) != pinned_level:
            errors.append(
                "analysis_level_status.visible_level="
                f"{_int_or_none(level_status.get('visible_level'))} expected={pinned_level}"
            )
        if level_status.get("analysis_level_pinned") is not True:
            errors.append(
                "analysis_level_status.analysis_level_pinned="
                f"{level_status.get('analysis_level_pinned')} expected=True"
            )
        if level_status.get("frontier_hidden_by_pin") is not True:
            errors.append(
                "analysis_level_status.frontier_hidden_by_pin="
                f"{level_status.get('frontier_hidden_by_pin')} expected=True"
            )
        if level_status.get("next_allowed_operation") != "finalize_pinned_level":
            errors.append(
                "analysis_level_status.next_allowed_operation="
                f"{level_status.get('next_allowed_operation')} expected=finalize_pinned_level"
            )
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
    visible_compare_level = _int_or_none(visible_compare.get("level"))
    if visible_compare and visible_compare_level != pinned_level:
        errors.append(
            "level_current.sequence_compare.current_compare.level="
            f"{visible_compare_level} expected={pinned_level}"
        )
    if compare and visible_compare:
        for key in ("all_match", "compared_sequences", "diverged_sequences"):
            if compare.get(key) != visible_compare.get(key):
                errors.append(
                    "level_current.sequence_compare.current_compare mismatch on "
                    f"{key}: root={compare.get(key)!r} visible={visible_compare.get(key)!r}"
                )
        root_reports = compare.get("reports")
        visible_reports = visible_compare.get("reports")
        if isinstance(root_reports, list) and isinstance(visible_reports, list):
            root_summary = [
                (
                    str(report.get("sequence_id")),
                    bool(report.get("matched")),
                    _int_or_none(report.get("actions_compared")),
                    _int_or_none(report.get("divergence_step")),
                )
                for report in root_reports
                if isinstance(report, dict)
            ]
            visible_summary = [
                (
                    str(report.get("sequence_id")),
                    bool(report.get("matched")),
                    _int_or_none(report.get("actions_compared")),
                    _int_or_none(report.get("divergence_step")),
                )
                for report in visible_reports
                if isinstance(report, dict)
            ]
            if root_summary != visible_summary:
                errors.append(
                    "level_current.sequence_compare.current_compare reports diverged from root current_compare"
                )

    visible_completed = max(0, pinned_level - 1)
    for path, payload in _iter_visible_json_payloads(game_dir / "level_current"):
        if "frontier_level" in payload:
            errors.append(f"{path} leaks frontier_level")
        for key in ("current_level", "level_after", "level_before", "level"):
            value = _int_or_none(payload.get(key))
            if value is not None and value > pinned_level:
                errors.append(f"{path} leaks {key}={value} beyond pinned_level={pinned_level}")
        for key in ("levels_completed", "levels_completed_before", "levels_completed_after"):
            value = _int_or_none(payload.get(key))
            if value is not None and value > visible_completed:
                errors.append(
                    f"{path} leaks {key}={value} beyond visible_levels_completed={visible_completed}"
                )

    if frontier_level > pinned_level:
        level_transition_path = game_dir / "level_current" / "level_transition.json"
        transition_payload = _read_json_if_exists(level_transition_path)
        if not isinstance(transition_payload, dict):
            errors.append("level_current.level_transition.json missing while frontier is hidden by pin")
        elif transition_payload.get("analysis_level_boundary_redacted") is not True:
            errors.append(
                "level_current.level_transition.json missing analysis_level_boundary_redacted=true"
            )

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
    if not target_mode:
        return

    transition_payload = load_super_active_transition_payload_impl(runtime)
    certified = str(transition_payload.get("wrapup_certified") or "").strip().lower() == "true"
    certified_level = _int_or_none(transition_payload.get("wrapup_level"))
    if not certified:
        if target_mode in {"theory", "code_model"}:
            return
        raise RuntimeError(
            "cannot leave solved-level wrap-up without explicit supervisor certification: "
            f"target_mode={target_mode} "
            f"wrapup_certified={transition_payload.get('wrapup_certified')} "
            f"wrapup_level={transition_payload.get('wrapup_level')} "
            f"expected_level={status['pinned_level']}"
        )

    if not bool(status["ready_to_certify"]):
        raise RuntimeError(
            "cannot leave solved-level wrap-up while pin is active: "
            f"target_mode={target_mode} "
            f"pinned_level={status['pinned_level']} "
            f"frontier_level={status['frontier_level']} "
            f"coverage_passed={status['coverage_passed']} "
            f"compare_clean={status['compare_clean']} "
            f"compare_level={status['compare_level']}"
        )

    if certified_level != int(status["pinned_level"]):
        raise RuntimeError(
            "cannot leave solved-level wrap-up without explicit supervisor certification: "
            f"target_mode={target_mode} "
            f"wrapup_certified={transition_payload.get('wrapup_certified')} "
            f"wrapup_level={transition_payload.get('wrapup_level')} "
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
