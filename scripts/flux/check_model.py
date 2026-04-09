from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from common import load_runtime_meta, read_json_stdin, write_json_stdout


def _classify_infrastructure_failure(message: str) -> dict | None:
    text = str(message or "")
    lowered = text.lower()
    if "visible_sequence_surface.py" in text or "preserve_local_sequence_surface" in text:
        return {
            "type": "sequence_surface_race",
            "message": text,
        }
    if "shutil.error" in lowered and "no such file or directory" in lowered:
        return {
            "type": "snapshot_copy_race",
            "message": text,
        }
    if '"type": "missing_sequence"' in text or "sequence not found under:" in text:
        return {
            "type": "missing_sequence_surface",
            "message": text,
        }
    if '"type": "missing_sequences"' in text or "missing sequences dir:" in text:
        return {
            "type": "missing_sequence_surface",
            "message": text,
        }
    normalized = text.replace('\\', '/')
    if 'filenotfounderror' in lowered and '/sequences/' in normalized:
        return {
            "type": "missing_sequence_surface",
            "message": text,
        }
    return None


def _read_frontier_level(model_workspace: Path) -> int:
    level_meta = model_workspace / "level_current" / "meta.json"
    frontier_level = 1
    try:
        payload = json.loads(level_meta.read_text()) if level_meta.exists() else {}
        frontier_level = int(payload.get("level", 1) or 1)
    except Exception:
        frontier_level = 1
    visible_levels = [
        level_num
        for level_num in _levels_with_sequences(model_workspace)
        if _frontier_level_ready(model_workspace, level_num)
    ]
    if visible_levels:
        frontier_level = max(frontier_level, max(visible_levels))
    return frontier_level


def _frontier_level_ready(model_workspace: Path, frontier_level: int) -> bool:
    level_dir = model_workspace / f"level_{frontier_level}"
    if not level_dir.exists() or not level_dir.is_dir():
        return False
    required = [
        level_dir / "initial_state.hex",
        level_dir / "initial_state.meta.json",
    ]
    return all(path.exists() for path in required)


def _run_compare(
    model_workspace: Path,
    meta: dict,
    child_env: dict[str, str],
    frontier_level: int | None = None,
    *,
    include_reset_ended: bool = False,
) -> tuple[int, dict]:
    command = ["python3", "model.py", "compare_sequences", "--game-id", str(meta["game_id"])]
    if frontier_level is not None:
        command.extend(["--level", str(frontier_level)])
    if include_reset_ended:
        command.append("--include-reset-ended")
    proc = subprocess.run(
        command,
        cwd=str(model_workspace),
        text=True,
        capture_output=True,
        env=child_env,
    )
    payload = json.loads(proc.stdout or "{}")
    if proc.returncode != 0:
        if isinstance(payload, dict):
            return proc.returncode, payload
        raise RuntimeError(proc.stderr or proc.stdout)
    if not isinstance(payload, dict):
        raise RuntimeError("compare_sequences returned non-object JSON")
    return proc.returncode, payload


def _is_frontier_discovery_payload(compare_payload: dict, *, frontier_level: int) -> bool:
    error = compare_payload.get("error") if isinstance(compare_payload.get("error"), dict) else {}
    if str(error.get("type", "") or "") != "no_eligible_sequences":
        return False
    try:
        payload_level = int(compare_payload.get("level", 0) or 0)
    except Exception:
        payload_level = 0
    if payload_level != frontier_level:
        return False
    skipped = compare_payload.get("skipped_sequences") if isinstance(compare_payload.get("skipped_sequences"), list) else []
    if not skipped:
        return False
    return all(isinstance(item, dict) and str(item.get("reason", "") or "") == "wrong_level" for item in skipped)


def _levels_with_sequences(model_workspace: Path) -> list[int]:
    levels: list[int] = []
    for level_dir in sorted(model_workspace.glob("level_*")):
        if not level_dir.is_dir():
            continue
        name = level_dir.name
        if not name.startswith("level_") or name == "level_current":
            continue
        try:
            level_num = int(name.split("_", 1)[1])
        except Exception:
            continue
        if any((level_dir / "sequences").glob("seq_*.json")):
            levels.append(level_num)
    return levels


def _sequence_payload_for_report(model_workspace: Path, report: dict) -> dict | None:
    sequence_id = str(report.get("sequence_id", "")).strip()
    if not sequence_id:
        return None
    try:
        level = int(report.get("level", 1) or 1)
    except Exception:
        level = 1
    sequence_path = model_workspace / f"level_{level}" / "sequences" / f"{sequence_id}.json"
    if not sequence_path.exists():
        return None
    try:
        payload = json.loads(sequence_path.read_text())
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _sequence_frontier_level(sequence_payload: dict) -> int:
    try:
        frontier_level = int(sequence_payload.get("level", 1) or 1)
    except Exception:
        frontier_level = 1
    actions = sequence_payload.get("actions") if isinstance(sequence_payload.get("actions"), list) else []
    for action in actions:
        if not isinstance(action, dict):
            continue
        try:
            level_before = int(action.get("level_before", frontier_level) or frontier_level)
        except Exception:
            level_before = frontier_level
        try:
            level_after = int(action.get("level_after", level_before) or level_before)
        except Exception:
            level_after = level_before
        frontier_level = max(frontier_level, level_after)
        try:
            completed_before = int(action.get("levels_completed_before", 0) or 0)
            completed_after = int(action.get("levels_completed_after", completed_before) or completed_before)
        except Exception:
            completed_before = 0
            completed_after = 0
        if completed_after > completed_before or bool(action.get("level_complete_after", False)):
            frontier_level = max(frontier_level, max(level_before, level_after) + 1)
    return frontier_level


def _annotate_compare_payload_frontier(model_workspace: Path, compare_payload: dict) -> dict:
    payload = dict(compare_payload)
    reports = payload.get("reports") if isinstance(payload.get("reports"), list) else []
    matched_frontier = 0
    matched_levels: set[int] = set()
    annotated_reports: list[dict] = []
    for report in reports:
        if not isinstance(report, dict):
            annotated_reports.append(report)
            continue
        annotated = dict(report)
        sequence_payload = _sequence_payload_for_report(model_workspace, annotated)
        if sequence_payload:
            sequence_frontier = _sequence_frontier_level(sequence_payload)
            annotated["frontier_level_after_sequence"] = sequence_frontier
            annotated["sequence_completed_level"] = sequence_frontier > int(sequence_payload.get("level", 1) or 1)
            if bool(annotated.get("matched")):
                matched_frontier = max(matched_frontier, sequence_frontier)
                try:
                    matched_levels.add(int(sequence_payload.get("level", 1) or 1))
                except Exception:
                    pass
        annotated_reports.append(annotated)
    if annotated_reports:
        payload["reports"] = annotated_reports
    try:
        compare_level = int(payload.get("level", 1) or 1)
    except Exception:
        compare_level = 1
    payload["frontier_level"] = max(compare_level, matched_frontier)
    if matched_levels:
        payload["matched_levels"] = sorted(matched_levels)
    return payload


def _summarize_frontier_progress(reports: list[dict]) -> tuple[int, int, str | None, int | None, str | None]:
    by_level: dict[int, list[dict]] = {}
    for report in reports:
        try:
            level_num = int(report.get("level", 1) or 1)
        except Exception:
            level_num = 1
        by_level.setdefault(level_num, []).append(report)
    if not by_level:
        return 1, 0, None, None, None
    highest_level = max(by_level)
    ordered_reports = sorted(
        by_level[highest_level],
        key=lambda report: str(report.get("sequence_id", "")),
    )
    contiguous = 0
    first_failing_sequence_id = None
    first_failing_step = None
    first_failing_reason = None
    for report in ordered_reports:
        if bool(report.get("matched")):
            contiguous += 1
            continue
        first_failing_sequence_id = str(report.get("sequence_id", "") or "") or None
        try:
            first_failing_step = int(report.get("divergence_step", 0) or 0) or None
        except Exception:
            first_failing_step = None
        first_failing_reason = str(report.get("divergence_reason", "") or "") or None
        break
    return highest_level, contiguous, first_failing_sequence_id, first_failing_step, first_failing_reason


def _aggregate_compare_payloads(model_workspace: Path, compare_payloads: list[dict], *, visible_frontier_level: int) -> dict:
    reports: list[dict] = []
    skipped_sequences: list[dict] = []
    requested_sequences = 0
    eligible_sequences = 0
    compared_sequences = 0
    diverged_sequences = 0
    all_match = True
    covered_sequence_ids: list[str] = []
    frontier_level = visible_frontier_level
    payload_state: dict = {}
    matched_levels: set[int] = set()
    for compare_payload in compare_payloads:
        requested_sequences += int(compare_payload.get("requested_sequences", 0) or 0)
        eligible_sequences += int(compare_payload.get("eligible_sequences", 0) or 0)
        compared_sequences += int(compare_payload.get("compared_sequences", 0) or 0)
        diverged_sequences += int(compare_payload.get("diverged_sequences", 0) or 0)
        all_match = all_match and bool(compare_payload.get("all_match"))
        reports.extend(report for report in compare_payload.get("reports", []) if isinstance(report, dict))
        skipped_sequences.extend(item for item in compare_payload.get("skipped_sequences", []) if isinstance(item, dict))
        try:
            frontier_level = max(frontier_level, int(compare_payload.get("frontier_level", 0) or 0))
        except Exception:
            pass
        payload_state = compare_payload
    for report in reports:
        try:
            level_num = int(report.get("level", 1) or 1)
        except Exception:
            level_num = 1
        if bool(report.get("matched")):
            covered_sequence_ids.append(f"level_{level_num}:{str(report.get('sequence_id', '') or '')}")
            matched_levels.add(level_num)
        try:
            frontier_level = max(frontier_level, int(report.get("frontier_level_after_sequence", 0) or 0))
        except Exception:
            pass
    progress_level, frontier_contiguous, frontier_first_failing_sequence_id, frontier_first_failing_step, frontier_first_failing_reason = _summarize_frontier_progress(reports)
    return {
        "ok": True,
        "action": "compare_sequences",
        "level": progress_level,
        "frontier_level": frontier_level,
        "requested_sequences": requested_sequences,
        "eligible_sequences": eligible_sequences,
        "skipped_sequences": skipped_sequences,
        "compared_sequences": compared_sequences,
        "diverged_sequences": diverged_sequences,
        "all_match": all_match,
        "covered_sequence_ids": covered_sequence_ids,
        "matched_levels": sorted(matched_levels),
        "frontier_contiguous_matched_sequences": frontier_contiguous,
        "frontier_first_failing_sequence_id": frontier_first_failing_sequence_id,
        "frontier_first_failing_step": frontier_first_failing_step,
        "frontier_first_failing_reason": frontier_first_failing_reason,
        **{
            key: value
            for key, value in payload_state.items()
            if key not in {
                "reports",
                "skipped_sequences",
                "requested_sequences",
                "eligible_sequences",
                "compared_sequences",
                "diverged_sequences",
                "all_match",
                "level",
                "frontier_level",
            }
        },
        "reports": reports,
    }


def main() -> None:
    payload = read_json_stdin()
    model_output = payload.get("modelOutput") if isinstance(payload.get("modelOutput"), dict) else {}
    workspace_root = str(payload.get("workspaceRoot", ""))
    meta = load_runtime_meta(workspace_root)
    model_revision_id = str(payload.get("modelRevisionId") or "").strip()
    evidence_bundle_path = str(payload.get("evidenceBundlePath") or "").strip()
    model_workspace = Path(str(meta["model_workspace_dir"]))
    if model_revision_id:
        revision_workspace = Path(workspace_root) / "flux" / "model" / "revisions" / model_revision_id / "workspace" / model_workspace.name
        if revision_workspace.exists():
            model_workspace = revision_workspace
    model_script = model_workspace / "model.py"
    if not model_script.exists():
        write_json_stdout(
            {
                "accepted": False,
                "message": f"missing model.py in durable workspace: {model_workspace}",
                "model_output": model_output,
            }
        )
        return
    (Path(workspace_root) / "flux").mkdir(parents=True, exist_ok=True)
    compare_workspace_root = Path(tempfile.mkdtemp(prefix="flux-compare-", dir=Path(workspace_root) / "flux"))
    compare_workspace = compare_workspace_root / model_workspace.name
    if compare_workspace.exists():
        shutil.rmtree(compare_workspace, ignore_errors=True)
    shutil.copytree(model_workspace, compare_workspace)
    bundle_path = Path(evidence_bundle_path) if evidence_bundle_path else None
    bundle_workspace = bundle_path / "workspace" / model_workspace.name if bundle_path else None
    if bundle_workspace and bundle_workspace.exists():
        for child in bundle_workspace.iterdir():
            destination = compare_workspace / child.name
            if destination.exists() or destination.is_symlink():
                if destination.is_dir() and not destination.is_symlink():
                    shutil.rmtree(destination, ignore_errors=True)
                else:
                    destination.unlink(missing_ok=True)
            if child.is_dir():
                shutil.copytree(child, destination)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(child, destination)
    child_env = dict(os.environ)
    child_env["ARC_CONFIG_DIR"] = str(meta["run_config_dir"])
    bundle_state_dir = bundle_path / "arc_state" if bundle_path else None
    child_env["ARC_STATE_DIR"] = str(bundle_state_dir or (Path(workspace_root) / "supervisor" / "arc"))
    child_env["ARC_MODEL_DISABLE_CANONICAL_ARTIFACTS"] = "1"
    child_env["PATH"] = f"{meta['run_bin_dir']}:{child_env.get('PATH', '')}"
    visible_frontier_level = _read_frontier_level(compare_workspace)
    levels_to_compare = _levels_with_sequences(compare_workspace)
    if not levels_to_compare:
        try:
            _code, compare_payload = _run_compare(
                compare_workspace,
                meta,
                child_env,
                frontier_level=None,
                include_reset_ended=True,
            )
        except Exception as exc:
            infra = _classify_infrastructure_failure(str(exc))
            write_json_stdout(
                {
                    "accepted": False,
                    "message": f"compare_sequences failed: {exc}",
                    "model_output": model_output,
                    "infrastructure_failure": infra,
                }
            )
            return
        compare_for_acceptance = _annotate_compare_payload_frontier(compare_workspace, compare_payload)
        accepted = bool(compare_for_acceptance.get("all_match"))
        summary = str(model_output.get("summary", "")).strip()
        if not summary and accepted:
            summary = f"compare_sequences passed through frontier level {int(compare_for_acceptance.get('frontier_level', visible_frontier_level) or visible_frontier_level or 1)}"
        write_json_stdout(
            {
                "accepted": accepted,
                "message": summary or ("compare_sequences passed" if accepted else "compare_sequences did not pass"),
                "model_output": model_output,
                "compare_payload": compare_for_acceptance,
            }
        )
        return
    compare_payloads: list[dict] = []
    frontier_discovery_payload: dict | None = None
    for level_num in levels_to_compare:
        try:
            _code, compare_payload = _run_compare(
                compare_workspace,
                meta,
                child_env,
                frontier_level=level_num,
                include_reset_ended=True,
            )
        except Exception as exc:
            infra = _classify_infrastructure_failure(str(exc))
            write_json_stdout(
                {
                    "accepted": False,
                    "message": f"compare_sequences failed at level {level_num}: {exc}",
                    "model_output": model_output,
                    "infrastructure_failure": infra,
                }
            )
            return
        if not bool(compare_payload.get("ok", True)):
            if _is_frontier_discovery_payload(compare_payload, frontier_level=visible_frontier_level):
                frontier_discovery_payload = compare_payload
                continue
            write_json_stdout(
                {
                    "accepted": False,
                    "message": f"compare_sequences failed at level {level_num}: {json.dumps(compare_payload, indent=2)}",
                    "model_output": model_output,
                    "compare_payload": compare_payload,
                }
            )
            return
        compare_payloads.append(_annotate_compare_payload_frontier(compare_workspace, compare_payload))

    compare_for_acceptance = _aggregate_compare_payloads(compare_workspace, compare_payloads, visible_frontier_level=visible_frontier_level)
    accepted = bool(compare_for_acceptance.get("all_match"))
    if frontier_discovery_payload and accepted:
        compare_for_acceptance["frontier_discovery"] = True
        compare_for_acceptance["frontier_level"] = max(
            int(compare_for_acceptance.get("frontier_level", 0) or 0),
            int(frontier_discovery_payload.get("level", visible_frontier_level) or visible_frontier_level or 1),
        )
        compare_for_acceptance["requested_sequences"] = int(compare_for_acceptance.get("requested_sequences", 0) or 0) + int(frontier_discovery_payload.get("requested_sequences", 0) or 0)
        compare_for_acceptance["eligible_sequences"] = int(compare_for_acceptance.get("eligible_sequences", 0) or 0) + int(frontier_discovery_payload.get("eligible_sequences", 0) or 0)
        compare_for_acceptance["skipped_sequences"] = list(compare_for_acceptance.get("skipped_sequences") or []) + list(frontier_discovery_payload.get("skipped_sequences") or [])
    frontier_level = int(compare_for_acceptance.get("frontier_level", visible_frontier_level) or visible_frontier_level or 1)
    summary = str(model_output.get("summary", "")).strip()
    if not summary and accepted:
        summary = f"compare_sequences passed through frontier level {frontier_level}"
    write_json_stdout(
        {
            "accepted": accepted,
            "message": summary or ("compare_sequences passed" if accepted else "compare_sequences did not pass"),
            "model_output": model_output,
            "compare_payload": compare_for_acceptance,
        }
    )


if __name__ == "__main__":
    main()
