from __future__ import annotations

import hashlib
import json
from collections import deque
from pathlib import Path

import numpy as np


def _read_hex_grid(path: Path) -> np.ndarray:
    rows = [line.strip().upper() for line in path.read_text().splitlines() if line.strip()]
    return np.array([[int(ch, 16) for ch in row] for row in rows], dtype=np.int8)


def _diff_mask(before: np.ndarray, after: np.ndarray) -> np.ndarray:
    if before.shape != after.shape:
        raise RuntimeError(f"shape mismatch for feature box diff: {before.shape} vs {after.shape}")
    return before != after


def _dilate(mask: np.ndarray, radius: int = 1) -> np.ndarray:
    if radius <= 0:
        return np.array(mask, copy=True)
    out = np.array(mask, copy=True)
    for dr in range(-radius, radius + 1):
        for dc in range(-radius, radius + 1):
            if dr == 0 and dc == 0:
                continue
            shifted = np.zeros_like(mask, dtype=bool)
            src_r0 = max(0, -dr)
            src_r1 = mask.shape[0] - max(0, dr)
            src_c0 = max(0, -dc)
            src_c1 = mask.shape[1] - max(0, dc)
            dst_r0 = max(0, dr)
            dst_r1 = dst_r0 + (src_r1 - src_r0)
            dst_c0 = max(0, dc)
            dst_c1 = dst_c0 + (src_c1 - src_c0)
            shifted[dst_r0:dst_r1, dst_c0:dst_c1] = mask[src_r0:src_r1, src_c0:src_c1]
            out |= shifted
    return out


def _component_boxes(mask: np.ndarray) -> list[tuple[int, int, int, int]]:
    seen = np.zeros_like(mask, dtype=bool)
    boxes: list[tuple[int, int, int, int]] = []
    rows, cols = mask.shape
    for row in range(rows):
        for col in range(cols):
            if not mask[row, col] or seen[row, col]:
                continue
            queue = deque([(row, col)])
            seen[row, col] = True
            min_row = max_row = row
            min_col = max_col = col
            while queue:
                cur_row, cur_col = queue.popleft()
                min_row = min(min_row, cur_row)
                max_row = max(max_row, cur_row)
                min_col = min(min_col, cur_col)
                max_col = max(max_col, cur_col)
                for d_row, d_col in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
                    next_row = cur_row + d_row
                    next_col = cur_col + d_col
                    if next_row < 0 or next_col < 0 or next_row >= rows or next_col >= cols:
                        continue
                    if seen[next_row, next_col] or not mask[next_row, next_col]:
                        continue
                    seen[next_row, next_col] = True
                    queue.append((next_row, next_col))
            boxes.append((min_row, min_col, max_row, max_col))
    return boxes


def _boxes_intersect(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    a_r0, a_c0, a_r1, a_c1 = a
    b_r0, b_c0, b_r1, b_c1 = b
    return not (a_r1 < b_r0 or b_r1 < a_r0 or a_c1 < b_c0 or b_c1 < a_c0)


def _box_area(box: tuple[int, int, int, int]) -> int:
    return (box[2] - box[0] + 1) * (box[3] - box[1] + 1)


def _merge_boxes(boxes: list[tuple[int, int, int, int]]) -> tuple[int, int, int, int]:
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def _overlap_ratio(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ar0, ac0, ar1, ac1 = a
    br0, bc0, br1, bc1 = b
    ir0 = max(ar0, br0)
    ic0 = max(ac0, bc0)
    ir1 = min(ar1, br1)
    ic1 = min(ac1, bc1)
    if ir1 < ir0 or ic1 < ic0:
        return 0.0
    inter = (ir1 - ir0 + 1) * (ic1 - ic0 + 1)
    return inter / float(min(_box_area(a), _box_area(b)))


def _cluster_boxes(
    boxes: list[tuple[int, int, int, int]],
    *,
    overlap_threshold: float = 0.5,
    max_growth_factor: float = 8.0,
) -> list[tuple[int, int, int, int]]:
    clusters: list[dict[str, object]] = []
    for box in boxes:
        placed = False
        for cluster in clusters:
            representative = cluster["box"]
            assert isinstance(representative, tuple)
            if _overlap_ratio(box, representative) < overlap_threshold:
                continue
            members = list(cluster["members"])
            assert isinstance(members, list)
            candidate_members = [*members, box]
            merged_box = _merge_boxes(candidate_members)
            areas = sorted(_box_area(member) for member in candidate_members)
            median_area = areas[len(areas) // 2]
            if _box_area(merged_box) > int(median_area * max_growth_factor):
                continue
            cluster["members"] = candidate_members
            cluster["box"] = merged_box
            placed = True
            break
        if not placed:
            clusters.append({"box": box, "members": [box]})
    return [cluster["box"] for cluster in clusters]


def _expand_box(box: tuple[int, int, int, int], *, height: int, width: int, margin: int) -> tuple[int, int, int, int]:
    row0, col0, row1, col1 = box
    return (
        max(0, row0 - margin),
        max(0, col0 - margin),
        min(height - 1, row1 + margin),
        min(width - 1, col1 + margin),
    )


def _iter_level_sequences(level_dir: Path) -> list[dict]:
    sequences_dir = level_dir / "sequences"
    payloads: list[dict] = []
    for seq_path in sorted(sequences_dir.glob("seq_*.json")):
        try:
            payload = json.loads(seq_path.read_text())
        except Exception:
            continue
        if isinstance(payload, dict):
            payloads.append(payload)
    return payloads


def generate_feature_boxes(level_dir: Path, *, dilation_radius: int = 1, margin: int = 1) -> dict:
    if not level_dir.exists():
        raise RuntimeError(f"missing level dir for feature boxes: {level_dir}")
    level_name = level_dir.name
    if not level_name.startswith("level_"):
        raise RuntimeError(f"feature boxes require canonical level dir, got {level_name}")
    level_num = int(level_name.split("_", 1)[1])
    sequences = _iter_level_sequences(level_dir)
    if not sequences:
        payload = {
            "schema_version": "flux.feature_boxes.v1",
            "level": level_num,
            "boxes": [],
        }
        payload["box_spec_hash"] = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
        return payload

    all_step_boxes: list[tuple[int, int, int, int]] = []
    stats: list[dict] = []
    grid_shape: tuple[int, int] | None = None
    for sequence in sequences:
        sequence_id = str(sequence.get("sequence_id", "") or "").strip()
        actions = sequence.get("actions") if isinstance(sequence.get("actions"), list) else []
        for action in actions:
            if not isinstance(action, dict):
                continue
            files = action.get("files") if isinstance(action.get("files"), dict) else {}
            before_rel = str(files.get("before_state_hex", "") or "")
            after_rel = str(files.get("after_state_hex", "") or "")
            if not before_rel or not after_rel:
                continue
            before = _read_hex_grid(level_dir / before_rel)
            after = _read_hex_grid(level_dir / after_rel)
            if grid_shape is None:
                grid_shape = before.shape
            step_mask = _diff_mask(before, after)
            for frame_rel in files.get("frame_sequence_hex", []) if isinstance(files.get("frame_sequence_hex"), list) else []:
                frame_path = level_dir / str(frame_rel)
                if frame_path.exists():
                    frame = _read_hex_grid(frame_path)
                    step_mask |= _diff_mask(before, frame)
                    step_mask |= _diff_mask(frame, after)
            if not bool(np.any(step_mask)):
                continue
            board_area = before.shape[0] * before.shape[1]
            changed_pixels = int(np.count_nonzero(step_mask))
            if changed_pixels >= int(board_area * 0.8):
                # Whole-screen or near-whole-screen transition surfaces are not useful local feature evidence.
                # They tend to be level/room wipes or large animations that collapse the boxing phase.
                continue
            dilated = _dilate(step_mask, radius=dilation_radius)
            boxes = [_expand_box(box, height=before.shape[0], width=before.shape[1], margin=margin) for box in _component_boxes(dilated)]
            all_step_boxes.extend(boxes)
            stats.append({
                "sequence_id": sequence_id,
                "local_step": int(action.get("local_step", 0) or 0),
                "action_name": str(action.get("action_name", "") or ""),
                "changed_pixels": changed_pixels,
                "boxes": boxes,
            })
    if grid_shape is None:
        raise RuntimeError(f"could not determine grid shape for feature boxes under {level_dir}")
    clustered_boxes = _cluster_boxes(all_step_boxes)
    deduped_boxes: list[tuple[int, int, int, int]] = []
    for box in sorted(clustered_boxes):
        if box not in deduped_boxes:
            deduped_boxes.append(box)
    payload_boxes = []
    for index, box in enumerate(deduped_boxes, start=1):
        row0, col0, row1, col1 = box
        touched_sequences = sorted({
            item["sequence_id"]
            for item in stats
            for step_box in item["boxes"]
            if _boxes_intersect(box, step_box)
        })
        touched_actions = sorted({
            item["action_name"]
            for item in stats
            for step_box in item["boxes"]
            if _boxes_intersect(box, step_box) and item["action_name"]
        })
        payload_boxes.append({
            "box_id": f"box_{index:02d}",
            "bbox": [row0, col0, row1, col1],
            "touched_sequences": touched_sequences,
            "touched_actions": touched_actions,
        })
    payload = {
        "schema_version": "flux.feature_boxes.v1",
        "level": level_num,
        "boxes": payload_boxes,
    }
    payload["box_spec_hash"] = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return payload
