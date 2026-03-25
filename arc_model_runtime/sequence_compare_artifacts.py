from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .sequence_compare_render import current_compare_markdown, report_md
from .utils import (
    load_analysis_state,
    canonical_game_artifacts_dir,
    load_analysis_level_pin,
    resolve_level_dir,
    sanitize_visible_json_payload,
)


def _redact_payload_for_pinned_level(payload: dict, *, pinned_level: int | None) -> dict:
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


def persist_current_compare(session, payload: dict[str, Any]) -> None:
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
    compare_level = int(payload.get("level", session.env.current_level))
    summary_payload = {
        "level": compare_level,
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
    analysis_state = load_analysis_state(session.game_dir)
    analysis_level = None
    frontier_level = None
    if isinstance(analysis_state, dict):
        try:
            analysis_level = int(analysis_state.get("analysis_level"))
        except Exception:
            analysis_level = None
        try:
            frontier_level = int(analysis_state.get("frontier_level"))
        except Exception:
            frontier_level = None
    write_to_analysis_surface = (
        analysis_level is not None
        and int(compare_level) == analysis_level
        and frontier_level is not None
        and analysis_level != frontier_level
    )
    if not write_to_analysis_surface:
        level_current = session.game_dir / "level_current" / "sequence_compare"
        _write_text_atomic(level_current / "current_compare.json", json_text)
        _write_text_atomic(level_current / "current_compare.md", md_text)
        for report in reports:
            if not isinstance(report, dict):
                continue
            sequence_id = str(report.get("sequence_id") or "").strip()
            if sequence_id:
                _write_text_atomic(level_current / f"{sequence_id}.md", report_md(report))
    analysis_level_dir = session.game_dir / "analysis_level" / "sequence_compare"
    if write_to_analysis_surface or compare_level != int(session.env.current_level):
        _write_text_atomic(analysis_level_dir / "current_compare.json", json_text)
        _write_text_atomic(analysis_level_dir / "current_compare.md", md_text)
        for report in reports:
            if not isinstance(report, dict):
                continue
            sequence_id = str(report.get("sequence_id") or "").strip()
            if sequence_id:
                _write_text_atomic(analysis_level_dir / f"{sequence_id}.md", report_md(report))

    level_compare = resolve_level_dir(session.game_dir, compare_level)
    if level_compare is not None:
        compare_dir = level_compare / "sequence_compare"
        _write_text_atomic(compare_dir / "current_compare.json", json_text)
        _write_text_atomic(compare_dir / "current_compare.md", md_text)
        for report in reports:
            if not isinstance(report, dict):
                continue
            sequence_id = str(report.get("sequence_id") or "").strip()
            if sequence_id:
                _write_text_atomic(compare_dir / f"{sequence_id}.md", report_md(report))

    canonical_artifacts = canonical_game_artifacts_dir(session.game_dir)
    if canonical_artifacts is not None:
        canonical_compare_dir = canonical_artifacts / f"level_{compare_level}" / "sequence_compare"
        _write_text_atomic(canonical_compare_dir / "current_compare.json", json_text)
        _write_text_atomic(canonical_compare_dir / "current_compare.md", md_text)
        for report in reports:
            if not isinstance(report, dict):
                continue
            sequence_id = str(report.get("sequence_id") or "").strip()
            if sequence_id:
                _write_text_atomic(canonical_compare_dir / f"{sequence_id}.md", report_md(report))
