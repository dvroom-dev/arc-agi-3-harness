from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from .utils import action_from_name, diff_payload, read_hex_grid, resolve_level_dir


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
    report: dict[str, Any] = {
        "level": int(level),
        "sequence_id": seq_id,
        "actions_total": int(len(actions)),
        "actions_compared": 0,
        "matched": True,
        "divergence_step": None,
        "divergence_reason": "",
        "game_step_diff": None,
        "model_step_diff": None,
        "state_diff": None,
        "transition_mismatch": None,
    }
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
        model_state_before = str(compare_env.state)
        model_levels_before = int(compare_env.levels_completed)
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
        compare_env.step(action_from_name(action_name), data=action_data, reasoning=None)
        model_after = np.array(compare_env.grid, dtype=np.int8, copy=True)
        model_state_after = str(compare_env.state)
        model_levels_after = int(compare_env.levels_completed)
        report["actions_compared"] = int(local_step)
        if (
            model_state_before != game_state_before
            or model_state_after != game_state_after
            or model_levels_before != game_levels_before
            or model_levels_after != game_levels_after
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
                },
                "model": {
                    "state_before": model_state_before,
                    "state_after": model_state_after,
                    "levels_completed_before": model_levels_before,
                    "levels_completed_after": model_levels_after,
                },
            }
            report["game_step_diff"] = diff_payload(game_before, game_after)
            report["model_step_diff"] = diff_payload(model_before, model_after)
            report["state_diff"] = diff_payload(game_after, model_after)
            break
        if model_after.shape != game_after.shape or not np.array_equal(model_after, game_after):
            report["matched"] = False
            report["divergence_step"] = local_step
            report["divergence_reason"] = "after_state_mismatch"
            report["game_step_diff"] = diff_payload(game_before, game_after)
            report["model_step_diff"] = diff_payload(model_before, model_after)
            report["state_diff"] = diff_payload(game_after, model_after)
            break
    return report


def report_md(report: dict) -> str:
    lines = [f"# Sequence Comparison: {report['sequence_id']}", ""]
    lines.append(f"- level: {int(report['level'])}")
    lines.append(f"- actions_total: {int(report['actions_total'])}")
    lines.append(f"- actions_compared: {int(report['actions_compared'])}")
    lines.append(f"- matched: {bool(report['matched'])}")
    if report.get("divergence_step") is not None:
        lines.append(f"- divergence_step: {int(report['divergence_step'])}")
        lines.append(f"- divergence_reason: {str(report.get('divergence_reason', ''))}")
    for section, value in (
        ("Game Step Diff", report.get("game_step_diff")),
        ("Model Step Diff", report.get("model_step_diff")),
        ("State Diff (Game After vs Model After)", report.get("state_diff")),
        ("Transition Mismatch", report.get("transition_mismatch")),
    ):
        if not value:
            continue
        lines.extend(["", f"## {section}", "```json", json.dumps(value, indent=2), "```"])
    return "\n".join(lines).rstrip() + "\n"


def compare_sequences(
    session,
    *,
    level: int | None,
    sequence_id: str | None,
    include_reset_ended: bool = False,
    include_level_regressions: bool = False,
) -> tuple[dict, int]:
    target_level = int(level) if level is not None else int(session.env.current_level)
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
        report_file = compare_root / f"{report['sequence_id']}.md"
        report_file.write_text(report_md(report))
        try:
            report["report_file"] = str(report_file.relative_to(session.game_dir))
        except ValueError:
            report["report_file"] = str(report_file)
        reports.append(report)
        if not bool(report.get("matched", False)):
            diverged += 1

    session._persist_to_disk("compare_sequences")
    return {
        "ok": True,
        "action": "compare_sequences",
        "level": int(target_level),
        "requested_sequences": int(len(seq_files)),
        "eligible_sequences": int(len(eligible_payloads)),
        "skipped_sequences": skipped_sequences,
        "compared_sequences": int(len(reports)),
        "diverged_sequences": int(diverged),
        "all_match": bool(diverged == 0),
        "include_reset_ended": bool(include_reset_ended),
        "include_level_regressions": bool(include_level_regressions),
        "reports": reports,
        **session.get_state(),
    }, 0
