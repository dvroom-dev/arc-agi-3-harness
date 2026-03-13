from __future__ import annotations

import json
from typing import Any


def _append_diff_summary(lines: list[str], title: str, payload: object) -> None:
    if not isinstance(payload, dict):
        return
    lines.extend(["", f"## {title}"])
    if bool(payload.get("shape_mismatch")):
        lines.append("- shape_mismatch: true")
        lines.append(f"- before_shape: {payload.get('before_shape')}")
        lines.append(f"- after_shape: {payload.get('after_shape')}")
        return
    lines.append(f"- changed_pixels: {payload.get('changed_pixels')}")
    changes = payload.get("changes")
    if isinstance(changes, list) and changes:
        lines.append("- sample_changes:")
        for change in changes[:5]:
            if not isinstance(change, dict):
                continue
            lines.append(
                "  - "
                f"({change.get('row')},{change.get('col')}): "
                f"{change.get('before')} -> {change.get('after')}"
            )
        remaining = max(0, len(changes) - 5)
        if remaining:
            lines.append(f"- remaining_changes_not_shown: {remaining}")


def report_md(report: dict[str, Any]) -> str:
    lines = [f"# Sequence Comparison: {report['sequence_id']}", ""]
    lines.append(f"- level: {int(report['level'])}")
    lines.append(f"- actions_total: {int(report['actions_total'])}")
    lines.append(f"- actions_compared: {int(report['actions_compared'])}")
    lines.append(f"- matched: {bool(report['matched'])}")
    if report.get("start_action_index") is not None:
        lines.append(f"- start_action_index: {int(report['start_action_index'])}")
    if report.get("end_action_index") is not None:
        lines.append(f"- end_action_index: {int(report['end_action_index'])}")
    if report.get("end_reason"):
        lines.append(f"- end_reason: {str(report['end_reason'])}")
    if report.get("divergence_step") is not None:
        lines.append(f"- divergence_step: {int(report['divergence_step'])}")
        lines.append(f"- divergence_reason: {str(report.get('divergence_reason', ''))}")
    lines.extend(
        [
            "",
            "## Diff Legend",
            "- Game Step Diff: game before -> game after for the mismatching step.",
            "- Model Step Diff: model before -> model after for the same step.",
            "- State Diff (Game After vs Model After): game after -> model after.",
        ]
    )
    transition_mismatch = report.get("transition_mismatch")
    if transition_mismatch:
        lines.extend(["", "## Transition Mismatch", "```json", json.dumps(transition_mismatch, indent=2), "```"])
    _append_diff_summary(lines, "Game Step Diff", report.get("game_step_diff"))
    _append_diff_summary(lines, "Model Step Diff", report.get("model_step_diff"))
    _append_diff_summary(lines, "State Diff (Game After vs Model After)", report.get("state_diff"))
    return "\n".join(lines).rstrip() + "\n"


def current_compare_markdown(summary_payload: dict[str, Any]) -> str:
    lines = [
        f"# Current Compare (Level {int(summary_payload['level'])})",
        "",
        f"- compare_ok: {str(bool(summary_payload['compare_ok'])).lower()}",
        f"- all_match: {str(bool(summary_payload['all_match'])).lower()}",
        f"- compared_sequences: {int(summary_payload['compared_sequences'])}",
        f"- diverged_sequences: {int(summary_payload['diverged_sequences'])}",
    ]
    reports = summary_payload.get("reports")
    if isinstance(reports, list) and reports:
        lines.extend(["", "## Reports"])
        for report in reports:
            if not isinstance(report, dict):
                continue
            lines.extend(
                [
                    "",
                    f"### {str(report.get('sequence_id', 'seq_unknown'))}",
                    f"- matched: {str(bool(report.get('matched'))).lower()}",
                    f"- actions_total: {int(report.get('actions_total', 0) or 0)}",
                    f"- actions_compared: {int(report.get('actions_compared', 0) or 0)}",
                ]
            )
            if report.get("start_action_index") is not None:
                lines.append(f"- start_action_index: {int(report['start_action_index'])}")
            if report.get("end_action_index") is not None:
                lines.append(f"- end_action_index: {int(report['end_action_index'])}")
            if report.get("end_reason"):
                lines.append(f"- end_reason: {str(report['end_reason'])}")
            if report.get("divergence_step") is not None:
                lines.append(f"- divergence_step: {int(report['divergence_step'])}")
            reason = str(report.get("divergence_reason", "") or "").strip()
            if reason:
                lines.append(f"- divergence_reason: {reason}")
            if report.get("report_file"):
                lines.append(f"- report_file: {report['report_file']}")
    lines.extend(
        [
            "",
            "## Diff Legend",
            "- Game Step Diff: game before -> game after for the mismatching step.",
            "- Model Step Diff: model before -> model after for the same step.",
            "- State Diff (Game After vs Model After): game after -> model after.",
            "- Sequence indices are absolute across the level; they do not restart after reset_level. Use `end_reason` and `start_action_index` to see where a reset-bounded sequence begins.",
        ]
    )
    lines.extend(
        [
            "",
            "## Full Payload",
            "- current_compare.json contains the full machine-readable compare payload.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"
