from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from typing import Any

import numpy as np

from .sequence_compare_render import current_compare_markdown, report_md
from .utils import (
    action_from_name,
    canonical_game_artifacts_dir,
    clear_analysis_level_pin,
    diff_payload,
    load_frontier_level_from_arc_state,
    load_analysis_level_pin,
    read_hex_grid,
    resolve_level_dir,
    sanitize_visible_json_payload,
    sync_workspace_level_view,
    update_analysis_level_pin,
)


def _sequence_has_level_regression(payload: dict) -> bool:
    actions = list(payload.get("actions", []) or [])
    for action in actions:
        if not isinstance(action, dict):
            continue
        before = action.get("levels_completed_before")
        after = action.get("levels_completed_after")
        try:
            before_i = int(before)
            after_i = int(after)
        except Exception:
            continue
        if after_i < before_i:
            return True
    return False


def _sequence_eligibility(
    *,
    target_level: int,
    payload: dict,
    include_reset_ended: bool,
    include_level_regressions: bool,
) -> tuple[bool, str]:
    try:
        payload_level = int(payload.get("level", target_level) or target_level)
    except Exception:
        payload_level = int(target_level)
    if payload_level != int(target_level):
        return False, "wrong_level"
    actions = list(payload.get("actions", []) or [])
    if not actions:
        return False, "no_actions"
    end_reason = str(payload.get("end_reason", "")).strip().lower()
    if end_reason == "reset_level" and not include_reset_ended:
        return False, "reset_ended"
    if _sequence_has_level_regression(payload) and not include_level_regressions:
        return False, "level_regression"
    return True, "ok"


def compare_one_sequence(session, *, level: int, level_dir: Path, payload: dict) -> dict:
    from .session import ModelEnv

    compare_env = ModelEnv(session.env.game_id, session.game_dir, session.hooks)
    compare_env.levels_completed = int(level) - 1
    compare_env._init_level(level)
    seq_id = str(payload.get("sequence_id", "seq_unknown"))
    actions = list(payload.get("actions", []) or [])
    end_reason = str(payload.get("end_reason", "") or "").strip().lower()
    report: dict[str, Any] = {
        "level": int(level),
        "sequence_id": seq_id,
        "actions_total": int(len(list(payload.get("actions", []) or []))),
        "actions_compared": 0,
        "matched": True,
        "divergence_step": None,
        "divergence_reason": "",
        "game_step_diff": None,
        "model_step_diff": None,
        "state_diff": None,
        "transition_mismatch": None,
    }
    boundary_transition_compared = False
    for action in actions:
        local_step = int(action.get("local_step", 0) or 0)
        files = action.get("files", {}) if isinstance(action.get("files"), dict) else {}
        before_path = level_dir / str(files.get("before_state_hex", ""))
        after_path = level_dir / str(files.get("after_state_hex", ""))
        if not before_path.exists() or not after_path.exists():
            report["matched"] = False
            report["divergence_step"] = local_step
            report["divergence_reason"] = "missing_action_files"
            break
        game_before = read_hex_grid(before_path)
        game_after = read_hex_grid(after_path)
        model_before = np.array(compare_env.grid, dtype=np.int8, copy=True)
        game_state_before = str(action.get("state_before", "") or "")
        game_state_after = str(action.get("state_after", "") or "")
        game_levels_before = int(action.get("levels_completed_before", 0) or 0)
        game_levels_after = int(action.get("levels_completed_after", 0) or 0)
        game_level_complete_before = bool(action.get("level_complete_before", False))
        game_level_complete_after = bool(
            action.get(
                "level_complete_after",
                game_levels_after > game_levels_before or game_state_after == "WIN",
            )
        )
        game_game_over_before = bool(action.get("game_over_before", game_state_before == "GAME_OVER"))
        game_game_over_after = bool(action.get("game_over_after", game_state_after == "GAME_OVER"))
        model_state_before = str(compare_env.state)
        model_levels_before = int(compare_env.levels_completed)
        model_level_complete_before = bool(
            getattr(compare_env, "last_step_level_complete", False) or str(compare_env.state) == "WIN"
        )
        model_game_over_before = bool(
            getattr(compare_env, "last_step_game_over", False) or str(compare_env.state) == "GAME_OVER"
        )
        if model_before.shape != game_before.shape or not np.array_equal(model_before, game_before):
            report["matched"] = False
            report["divergence_step"] = local_step
            report["divergence_reason"] = "before_state_mismatch"
            report["game_step_diff"] = diff_payload(game_before, game_after)
            report["model_step_diff"] = diff_payload(model_before, model_before)
            report["state_diff"] = diff_payload(game_before, model_before)
            break
        action_name = str(action.get("action_name", "")).strip()
        action_data = action.get("action_data", {}) if isinstance(action.get("action_data"), dict) else {}
        compare_env.level_complete = False
        compare_env.last_step_level_complete = False
        compare_env.hooks.apply_action(
            compare_env,
            action_from_name(action_name),
            data=action_data,
            reasoning=None,
        )
        model_after = np.array(compare_env.grid, dtype=np.int8, copy=True)
        model_level_complete_after = bool(compare_env.hooks.is_level_complete(compare_env))
        model_game_over_after = bool(compare_env.hooks.is_game_over(compare_env) or str(compare_env.state) == "GAME_OVER")
        compare_env.level_complete = model_level_complete_after
        compare_env.last_step_level_complete = model_level_complete_after
        compare_env.game_over = model_game_over_after
        compare_env.last_step_game_over = model_game_over_after
        model_levels_after = int(compare_env.levels_completed) + (1 if model_level_complete_after else 0)
        if model_game_over_after:
            model_state_after = "GAME_OVER"
        else:
            model_state_after = "WIN" if model_levels_after >= int(compare_env.win_levels) else str(compare_env.state)
        completion_boundary = (
            game_level_complete_after
            or model_level_complete_after
            or int(action.get("level_after", game_levels_after + 1) or (game_levels_after + 1))
            > int(action.get("level_before", game_levels_before + 1) or (game_levels_before + 1))
        )
        report["actions_compared"] = int(local_step)
        if (
            model_state_before != game_state_before
            or model_state_after != game_state_after
            or model_levels_before != game_levels_before
            or model_level_complete_before != game_level_complete_before
            or model_level_complete_after != game_level_complete_after
            or model_game_over_before != game_game_over_before
            or model_game_over_after != game_game_over_after
            or (
                not completion_boundary
                and model_levels_after != game_levels_after
            )
        ):
            report["matched"] = False
            report["divergence_step"] = local_step
            report["divergence_reason"] = "state_transition_mismatch"
            report["transition_mismatch"] = {
                "game": {
                    "state_before": game_state_before,
                    "state_after": game_state_after,
                    "levels_completed_before": game_levels_before,
                    "levels_completed_after": game_levels_after,
                    "level_complete_before": game_level_complete_before,
                    "level_complete_after": game_level_complete_after,
                    "game_over_before": game_game_over_before,
                    "game_over_after": game_game_over_after,
                },
                "model": {
                    "state_before": model_state_before,
                    "state_after": model_state_after,
                    "levels_completed_before": model_levels_before,
                    "levels_completed_after": model_levels_after,
                    "level_complete_before": model_level_complete_before,
                    "level_complete_after": model_level_complete_after,
                    "game_over_before": model_game_over_before,
                    "game_over_after": model_game_over_after,
                },
            }
            if not completion_boundary:
                report["game_step_diff"] = diff_payload(game_before, game_after)
                report["model_step_diff"] = diff_payload(model_before, model_after)
                report["state_diff"] = diff_payload(game_after, model_after)
            break
        if game_level_complete_after or model_level_complete_after:
            boundary_transition_compared = True
            report["comparison_stop_reason"] = "post_level_complete_state_diff_excluded"
            break
        if model_after.shape != game_after.shape or not np.array_equal(model_after, game_after):
            report["matched"] = False
            report["divergence_step"] = local_step
            report["divergence_reason"] = "after_state_mismatch"
            report["game_step_diff"] = diff_payload(game_before, game_after)
            report["model_step_diff"] = diff_payload(model_before, model_after)
            report["state_diff"] = diff_payload(game_after, model_after)
            break
        compare_env.levels_completed = model_levels_after
        compare_env.state = model_state_after
    if boundary_transition_compared and report.get("comparison_stop_reason") is None:
        report["comparison_stop_reason"] = "post_level_complete_state_diff_excluded"
    return report


def _redact_payload_for_pinned_level(payload: dict[str, Any], *, pinned_level: int | None) -> dict[str, Any]:
    if pinned_level is None:
        return payload
    sanitized = sanitize_visible_json_payload(payload, visible_level=int(pinned_level))
    return sanitized if isinstance(sanitized, dict) else payload


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    tmp.replace(path)


def _export_compare_reports(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    exported: list[dict[str, Any]] = []
    for report in reports:
        if not isinstance(report, dict):
            continue
        item = dict(report)
        if "end_reason" in item:
            item["sequence_end_reason"] = item.pop("end_reason")
        exported.append(item)
    return exported


def _persist_current_compare(session, payload: dict[str, Any]) -> None:
    pin = load_analysis_level_pin(session.game_dir)
    pinned_level: int | None = None
    if isinstance(pin, dict):
        try:
            pinned_level = int(pin.get("level"))
        except Exception:
            pinned_level = None
    payload = _redact_payload_for_pinned_level(payload, pinned_level=pinned_level)
    reports = payload.get("reports")
    if not isinstance(reports, list):
        reports = []
    exported_reports = _export_compare_reports(reports)
    exported_compare_payload = dict(payload)
    exported_compare_payload["reports"] = exported_reports
    summary_payload = {
        "level": int(payload.get("level", session.env.current_level)),
        "command": ["python3", "model.py", "compare_sequences"],
        "return_code": 0 if bool(payload.get("ok")) else 1,
        "compare_ok": bool(payload.get("ok")),
        "all_match": bool(payload.get("all_match")),
        "compared_sequences": int(payload.get("compared_sequences", 0) or 0),
        "diverged_sequences": int(payload.get("diverged_sequences", 0) or 0),
        "reports": exported_reports,
        "mismatched_reports": [
            report for report in exported_reports if isinstance(report, dict) and report.get("matched") is False
        ],
        "current_runtime_state": {
            "state": str(payload.get("state", "")),
            "current_level": int(payload.get("current_level", session.env.current_level)),
            "levels_completed": int(payload.get("levels_completed", 0) or 0),
            "level_complete": bool(payload.get("level_complete", False)),
            "current_level_complete": bool(payload.get("current_level_complete", False)),
            "last_step_level_complete": bool(payload.get("last_step_level_complete", False)),
            "last_completed_level": payload.get("last_completed_level"),
            "game_over": bool(payload.get("game_over", False)),
            "current_level_game_over": bool(payload.get("current_level_game_over", False)),
            "last_step_game_over": bool(payload.get("last_step_game_over", False)),
            "last_game_over_level": payload.get("last_game_over_level"),
        },
        "compare_payload": exported_compare_payload,
        "stdout": "",
        "stderr": "",
    }
    json_text = json.dumps(summary_payload, indent=2) + "\n"
    md_text = current_compare_markdown(summary_payload)
    _write_text_atomic(session.game_dir / "current_compare.json", json_text)
    _write_text_atomic(session.game_dir / "current_compare.md", md_text)

    level_current = session.game_dir / "level_current" / "sequence_compare"
    _write_text_atomic(level_current / "current_compare.json", json_text)
    _write_text_atomic(level_current / "current_compare.md", md_text)

    for report in reports:
        if not isinstance(report, dict):
            continue
        sequence_id = str(report.get("sequence_id") or "").strip()
        if not sequence_id:
            continue
        report_text = report_md(report)
        _write_text_atomic(level_current / f"{sequence_id}.md", report_text)

    analysis_level_dir = session.game_dir / "analysis_level" / "sequence_compare"
    if int(payload.get("level", session.env.current_level)) != int(session.env.current_level):
        _write_text_atomic(analysis_level_dir / "current_compare.json", json_text)
        _write_text_atomic(analysis_level_dir / "current_compare.md", md_text)
        for report in reports:
            if not isinstance(report, dict):
                continue
            sequence_id = str(report.get("sequence_id") or "").strip()
            if not sequence_id:
                continue
            _write_text_atomic(analysis_level_dir / f"{sequence_id}.md", report_md(report))

    level_compare = resolve_level_dir(session.game_dir, int(payload.get("level", session.env.current_level)))
    if level_compare is not None:
        compare_dir = level_compare / "sequence_compare"
        _write_text_atomic(compare_dir / "current_compare.json", json_text)
        _write_text_atomic(compare_dir / "current_compare.md", md_text)
        for report in reports:
            if not isinstance(report, dict):
                continue
            sequence_id = str(report.get("sequence_id") or "").strip()
            if not sequence_id:
                continue
            _write_text_atomic(compare_dir / f"{sequence_id}.md", report_md(report))

    canonical_artifacts = canonical_game_artifacts_dir(session.game_dir)
    if canonical_artifacts is not None:
        canonical_compare_dir = canonical_artifacts / f"level_{int(payload.get('level', session.env.current_level))}" / "sequence_compare"
        _write_text_atomic(canonical_compare_dir / "current_compare.json", json_text)
        _write_text_atomic(canonical_compare_dir / "current_compare.md", md_text)
        for report in reports:
            if not isinstance(report, dict):
                continue
            sequence_id = str(report.get("sequence_id") or "").strip()
            if not sequence_id:
                continue
            _write_text_atomic(canonical_compare_dir / f"{sequence_id}.md", report_md(report))

def compare_sequences(
    session,
    *,
    level: int | None,
    sequence_id: str | None,
    include_reset_ended: bool = False,
    include_level_regressions: bool = False,
) -> tuple[dict, int]:
    pin = load_analysis_level_pin(session.game_dir)
    pinned_level = None
    if isinstance(pin, dict):
        try:
            pinned_level = int(pin.get("level"))
        except Exception:
            pinned_level = None
    target_level = int(pinned_level) if pinned_level is not None else (
        int(level) if level is not None else int(session.env.current_level)
    )
    level_dir = resolve_level_dir(session.game_dir, target_level)
    if level_dir is None:
        return session._error(
            "compare_sequences",
            "missing_level_dir",
            f"missing level dir for level {target_level}",
        ), 1
    seq_root = level_dir / "sequences"
    if not seq_root.exists():
        return session._error(
            "compare_sequences",
            "missing_sequences",
            f"missing sequences dir: {seq_root}",
        ), 1
    seq_files = [seq_root / f"{sequence_id}.json"] if sequence_id else sorted(seq_root.glob("seq_*.json"))
    if not seq_files or not all(path.exists() for path in seq_files):
        return session._error(
            "compare_sequences",
            "missing_sequence",
            f"sequence not found under: {seq_root}",
        ), 1

    skipped_sequences: list[dict[str, Any]] = []
    eligible_payloads: list[tuple[Path, dict]] = []
    for seq_file in seq_files:
        try:
            payload = json.loads(seq_file.read_text())
        except Exception as exc:
            skipped_sequences.append(
                {
                    "sequence_file": str(seq_file.name),
                    "reason": "invalid_sequence_json",
                    "error": str(exc),
                }
            )
            continue
        if not isinstance(payload, dict):
            skipped_sequences.append(
                {
                    "sequence_file": str(seq_file.name),
                    "reason": "invalid_sequence_payload",
                }
            )
            continue
        eligible, reason = _sequence_eligibility(
            target_level=target_level,
            payload=payload,
            include_reset_ended=include_reset_ended,
            include_level_regressions=include_level_regressions,
        )
        if not eligible:
            skipped_sequences.append(
                {
                    "sequence_id": str(payload.get("sequence_id", seq_file.stem)),
                    "sequence_file": str(seq_file.name),
                    "end_reason": str(payload.get("end_reason", "")),
                    "reason": reason,
                }
            )
            continue
        eligible_payloads.append((seq_file, payload))

    if not eligible_payloads:
        details = (
            f"no eligible sequences under {seq_root} "
            f"(requested={len(seq_files)} skipped={len(skipped_sequences)})"
        )
        err, code = session._error("compare_sequences", "no_eligible_sequences", details), 1
        err["level"] = int(target_level)
        err["requested_sequences"] = int(len(seq_files))
        err["eligible_sequences"] = 0
        err["skipped_sequences"] = skipped_sequences
        err["include_reset_ended"] = bool(include_reset_ended)
        err["include_level_regressions"] = bool(include_level_regressions)
        return err, code

    compare_root = level_dir / "sequence_compare"
    compare_root.mkdir(parents=True, exist_ok=True)
    reports: list[dict] = []
    diverged = 0
    for _, payload in eligible_payloads:
        report = compare_one_sequence(session, level=target_level, level_dir=level_dir, payload=payload)
        report["start_action_index"] = int(payload.get("start_action_index", 0) or 0)
        report["end_action_index"] = int(payload.get("end_action_index", report["start_action_index"]) or report["start_action_index"])
        report["end_reason"] = str(payload.get("end_reason", "") or "")
        report_file = compare_root / f"{report['sequence_id']}.md"
        report_file.write_text(report_md(report))
        report_surface_dir = (
            "level_current/sequence_compare"
            if int(target_level) == int(session.env.current_level)
            else "analysis_level/sequence_compare"
        )
        report["report_file"] = f"{report_surface_dir}/{report['sequence_id']}.md"
        reports.append(report)
        if not bool(report.get("matched", False)):
            diverged += 1

    session._persist_to_disk("compare_sequences")
    payload = {
        "ok": True,
        "action": "compare_sequences",
        "level": int(target_level),
        "requested_sequences": int(len(seq_files)),
        "eligible_sequences": int(len(eligible_payloads)),
        "skipped_sequences": skipped_sequences,
        "compared_sequences": int(len(reports)),
        "diverged_sequences": int(diverged),
        "all_match": bool(diverged == 0),
        "analysis_level_pinned": bool(pinned_level is not None),
        "analysis_level_pin": pin,
        "include_reset_ended": bool(include_reset_ended),
        "include_level_regressions": bool(include_level_regressions),
        "reports": reports,
        **session.get_status_state(),
    }
    payload = _redact_payload_for_pinned_level(payload, pinned_level=pinned_level)
    _persist_current_compare(session, payload)
    if bool(payload["all_match"]) and isinstance(pin, dict) and int(pin.get("level", -1)) == int(target_level):
        update_analysis_level_pin(
            session.game_dir,
            {"last_compare_all_match": True, "last_compare_level": int(target_level)},
        )
    frontier_level = load_frontier_level_from_arc_state()
    if frontier_level is not None:
        sync_workspace_level_view(
            session.game_dir,
            game_id=str(session.game_id),
            frontier_level=int(frontier_level),
        )
    return payload, 0
