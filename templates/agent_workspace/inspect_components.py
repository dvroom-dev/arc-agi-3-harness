#!/usr/bin/env python3
"""Summarize component coverage and compare mismatches using components.py detectors."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any

import numpy as np

import artifact_helpers

sys.dont_write_bytecode = True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-dir", default=".", help="Game workspace root (default: current dir)")
    parser.add_argument("--level", type=int, help="Explicit level number")
    parser.add_argument(
        "--coverage",
        action="store_true",
        help="Check component bounding-box coverage across every seen state for the level",
    )
    parser.add_argument(
        "--current-mismatch",
        action="store_true",
        help="Summarize the first current compare mismatch using component bounding boxes",
    )
    return parser.parse_args()


def _component_report_paths(game_dir: Path) -> tuple[Path, Path]:
    return game_dir / "component_coverage.json", game_dir / "component_coverage.md"


def _mismatch_report_paths(game_dir: Path) -> tuple[Path, Path]:
    return game_dir / "component_mismatch.json", game_dir / "component_mismatch.md"


def _load_components_module(game_dir: Path):
    components_path = game_dir / "components.py"
    target_path = components_path if components_path.exists() else game_dir / "model_lib.py"
    spec = importlib.util.spec_from_file_location("agent_components", target_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load component definitions from {target_path.name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _bbox_from_cells(cells: list[tuple[int, int]]) -> tuple[int, int, int, int]:
    rows = [row for row, _col in cells]
    cols = [col for _row, col in cells]
    return min(rows), min(cols), max(rows), max(cols)


def _normalize_component(candidate: Any, *, fallback_kind: str, index: int) -> dict[str, Any]:
    kind = fallback_kind
    attrs: dict[str, Any] = {}
    bbox: tuple[int, int, int, int] | None = None

    if hasattr(candidate, "kind") and isinstance(candidate.kind, str):
        kind = candidate.kind
    if hasattr(candidate, "attrs") and isinstance(candidate.attrs, dict):
        attrs = dict(candidate.attrs)
    elif isinstance(candidate, dict) and isinstance(candidate.get("attrs"), dict):
        attrs = dict(candidate["attrs"])

    if hasattr(candidate, "bbox"):
        raw_bbox = getattr(candidate, "bbox")
    elif isinstance(candidate, dict):
        raw_bbox = candidate.get("bbox")
    else:
        raw_bbox = candidate

    if (
        isinstance(raw_bbox, (list, tuple))
        and len(raw_bbox) == 4
        and all(isinstance(value, (int, np.integer)) for value in raw_bbox)
    ):
        bbox = tuple(int(value) for value in raw_bbox)  # type: ignore[assignment]
    elif hasattr(candidate, "cells"):
        cells = list(getattr(candidate, "cells"))
        if cells:
            bbox = _bbox_from_cells([(int(row), int(col)) for row, col in cells])
    elif isinstance(candidate, dict) and isinstance(candidate.get("cells"), list) and candidate["cells"]:
        bbox = _bbox_from_cells([(int(row), int(col)) for row, col in candidate["cells"]])
    elif isinstance(candidate, list) and candidate and all(
        isinstance(entry, (list, tuple)) and len(entry) == 2 for entry in candidate
    ):
        bbox = _bbox_from_cells([(int(row), int(col)) for row, col in candidate])

    if bbox is None:
        raise RuntimeError(f"component detector '{kind}' returned an unsupported component at index {index}")

    top, left, bottom, right = bbox
    return {
        "id": f"{kind}#{index}",
        "kind": kind,
        "bbox": [top, left, bottom, right],
        "attrs": attrs,
    }


def _collect_components(components_module: Any, grid: np.ndarray) -> list[dict[str, Any]]:
    if hasattr(components_module, "iter_components") and callable(components_module.iter_components):
        raw_components = list(components_module.iter_components(grid))
        return [
            _normalize_component(component, fallback_kind=f"component_{index}", index=index)
            for index, component in enumerate(raw_components)
        ]

    registry = getattr(components_module, "COMPONENT_REGISTRY", None)
    if not isinstance(registry, dict):
        raise RuntimeError("components.py must define COMPONENT_REGISTRY or iter_components()")
    if not registry:
        return []

    components: list[dict[str, Any]] = []
    for kind, detector in registry.items():
        if not callable(detector):
            continue
        for index, candidate in enumerate(detector(grid)):
            components.append(_normalize_component(candidate, fallback_kind=str(kind), index=index))
    return components


def _coverage_mask(shape: tuple[int, int], components: list[dict[str, Any]]) -> np.ndarray:
    mask = np.zeros(shape, dtype=bool)
    for component in components:
        top, left, bottom, right = component["bbox"]
        mask[top : bottom + 1, left : right + 1] = True
    return mask


def _connected_uncovered_boxes(mask: np.ndarray) -> list[dict[str, Any]]:
    visited = np.zeros_like(mask, dtype=bool)
    boxes: list[dict[str, Any]] = []
    rows, cols = mask.shape
    for row in range(rows):
        for col in range(cols):
            if not mask[row, col] or visited[row, col]:
                continue
            stack = [(row, col)]
            visited[row, col] = True
            cells: list[tuple[int, int]] = []
            while stack:
                cur_row, cur_col = stack.pop()
                cells.append((cur_row, cur_col))
                for next_row, next_col in (
                    (cur_row - 1, cur_col),
                    (cur_row + 1, cur_col),
                    (cur_row, cur_col - 1),
                    (cur_row, cur_col + 1),
                ):
                    if not (0 <= next_row < rows and 0 <= next_col < cols):
                        continue
                    if visited[next_row, next_col] or not mask[next_row, next_col]:
                        continue
                    visited[next_row, next_col] = True
                    stack.append((next_row, next_col))
            top, left, bottom, right = _bbox_from_cells(cells)
            boxes.append(
                {
                    "bbox": [top, left, bottom, right],
                    "pixel_count": len(cells),
                }
            )
    return boxes


def _write_json_and_markdown(json_path: Path, md_path: Path, payload: dict[str, Any], markdown: str) -> None:
    json_path.write_text(json.dumps(payload, indent=2) + "\n")
    md_path.write_text(markdown)


def _component_coverage_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Component Coverage",
        "",
        f"status: {payload['status']}",
        f"level: {payload.get('level')}",
        f"states_checked: {payload.get('states_checked')}",
    ]
    failure = payload.get("first_failure")
    if not failure:
        lines.extend(["", "All seen states for this level are covered by component bounding boxes."])
        return "\n".join(lines) + "\n"
    lines.extend(
        [
            "",
            f"first_failure_state: {failure.get('label')}",
            f"state_file: {failure.get('path')}",
            f"uncovered_pixel_count: {failure.get('uncovered_pixel_count')}",
            "",
            "uncovered_boxes:",
        ]
    )
    for box in failure.get("uncovered_boxes", []):
        lines.append(f"- bbox={box['bbox']} pixels={box['pixel_count']}")
    lines.extend(["", "components:"])
    for component in failure.get("components", []):
        lines.append(f"- {component['id']}: bbox={component['bbox']}")
    return "\n".join(lines) + "\n"


def _iou(box_a: list[int], box_b: list[int]) -> float:
    top = max(box_a[0], box_b[0])
    left = max(box_a[1], box_b[1])
    bottom = min(box_a[2], box_b[2])
    right = min(box_a[3], box_b[3])
    if top > bottom or left > right:
        return 0.0
    intersection = (bottom - top + 1) * (right - left + 1)
    area_a = (box_a[2] - box_a[0] + 1) * (box_a[3] - box_a[1] + 1)
    area_b = (box_b[2] - box_b[0] + 1) * (box_b[3] - box_b[1] + 1)
    union = area_a + area_b - intersection
    return intersection / union if union else 0.0


def _pair_components(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> dict[str, Any]:
    used_after: set[int] = set()
    moved: list[dict[str, Any]] = []
    disappeared: list[dict[str, Any]] = []
    unchanged: list[dict[str, Any]] = []

    for before_component in before:
        before_kind = before_component["kind"]
        before_bbox = before_component["bbox"]
        best_index = None
        best_score = 0.0
        for index, after_component in enumerate(after):
            if index in used_after or after_component["kind"] != before_kind:
                continue
            score = _iou(before_bbox, after_component["bbox"])
            if score > best_score:
                best_score = score
                best_index = index
        if best_index is None:
            disappeared.append(before_component)
            continue
        used_after.add(best_index)
        after_component = after[best_index]
        if before_bbox == after_component["bbox"]:
            unchanged.append(before_component)
        else:
            moved.append(
                {
                    "id": before_component["id"],
                    "kind": before_kind,
                    "before_bbox": before_bbox,
                    "after_bbox": after_component["bbox"],
                }
            )

    appeared = [component for index, component in enumerate(after) if index not in used_after]
    return {
        "moved": moved,
        "appeared": appeared,
        "disappeared": disappeared,
        "unchanged": unchanged,
    }


def _component_mismatch_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Component Mismatch",
        "",
        f"status: {payload['status']}",
    ]
    if payload["status"] != "mismatch":
        lines.append("")
        lines.append(payload.get("message", "No mismatch"))
        return "\n".join(lines) + "\n"

    compare = payload["compare"]
    lines.extend(
        [
            f"sequence_id: {compare.get('sequence_id')}",
            f"divergence_step: {compare.get('divergence_step')}",
            f"divergence_reason: {compare.get('divergence_reason')}",
            "",
            "moved_components:",
        ]
    )
    for item in payload["moved_components"]:
        lines.append(f"- {item['id']}: {item['before_bbox']} -> {item['after_bbox']}")
    lines.extend(["", "appeared_components:"])
    for item in payload["appeared_components"]:
        lines.append(f"- {item['id']}: bbox={item['bbox']}")
    lines.extend(["", "disappeared_components:"])
    for item in payload["disappeared_components"]:
        lines.append(f"- {item['id']}: bbox={item['bbox']}")
    lines.extend(["", "unchanged_components:"])
    for item in payload["unchanged_components"]:
        lines.append(f"- {item['id']}: bbox={item['bbox']}")
    return "\n".join(lines) + "\n"


def run_component_coverage(game_dir: Path, *, level: int | None) -> tuple[dict[str, Any], int]:
    components_module = _load_components_module(game_dir)
    level_value = level or artifact_helpers.current_level_number(game_dir)
    if level_value is None:
        raise RuntimeError("could not determine current level")

    states = artifact_helpers.iter_seen_state_files(game_dir, level_value)
    payload: dict[str, Any] = {
        "status": "pass",
        "level": int(level_value),
        "states_checked": len(states),
        "first_failure": None,
    }

    for state in states:
        grid = artifact_helpers.load_hex_grid(game_dir / state["path"])
        components = _collect_components(components_module, grid)
        covered = _coverage_mask(grid.shape, components)
        uncovered = ~covered
        if uncovered.any():
            payload["status"] = "fail"
            payload["first_failure"] = {
                "label": state["label"],
                "path": state["path"],
                "uncovered_pixel_count": int(uncovered.sum()),
                "uncovered_boxes": _connected_uncovered_boxes(uncovered),
                "components": components,
            }
            break

    json_path, md_path = _component_report_paths(game_dir)
    _write_json_and_markdown(json_path, md_path, payload, _component_coverage_markdown(payload))
    if payload["status"] == "pass":
        pin_payload = artifact_helpers.load_analysis_level_pin(game_dir)
        if isinstance(pin_payload, dict) and int(pin_payload.get("level", -1)) == int(level_value):
            artifact_helpers.write_analysis_level_pin(
                game_dir,
                {
                    **pin_payload,
                    "phase": "theory_passed",
                    "coverage_checked_level": int(level_value),
                },
            )
    return payload, 0 if payload["status"] == "pass" else 1


def run_component_mismatch(game_dir: Path) -> tuple[dict[str, Any], int]:
    mismatch = artifact_helpers.inspect_current_mismatch(game_dir)
    if mismatch.get("status") == "clean":
        payload = {
            "status": "clean",
            "message": mismatch.get("message"),
        }
        json_path, md_path = _mismatch_report_paths(game_dir)
        _write_json_and_markdown(json_path, md_path, payload, _component_mismatch_markdown(payload))
        return payload, 0

    components_module = _load_components_module(game_dir)
    step = mismatch["step"]
    before_grid = artifact_helpers.load_hex_grid(game_dir / step["before_state_hex"])
    after_grid = artifact_helpers.load_hex_grid(game_dir / step["after_state_hex"])
    before_components = _collect_components(components_module, before_grid)
    after_components = _collect_components(components_module, after_grid)
    paired = _pair_components(before_components, after_components)

    payload = {
        "status": "mismatch",
        "compare": mismatch["compare"],
        "sequence": {
            "level": mismatch["level"],
            "sequence_id": mismatch["sequence_id"],
            "local_step": step["local_step"],
            "action_name": step["action_name"],
        },
        "moved_components": paired["moved"],
        "appeared_components": paired["appeared"],
        "disappeared_components": paired["disappeared"],
        "unchanged_components": paired["unchanged"],
    }
    json_path, md_path = _mismatch_report_paths(game_dir)
    _write_json_and_markdown(json_path, md_path, payload, _component_mismatch_markdown(payload))
    return payload, 0


def main() -> int:
    args = parse_args()
    game_dir = Path(args.game_dir).resolve()
    if args.coverage == args.current_mismatch:
        raise SystemExit("choose exactly one of --coverage or --current-mismatch")

    if args.coverage:
        payload, code = run_component_coverage(game_dir, level=args.level)
    else:
        payload, code = run_component_mismatch(game_dir)

    print(json.dumps(payload, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
