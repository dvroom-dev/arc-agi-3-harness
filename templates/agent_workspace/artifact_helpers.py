"""Helpers for navigating run-local compare and sequence artifacts.

These utilities only index files already visible in the agent workspace.
They do not add game-specific heuristics.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import numpy as np


def analysis_level_pin_path(game_dir: str | Path) -> Path:
    return coerce_path(game_dir) / ".analysis_level_pin.json"


def analysis_state_path(game_dir: str | Path) -> Path:
    return coerce_path(game_dir) / "analysis_state.json"


def load_analysis_state(game_dir: str | Path) -> dict[str, Any] | None:
    path = analysis_state_path(game_dir)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def load_analysis_level_pin(game_dir: str | Path) -> dict[str, Any] | None:
    path = analysis_level_pin_path(game_dir)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def write_analysis_level_pin(game_dir: str | Path, payload: dict[str, Any]) -> None:
    path = analysis_level_pin_path(game_dir)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n")
    tmp.replace(path)


def clear_analysis_level_pin(game_dir: str | Path) -> None:
    analysis_level_pin_path(game_dir).unlink(missing_ok=True)


def coerce_path(path_like: str | Path) -> Path:
    return path_like if isinstance(path_like, Path) else Path(path_like)


def display_path(game_dir: str | Path, path: str | Path) -> str:
    game_dir = coerce_path(game_dir)
    path = coerce_path(path)
    try:
        return str(path.relative_to(game_dir))
    except ValueError:
        return str(path)


def load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(coerce_path(path).read_text())


def load_hex_rows(path: str | Path) -> list[str]:
    return [line.strip().upper() for line in coerce_path(path).read_text().splitlines() if line.strip()]


def hex_rows_to_grid(rows: list[str]) -> np.ndarray:
    return np.array([[int(ch, 16) for ch in row] for row in rows], dtype=np.int8)


def load_hex_grid(path: str | Path) -> np.ndarray:
    return hex_rows_to_grid(load_hex_rows(path))


def level_dir(game_dir: str | Path, level: int) -> Path:
    game_dir = coerce_path(game_dir)
    analysis_state = load_analysis_state(game_dir)
    if isinstance(analysis_state, dict):
        try:
            analysis_level = int(analysis_state.get("analysis_level"))
        except Exception:
            analysis_level = None
        try:
            frontier_level = int(analysis_state.get("frontier_level"))
        except Exception:
            frontier_level = None
        analysis_dir = game_dir / "analysis_level"
        if (
            analysis_dir.exists()
            and analysis_dir.is_dir()
            and analysis_level is not None
            and int(level) == analysis_level
            and (frontier_level is None or analysis_level != frontier_level)
        ):
            return analysis_dir
    workspace_level = game_dir / f"level_{int(level)}"
    return workspace_level


def current_level_dir(game_dir: str | Path) -> Path:
    return coerce_path(game_dir) / "level_current"


def current_level_number(game_dir: str | Path) -> int | None:
    return _meta_level(current_level_dir(game_dir) / "meta.json")


def _meta_level(meta_path: Path) -> int | None:
    if not meta_path.exists():
        return None
    try:
        payload = json.loads(meta_path.read_text())
    except json.JSONDecodeError:
        return None
    try:
        return int(payload.get("level"))
    except (TypeError, ValueError):
        return None


def load_level_hex_rows(game_dir: str | Path, level: int, *, kind: str) -> list[str]:
    game_dir = coerce_path(game_dir)
    candidates = [level_dir(game_dir, level) / f"{kind}_state.hex"]
    current_hex = current_level_dir(game_dir) / f"{kind}_state.hex"
    if current_hex.exists():
        current_level = _meta_level(current_level_dir(game_dir) / "meta.json")
        if current_level is None or current_level == int(level):
            candidates.append(current_hex)
    for path in candidates:
        if path.exists():
            return load_hex_rows(path)
    return []


def iter_level_sequences(game_dir: str | Path, level: int) -> Iterable[dict[str, Any]]:
    sequences_dir = level_dir(game_dir, level) / "sequences"
    if not sequences_dir.exists():
        return []
    payloads: list[dict[str, Any]] = []
    for path in sorted(sequences_dir.glob("seq_*.json")):
        try:
            payloads.append(load_json(path))
        except Exception:
            continue
    return payloads


def iter_seen_state_files(game_dir: str | Path, level: int) -> list[dict[str, str]]:
    game_dir = coerce_path(game_dir)
    out: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(label: str, path: Path) -> None:
        rel = str(path.relative_to(game_dir))
        if rel in seen or not path.exists():
            return
        seen.add(rel)
        out.append({"label": label, "path": rel})

    level_root = level_dir(game_dir, level)
    add(f"level_{level}:initial_state", level_root / "initial_state.hex")

    for sequence in iter_level_sequences(game_dir, level):
        sequence_id = str(sequence.get("sequence_id") or "").strip()
        actions = sequence.get("actions")
        if not sequence_id or not isinstance(actions, list):
            continue
        for action in actions:
            if not isinstance(action, dict):
                continue
            local_step = int(action.get("local_step") or 0)
            files = action.get("files") if isinstance(action.get("files"), dict) else {}
            before_rel = files.get("before_state_hex")
            after_rel = files.get("after_state_hex")
            if isinstance(before_rel, str) and before_rel:
                add(f"{sequence_id}:step_{local_step}:before", level_root / before_rel)
            if isinstance(after_rel, str) and after_rel:
                add(f"{sequence_id}:step_{local_step}:after", level_root / after_rel)

    current_root = current_level_dir(game_dir)
    if current_level_number(game_dir) == int(level):
        add(f"level_{level}:current_state", current_root / "current_state.hex")

    return out


def current_compare_json_path(game_dir: str | Path) -> Path:
    return coerce_path(game_dir) / "current_compare.json"


def current_compare_markdown_path(game_dir: str | Path) -> Path:
    return coerce_path(game_dir) / "current_compare.md"


def coverage_report_paths(game_dir: str | Path, level: int) -> dict[str, Path]:
    game_dir = coerce_path(game_dir)
    canonical_dir = level_dir(game_dir, int(level))
    canonical_json = canonical_dir / "component_coverage.json"
    canonical_md = canonical_dir / "component_coverage.md"
    root_json = game_dir / "component_coverage.json"
    root_md = game_dir / "component_coverage.md"
    return {
        "canonical_json": canonical_json,
        "canonical_md": canonical_md,
        "root_json": root_json,
        "root_md": root_md,
    }


def normalize_current_compare_payload(compare_payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(compare_payload)
    nested = normalized.get("compare_payload")
    if isinstance(nested, dict):
        merged = dict(nested)
        for key, value in normalized.items():
            if key == "compare_payload":
                continue
            merged.setdefault(key, value)
        normalized = merged

    reports = normalized.get("reports")
    if not isinstance(reports, list):
        reports = []
    normalized["reports"] = reports
    normalized["mismatched_reports"] = [
        report for report in reports if isinstance(report, dict) and report.get("matched") is False
    ]
    return normalized


def load_current_compare(game_dir: str | Path) -> dict[str, Any]:
    return normalize_current_compare_payload(load_json(current_compare_json_path(game_dir)))


def summarize_current_compare(game_dir: str | Path) -> dict[str, Any]:
    game_dir = coerce_path(game_dir)
    compare_payload = load_current_compare(game_dir)
    mismatch = first_mismatch_report(compare_payload)
    level = compare_payload.get("level")
    try:
        level_value = int(level) if level is not None else None
    except (TypeError, ValueError):
        level_value = None
    summary: dict[str, Any] = {
        "status": "mismatch" if mismatch else "clean",
        "level": level_value,
        "all_match": compare_payload.get("all_match"),
        "compared_sequences": compare_payload.get("compared_sequences"),
        "diverged_sequences": compare_payload.get("diverged_sequences"),
        "compare_json": str(current_compare_json_path(game_dir).relative_to(game_dir)),
        "compare_md": str(current_compare_markdown_path(game_dir).relative_to(game_dir)),
        "report_file": None,
        "mismatch": None,
    }
    if isinstance(mismatch, dict):
        summary["report_file"] = mismatch.get("report_file")
        summary["mismatch"] = {
            "sequence_id": mismatch.get("sequence_id"),
            "divergence_step": mismatch.get("divergence_step"),
            "divergence_reason": mismatch.get("divergence_reason"),
            "state_diff_changed_pixels": (mismatch.get("state_diff") or {}).get("changed_pixels"),
            "game_step_diff_changed_pixels": (mismatch.get("game_step_diff") or {}).get("changed_pixels"),
            "model_step_diff_changed_pixels": (mismatch.get("model_step_diff") or {}).get("changed_pixels"),
        }
    return summary


def first_mismatch_report(compare_payload: dict[str, Any]) -> dict[str, Any] | None:
    reports = normalize_current_compare_payload(compare_payload).get("reports")
    if not isinstance(reports, list):
        return None
    for report in reports:
        if isinstance(report, dict) and report.get("matched") is False:
            return report
    return None


def sequence_json_path(game_dir: str | Path, level: int, sequence_id: str) -> Path:
    return level_dir(game_dir, level) / "sequences" / f"{sequence_id}.json"


def load_sequence(game_dir: str | Path, level: int, sequence_id: str) -> dict[str, Any]:
    return load_json(sequence_json_path(game_dir, level, sequence_id))


def select_sequence_step(
    sequence_payload: dict[str, Any],
    *,
    local_step: int | None = None,
    divergence_step: int | None = None,
) -> dict[str, Any]:
    actions = sequence_payload.get("actions")
    if not isinstance(actions, list) or not actions:
        raise ValueError("sequence has no actions")
    target_step = int(local_step or divergence_step or 1)
    for action in actions:
        if isinstance(action, dict) and int(action.get("local_step", -1)) == target_step:
            return action
    raise ValueError(f"sequence step {target_step} not found")


def summarize_sequence_step(
    game_dir: str | Path,
    *,
    level: int,
    sequence_id: str,
    local_step: int | None = None,
    divergence_step: int | None = None,
) -> dict[str, Any]:
    game_dir = coerce_path(game_dir)
    sequence_payload = load_sequence(game_dir, level, sequence_id)
    step = select_sequence_step(
        sequence_payload,
        local_step=local_step,
        divergence_step=divergence_step,
    )
    files = step.get("files") if isinstance(step.get("files"), dict) else {}
    level_root = level_dir(game_dir, level)
    before_path = level_root / str(files.get("before_state_hex", ""))
    after_path = level_root / str(files.get("after_state_hex", ""))
    meta_rel = files.get("meta_json")
    meta_path = level_root / str(meta_rel) if meta_rel else before_path.parent / "meta.json"
    return {
        "level": int(level),
        "sequence_id": sequence_id,
        "sequence_file": display_path(game_dir, sequence_json_path(game_dir, level, sequence_id)),
        "sequence_action_count": int(sequence_payload.get("action_count", 0) or 0),
        "sequence_end_reason": sequence_payload.get("end_reason"),
        "step": {
            "local_step": int(step.get("local_step", 0) or 0),
            "action_index": int(step.get("action_index", 0) or 0),
            "tool_turn": int(step.get("tool_turn", 0) or 0),
            "step_in_call": int(step.get("step_in_call", 0) or 0),
            "action_name": step.get("action_name"),
            "state_before": step.get("state_before"),
            "state_after": step.get("state_after"),
            "levels_completed_before": step.get("levels_completed_before"),
            "levels_completed_after": step.get("levels_completed_after"),
            "before_state_hex": display_path(game_dir, before_path),
            "after_state_hex": display_path(game_dir, after_path),
            "meta_json": display_path(game_dir, meta_path),
        },
    }


def inspect_current_mismatch(game_dir: str | Path) -> dict[str, Any]:
    game_dir = coerce_path(game_dir)
    compare_payload = load_current_compare(game_dir)
    mismatch = first_mismatch_report(compare_payload)
    if not mismatch:
        compare_summary = summarize_current_compare(game_dir)
        if not bool(compare_summary.get("all_match")):
            return {
                "status": "error",
                "message": "current_compare.json is not clean but has no mismatched report",
                "compare": compare_summary,
                "mismatch": None,
            }
        return {
            "status": "clean",
            "message": "current_compare.json has no mismatched report",
            "compare": compare_summary,
            "mismatch": None,
        }
    level = int(mismatch.get("level") or compare_payload.get("level") or 0)
    sequence_id = str(mismatch.get("sequence_id") or "").strip()
    if not sequence_id:
        raise ValueError("mismatch report is missing sequence_id")
    summary = summarize_sequence_step(
        game_dir,
        level=level,
        sequence_id=sequence_id,
        divergence_step=int(mismatch.get("divergence_step") or 1),
    )
    summary["compare"] = {
        **summarize_current_compare(game_dir),
        "status": "mismatch",
        "divergence_step": mismatch.get("divergence_step"),
        "divergence_reason": mismatch.get("divergence_reason"),
        "state_diff_changed_pixels": (mismatch.get("state_diff") or {}).get("changed_pixels"),
        "game_step_diff_changed_pixels": (mismatch.get("game_step_diff") or {}).get("changed_pixels"),
        "model_step_diff_changed_pixels": (mismatch.get("model_step_diff") or {}).get("changed_pixels"),
    }
    return summary
