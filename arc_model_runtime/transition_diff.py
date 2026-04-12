from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from .utils import diff_payload, read_hex_grid, resolve_level_dir


def _diff_with_bbox(before: np.ndarray, after: np.ndarray) -> dict[str, Any]:
    payload = diff_payload(before, after)
    if payload.get("shape_mismatch"):
        return payload
    changes = payload.get("changes", [])
    if not isinstance(changes, list) or not changes:
        payload["changed_bbox"] = None
        return payload
    rows = [int(item["row"]) for item in changes if isinstance(item, dict) and "row" in item]
    cols = [int(item["col"]) for item in changes if isinstance(item, dict) and "col" in item]
    if not rows or not cols:
        payload["changed_bbox"] = None
        return payload
    payload["changed_bbox"] = {
        "row_min": min(rows),
        "row_max": max(rows),
        "col_min": min(cols),
        "col_max": max(cols),
    }
    return payload


def _load_sequence_payload(level_dir: Path, sequence_id: str) -> dict[str, Any]:
    seq_path = level_dir / "sequences" / f"{sequence_id}.json"
    if not seq_path.exists():
        raise RuntimeError(f"missing sequence file: {seq_path}")
    payload = json.loads(seq_path.read_text())
    if not isinstance(payload, dict):
        raise RuntimeError(f"invalid sequence payload: {seq_path}")
    return payload


def _load_transition_artifacts(level_dir: Path, action: dict[str, Any]) -> dict[str, Any]:
    files = action.get("files", {}) if isinstance(action.get("files"), dict) else {}
    before_rel = str(files.get("before_state_hex", "") or "").strip()
    after_rel = str(files.get("after_state_hex", "") or "").strip()
    if not before_rel or not after_rel:
        raise RuntimeError("transition is missing before/after state paths")
    before_path = level_dir / before_rel
    after_path = level_dir / after_rel
    if not before_path.exists():
        raise RuntimeError(f"missing before_state.hex: {before_path}")
    if not after_path.exists():
        raise RuntimeError(f"missing after_state.hex: {after_path}")
    frame_paths: list[Path] = []
    frame_grids: list[np.ndarray] = []
    raw_frame_paths = files.get("frame_sequence_hex", [])
    if isinstance(raw_frame_paths, list):
        for rel in raw_frame_paths:
            frame_path = level_dir / str(rel)
            if frame_path.exists():
                frame_paths.append(frame_path)
                frame_grids.append(read_hex_grid(frame_path))
    return {
        "before_path": before_path,
        "after_path": after_path,
        "frame_paths": frame_paths,
        "before_grid": read_hex_grid(before_path),
        "after_grid": read_hex_grid(after_path),
        "frame_grids": frame_grids,
    }


def _resolve_transition(level_dir: Path, sequence_id: str, local_step: int) -> dict[str, Any]:
    payload = _load_sequence_payload(level_dir, sequence_id)
    actions = payload.get("actions", [])
    if not isinstance(actions, list):
        raise RuntimeError(f"sequence has invalid actions list: {sequence_id}")
    target = None
    for action in actions:
        if not isinstance(action, dict):
            continue
        if int(action.get("local_step", 0) or 0) == int(local_step):
            target = action
            break
    if target is None:
        raise RuntimeError(f"missing step {int(local_step)} in sequence {sequence_id}")
    artifacts = _load_transition_artifacts(level_dir, target)
    return {
        "sequence_payload": payload,
        "action": target,
        "artifacts": artifacts,
    }


def _transition_ref(level: int, sequence_id: str, action: dict[str, Any], artifacts: dict[str, Any], level_dir: Path) -> dict[str, Any]:
    before_path = Path(artifacts["before_path"])
    after_path = Path(artifacts["after_path"])
    frame_paths = [Path(item) for item in artifacts.get("frame_paths", [])]
    return {
        "level": int(level),
        "sequence_id": str(sequence_id),
        "local_step": int(action.get("local_step", 0) or 0),
        "action_index": int(action.get("action_index", 0) or 0),
        "action_name": str(action.get("action_name", "") or ""),
        "state_before": str(action.get("state_before", "") or ""),
        "state_after": str(action.get("state_after", "") or ""),
        "level_before": int(action.get("level_before", level) or level),
        "level_after": int(action.get("level_after", level) or level),
        "levels_completed_before": int(action.get("levels_completed_before", 0) or 0),
        "levels_completed_after": int(action.get("levels_completed_after", 0) or 0),
        "frame_count": len(frame_paths),
        "before_state_path": before_path.relative_to(level_dir).as_posix(),
        "after_state_path": after_path.relative_to(level_dir).as_posix(),
        "frame_paths": [path.relative_to(level_dir).as_posix() for path in frame_paths],
    }


def diff_transition(*, game_dir: Path, level: int, sequence_id: str, local_step: int) -> dict[str, Any]:
    level_dir = resolve_level_dir(game_dir, int(level))
    if level_dir is None:
        raise RuntimeError(f"missing level dir for level {int(level)}")
    resolved = _resolve_transition(level_dir, sequence_id, local_step)
    action = resolved["action"]
    artifacts = resolved["artifacts"]
    before_grid = artifacts["before_grid"]
    after_grid = artifacts["after_grid"]
    frame_grids = artifacts["frame_grids"]
    frames: list[dict[str, Any]] = []
    previous = before_grid
    for index, frame_grid in enumerate(frame_grids, start=1):
        frames.append({
            "frame_index": int(index),
            "path": Path(artifacts["frame_paths"][index - 1]).relative_to(level_dir).as_posix(),
            "diff_from_previous": _diff_with_bbox(previous, frame_grid),
        })
        previous = frame_grid
    return {
        "ok": True,
        "action": "diff_transition",
        "transition": _transition_ref(int(level), sequence_id, action, artifacts, level_dir),
        "before_to_after_diff": _diff_with_bbox(before_grid, after_grid),
        "frames": frames,
    }


def compare_transitions(
    *,
    game_dir: Path,
    a_level: int,
    a_sequence_id: str,
    a_local_step: int,
    b_level: int,
    b_sequence_id: str,
    b_local_step: int,
) -> dict[str, Any]:
    a_level_dir = resolve_level_dir(game_dir, int(a_level))
    b_level_dir = resolve_level_dir(game_dir, int(b_level))
    if a_level_dir is None:
        raise RuntimeError(f"missing level dir for level {int(a_level)}")
    if b_level_dir is None:
        raise RuntimeError(f"missing level dir for level {int(b_level)}")
    a_resolved = _resolve_transition(a_level_dir, a_sequence_id, a_local_step)
    b_resolved = _resolve_transition(b_level_dir, b_sequence_id, b_local_step)
    a_action = a_resolved["action"]
    b_action = b_resolved["action"]
    a_artifacts = a_resolved["artifacts"]
    b_artifacts = b_resolved["artifacts"]
    a_before = a_artifacts["before_grid"]
    a_after = a_artifacts["after_grid"]
    b_before = b_artifacts["before_grid"]
    b_after = b_artifacts["after_grid"]
    a_frames = a_artifacts["frame_grids"]
    b_frames = b_artifacts["frame_grids"]
    paired_frames: list[dict[str, Any]] = []
    previous_a = a_before
    previous_b = b_before
    shared_count = min(len(a_frames), len(b_frames))
    for index in range(shared_count):
        a_frame = a_frames[index]
        b_frame = b_frames[index]
        paired_frames.append({
            "frame_index": int(index + 1),
            "a_diff_from_previous": _diff_with_bbox(previous_a, a_frame),
            "b_diff_from_previous": _diff_with_bbox(previous_b, b_frame),
            "between_frame_diff": _diff_with_bbox(a_frame, b_frame),
        })
        previous_a = a_frame
        previous_b = b_frame
    extra_a: list[dict[str, Any]] = []
    for index in range(shared_count, len(a_frames)):
        frame_grid = a_frames[index]
        extra_a.append({
            "frame_index": int(index + 1),
            "diff_from_previous": _diff_with_bbox(previous_a, frame_grid),
        })
        previous_a = frame_grid
    extra_b: list[dict[str, Any]] = []
    for index in range(shared_count, len(b_frames)):
        frame_grid = b_frames[index]
        extra_b.append({
            "frame_index": int(index + 1),
            "diff_from_previous": _diff_with_bbox(previous_b, frame_grid),
        })
        previous_b = frame_grid
    return {
        "ok": True,
        "action": "compare_transitions",
        "transition_a": _transition_ref(int(a_level), a_sequence_id, a_action, a_artifacts, a_level_dir),
        "transition_b": _transition_ref(int(b_level), b_sequence_id, b_action, b_artifacts, b_level_dir),
        "same_action_name": str(a_action.get("action_name", "") or "") == str(b_action.get("action_name", "") or ""),
        "pre_state_diff": _diff_with_bbox(a_before, b_before),
        "post_state_diff": _diff_with_bbox(a_after, b_after),
        "a_before_to_after_diff": _diff_with_bbox(a_before, a_after),
        "b_before_to_after_diff": _diff_with_bbox(b_before, b_after),
        "frame_count_a": len(a_frames),
        "frame_count_b": len(b_frames),
        "paired_frames": paired_frames,
        "extra_frames_a": extra_a,
        "extra_frames_b": extra_b,
    }
