from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from arc_model_runtime.utils import sync_workspace_level_view

LEVEL_COMPLETE_MODEL_MISMATCH_MARKER = "__ARC_INTERCEPT_LEVEL_COMPLETE_MODEL_MISMATCH__"
COMPARE_CLEAN_INTERCEPT_MARKER = "__ARC_INTERCEPT_COMPARE_CLEAN__"
COMPARE_MISMATCH_INTERCEPT_MARKER = "__ARC_INTERCEPT_COMPARE_MISMATCH__"
COMPARE_RESULTS_BEGIN_MARKER = "__ARC_COMPARE_RESULTS_BEGIN__"
COMPARE_RESULTS_END_MARKER = "__ARC_COMPARE_RESULTS_END__"


def _current_level_from_result(result: object) -> int | None:
    if not isinstance(result, dict):
        return None
    try:
        return int(result.get("current_level"))
    except Exception:
        return None


def result_has_real_game_action(action: str, result: object) -> bool:
    action_name = str(action or "").strip().lower()
    if action_name != "exec":
        return False
    if not isinstance(result, dict) or not bool(result.get("ok")):
        return False
    try:
        return int(result.get("steps_executed", 0) or 0) > 0
    except Exception:
        return False


def _safe_slug(value: str) -> str:
    text = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in str(value or "").strip())
    return text.strip("._") or "game"


def _artifacts_game_dir(*, cwd: Path, game_id: str) -> Path:
    state_dir = str(os.getenv("ARC_STATE_DIR", "") or "").strip()
    if not state_dir:
        return cwd
    return Path(state_dir).expanduser() / "game_artifacts" / f"game_{_safe_slug(game_id)}"


def _compare_target_level(result: dict) -> int | None:
    try:
        levels_gained = int(result.get("levels_gained_in_call", 0) or 0)
    except Exception:
        levels_gained = 0
    if levels_gained > 0:
        try:
            completed_level = int(result.get("levels_completed", 0) or 0)
        except Exception:
            completed_level = 0
        if completed_level > 0:
            return completed_level
    return _current_level_from_result(result)


def _write_compare_artifact(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp")
    tmp_path.write_text(text, encoding="utf-8")
    tmp_path.replace(path)


def _render_current_compare_markdown(summary_payload: dict) -> str:
    compare_payload = summary_payload.get("compare_payload")
    parsed_compare = compare_payload if isinstance(compare_payload, dict) else {}
    reports = parsed_compare.get("reports")
    skipped_sequences = parsed_compare.get("skipped_sequences")
    report_lines = [
        f"# Current Compare (Level {int(summary_payload['level'])})",
        "",
        f"- level: {int(summary_payload['level'])}",
        f"- return_code: {int(summary_payload['return_code'])}",
        f"- compare_ok: {str(bool(summary_payload['compare_ok'])).lower()}",
        f"- all_match: {str(bool(summary_payload['all_match'])).lower()}",
        f"- compared_sequences: {int(summary_payload['compared_sequences'])}",
        f"- diverged_sequences: {int(summary_payload['diverged_sequences'])}",
    ]
    current_runtime_state = summary_payload.get("current_runtime_state")
    if isinstance(current_runtime_state, dict):
        report_lines.extend(
            [
                "",
                "## Current Runtime State",
                f"- state: {str(current_runtime_state.get('state', ''))}",
                f"- current_level: {current_runtime_state.get('current_level')}",
                f"- levels_completed: {current_runtime_state.get('levels_completed')}",
                f"- level_complete: {str(bool(current_runtime_state.get('level_complete', False))).lower()}",
                f"- game_over: {str(bool(current_runtime_state.get('game_over', False))).lower()}",
            ]
        )

    def _append_diff_summary(title: str, payload: object) -> None:
        if not isinstance(payload, dict):
            return
        report_lines.extend(["", f"### {title}"])
        if bool(payload.get("shape_mismatch")):
            report_lines.append("- shape_mismatch: true")
            report_lines.append(f"- before_shape: {payload.get('before_shape')}")
            report_lines.append(f"- after_shape: {payload.get('after_shape')}")
            return
        changed_pixels = payload.get("changed_pixels")
        report_lines.append(f"- changed_pixels: {changed_pixels}")
        changes = payload.get("changes")
        if isinstance(changes, list) and changes:
            sample = changes[:5]
            report_lines.append("- sample_changes:")
            for change in sample:
                if not isinstance(change, dict):
                    continue
                report_lines.append(
                    f"  - ({change.get('row')},{change.get('col')}): "
                    f"{change.get('before')}->{change.get('after')}"
                )
            if len(changes) > len(sample):
                report_lines.append(f"  - ... {len(changes) - len(sample)} more changes")

    if isinstance(reports, list) and reports:
        report_lines.extend(["", "## Sequence Reports"])
        for report in reports:
            if not isinstance(report, dict):
                continue
            sequence_id = str(report.get("sequence_id", "unknown"))
            report_lines.append(f"- sequence_id: {sequence_id}")
            report_lines.append(f"  matched: {str(bool(report.get('matched'))).lower()}")
            if report.get("sequence_end_reason"):
                report_lines.append(f"  sequence_end_reason: {report.get('sequence_end_reason')}")
            elif report.get("end_reason"):
                report_lines.append(f"  sequence_end_reason: {report.get('end_reason')}")
            if report.get("report_file"):
                report_lines.append(f"  report_file: {report.get('report_file')}")
            if not bool(report.get("matched", False)):
                report_lines.append(f"  divergence_step: {report.get('divergence_step')}")
                report_lines.append(f"  divergence_reason: {report.get('divergence_reason')}")
                _append_diff_summary("Game Step Diff", report.get("game_step_diff"))
                _append_diff_summary("Model Step Diff", report.get("model_step_diff"))
                _append_diff_summary("State Diff", report.get("state_diff"))

    if isinstance(skipped_sequences, list) and skipped_sequences:
        report_lines.extend(["", "## Skipped Sequences"])
        for skipped in skipped_sequences:
            if not isinstance(skipped, dict):
                continue
            seq_id = str(skipped.get("sequence_id", skipped.get("sequence_file", "unknown")) or "unknown")
            reason = str(skipped.get("reason", "") or "").strip() or "unknown"
            report_lines.append(f"- {seq_id}: {reason}")

    report_lines.extend(
        [
            "",
            "## Full Payload",
            "- current_compare.json contains the full machine-readable compare payload.",
            "- Per-sequence markdown reports are listed above under `report_file`.",
            "- `sequence_end_reason` is historical sequence metadata, not the current live state.",
        ]
    )
    return "\n".join(report_lines).rstrip() + "\n"


def _export_compare_reports(reports: list[dict]) -> list[dict]:
    exported: list[dict] = []
    for report in reports:
        if not isinstance(report, dict):
            continue
        item = dict(report)
        if "end_reason" in item:
            item["sequence_end_reason"] = item.pop("end_reason")
        exported.append(item)
    return exported


def _write_current_compare_artifacts(
    *,
    cwd: Path,
    target_level: int,
    artifacts_dir: Path,
    summary_payload: dict,
) -> None:
    report_text = _render_current_compare_markdown(summary_payload)
    json_text = json.dumps(summary_payload, indent=2) + "\n"
    level_dir = artifacts_dir / f"level_{int(target_level)}"
    canonical_md = level_dir / "sequence_compare" / "current_compare.md"
    canonical_json = level_dir / "sequence_compare" / "current_compare.json"
    _write_compare_artifact(cwd / "current_compare.md", report_text)
    _write_compare_artifact(cwd / "current_compare.json", json_text)

    level_current_dir = cwd / "level_current" / "sequence_compare"
    _write_compare_artifact(level_current_dir / "current_compare.md", report_text)
    _write_compare_artifact(level_current_dir / "current_compare.json", json_text)

    try:
        _write_compare_artifact(canonical_md, report_text)
        _write_compare_artifact(canonical_json, json_text)
    except PermissionError:
        # Agent-facing compare artifacts are already written under the workspace.
        # Do not convert a successful real-game step into a failed exec result
        # just because the control-plane mirror path is not writable.
        return
    except OSError as exc:
        if getattr(exc, "errno", None) == 13:
            return
        raise


def run_exec_compare_intercept(cwd: Path, result: object) -> str | None:
    if not isinstance(result, dict):
        return None
    if not bool(result.get("ok")):
        return None
    if not result_has_real_game_action("exec", result):
        return None

    target_level = _compare_target_level(result)
    if target_level is None or target_level <= 0:
        return None

    model_py = cwd / "model.py"
    if not model_py.exists():
        return None
    game_id = str(result.get("game_id", "") or os.getenv("ARC_ACTIVE_GAME_ID", "")).strip() or "game"
    artifacts_dir = _artifacts_game_dir(cwd=cwd, game_id=game_id)
    level_dir = artifacts_dir / f"level_{int(target_level)}"
    if not level_dir.exists():
        return None

    cmd = [
        sys.executable,
        str(model_py),
        "compare_sequences",
        "--game-id",
        game_id,
        "--level",
        str(int(target_level)),
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        text=True,
        capture_output=True,
    )
    compare_stdout = str(proc.stdout or "")
    compare_stderr = str(proc.stderr or "")
    parsed_payload: dict | None = None
    try:
        parsed = json.loads(compare_stdout) if compare_stdout.strip() else None
        if isinstance(parsed, dict):
            parsed_payload = parsed
    except Exception:
        parsed_payload = None

    compare_ok = bool(parsed_payload.get("ok")) if isinstance(parsed_payload, dict) else False
    all_match = bool(parsed_payload.get("all_match")) if isinstance(parsed_payload, dict) else False
    compared_sequences = 0
    if isinstance(parsed_payload, dict):
        try:
            compared_sequences = int(parsed_payload.get("compared_sequences", 0) or 0)
        except Exception:
            compared_sequences = 0
    try:
        diverged_sequences = int(parsed_payload.get("diverged_sequences", 0) or 0) if isinstance(parsed_payload, dict) else 0
    except Exception:
        diverged_sequences = 0
    mismatch = (proc.returncode != 0) or (not compare_ok) or (not all_match) or (compared_sequences <= 0)
    exported_reports = _export_compare_reports(
        list(parsed_payload.get("reports", []) or []) if isinstance(parsed_payload, dict) else []
    )
    exported_compare_payload = dict(parsed_payload) if isinstance(parsed_payload, dict) else None
    if isinstance(exported_compare_payload, dict):
        exported_compare_payload["reports"] = exported_reports
    summary_payload = {
        "level": int(target_level),
        "command": cmd,
        "return_code": int(proc.returncode),
        "compare_ok": bool(compare_ok),
        "all_match": bool(all_match),
        "compared_sequences": int(compared_sequences),
        "diverged_sequences": int(diverged_sequences),
        "reports": exported_reports,
        "mismatched_reports": [
            report
            for report in exported_reports
            if isinstance(report, dict) and report.get("matched") is False
        ]
        if exported_reports
        else [],
        "current_runtime_state": {
            "state": str(result.get("state", "")),
            "current_level": result.get("current_level"),
            "levels_completed": result.get("levels_completed"),
            "level_complete": bool(result.get("level_complete", False)),
            "game_over": bool(result.get("game_over", False)),
        },
        "compare_payload": exported_compare_payload,
        "stdout": compare_stdout,
        "stderr": compare_stderr,
    }
    _write_current_compare_artifacts(
        cwd=cwd,
        target_level=int(target_level),
        artifacts_dir=artifacts_dir,
        summary_payload=summary_payload,
    )
    try:
        levels_gained = int(result.get("levels_gained_in_call", 0) or 0)
    except Exception:
        levels_gained = 0
    try:
        levels_completed = int(result.get("levels_completed", 0) or 0)
    except Exception:
        levels_completed = 0
    if levels_gained > 0:
        current_level = _current_level_from_result(result)
        if current_level is not None:
            sync_workspace_level_view(
                cwd,
                game_id=game_id,
                frontier_level=int(current_level),
            )

    compare_file = level_dir / "sequence_compare" / "current_compare.md"
    try:
        compare_rel = str(compare_file.relative_to(artifacts_dir))
    except Exception:
        compare_rel = str(compare_file)
    if mismatch:
        marker = (
            LEVEL_COMPLETE_MODEL_MISMATCH_MARKER
            if levels_gained > 0
            else COMPARE_MISMATCH_INTERCEPT_MARKER
        )
        compare_text = _render_current_compare_markdown(summary_payload)
        return (
            f"# {marker} level={int(target_level)} levels_completed={int(levels_completed)} "
            f"compare_file={compare_rel}\n"
            f"# {COMPARE_RESULTS_BEGIN_MARKER}\n"
            f"{compare_text}"
            f"# {COMPARE_RESULTS_END_MARKER}\n"
        )
    if str(result.get("state", "")).strip().upper() == "WIN":
        return None
    if levels_gained <= 0:
        return None
    return (
        f"# {COMPARE_CLEAN_INTERCEPT_MARKER} level={int(target_level)} "
        f"compare_file={compare_rel}\n"
    )
