#!/usr/bin/env python3
"""Summarize component coverage and compare mismatches using components.py detectors."""

from __future__ import annotations

import argparse
import ast
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
    return parser.parse_args()


def _component_report_paths(game_dir: Path) -> tuple[Path, Path]:
    return game_dir / "component_coverage.json", game_dir / "component_coverage.md"
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
def _collect_grid_sensitive_function_names(function_node: ast.FunctionDef, grid_param: str) -> set[str]:
    loaded_names: set[str] = set()

    class Visitor(ast.NodeVisitor):
        def visit_Subscript(self, node: ast.Subscript) -> None:
            if isinstance(node.value, ast.Name) and node.value.id == grid_param:
                loaded_names.add("__grid_subscript__")
            self.generic_visit(node)

        def visit_Compare(self, node: ast.Compare) -> None:
            names = [n.id for n in ast.walk(node) if isinstance(n, ast.Name)]
            if grid_param in names:
                loaded_names.add("__grid_compare__")
            self.generic_visit(node)

        def visit_Call(self, node: ast.Call) -> None:
            func = node.func
            func_name = None
            if isinstance(func, ast.Name):
                func_name = func.id
            elif isinstance(func, ast.Attribute):
                func_name = func.attr
            if any(isinstance(arg, ast.Name) and arg.id == grid_param for arg in node.args):
                if func_name:
                    loaded_names.add(func_name)
            self.generic_visit(node)

    Visitor().visit(function_node)
    return loaded_names
def _detector_source_issues(game_dir: Path, components_module: Any) -> list[dict[str, Any]]:
    components_path = game_dir / "components.py"
    if not components_path.exists():
        return []
    source = components_path.read_text()
    tree = ast.parse(source, filename=str(components_path))
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }

    registry = getattr(components_module, "COMPONENT_REGISTRY", None)
    if not isinstance(registry, dict):
        return []

    issues: list[dict[str, Any]] = []
    for kind, detector in registry.items():
        func_name = getattr(detector, "__name__", "")
        node = functions.get(func_name)
        if node is None or not node.args.args:
            continue
        grid_param = node.args.args[0].arg
        sensitive_names = _collect_grid_sensitive_function_names(node, grid_param)
        if sensitive_names:
            continue
        lineno = int(getattr(node, "lineno", 1))
        issues.append(
            {
                "kind": str(kind),
                "detector": func_name or str(kind),
                "line": lineno,
                "message": (
                    "detector does not inspect grid contents; static-coordinate or shape-only "
                    "detectors do not satisfy component coverage"
                ),
            }
        )
    return issues


def _bbox_from_cells(cells: list[tuple[int, int]]) -> tuple[int, int, int, int]:
    rows = [row for row, _col in cells]
    cols = [col for _row, col in cells]
    return min(rows), min(cols), max(rows), max(cols)


def _normalize_component(candidate: Any, *, fallback_kind: str, index: int) -> dict[str, Any]:
    kind = fallback_kind
    attrs: dict[str, Any] = {}
    bbox: tuple[int, int, int, int] | None = None
    cells: list[tuple[int, int]] | None = None
    geometry_source = "cells"

    if hasattr(candidate, "kind") and isinstance(candidate.kind, str):
        kind = candidate.kind
    if hasattr(candidate, "attrs") and isinstance(candidate.attrs, dict):
        attrs = dict(candidate.attrs)
    elif isinstance(candidate, dict) and isinstance(candidate.get("attrs"), dict):
        attrs = dict(candidate["attrs"])

    if hasattr(candidate, "cells"):
        raw_cells = list(getattr(candidate, "cells"))
        if raw_cells:
            cells = [(int(row), int(col)) for row, col in raw_cells]
    elif isinstance(candidate, dict) and isinstance(candidate.get("cells"), list) and candidate["cells"]:
        cells = [(int(row), int(col)) for row, col in candidate["cells"]]
    elif isinstance(candidate, list) and candidate and all(
        isinstance(entry, (list, tuple)) and len(entry) == 2 for entry in candidate
    ):
        cells = [(int(row), int(col)) for row, col in candidate]

    if hasattr(candidate, "bbox"):
        raw_bbox = getattr(candidate, "bbox")
    elif isinstance(candidate, dict):
        raw_bbox = candidate.get("bbox")
    else:
        raw_bbox = candidate

    if cells:
        cells = sorted(set(cells))
        bbox = _bbox_from_cells(cells)
    elif (
        isinstance(raw_bbox, (list, tuple))
        and len(raw_bbox) == 4
        and all(isinstance(value, (int, np.integer)) for value in raw_bbox)
    ):
        bbox = tuple(int(value) for value in raw_bbox)  # type: ignore[assignment]
        top, left, bottom, right = bbox
        cells = [(row, col) for row in range(top, bottom + 1) for col in range(left, right + 1)]
        geometry_source = "bbox"

    if bbox is None:
        raise RuntimeError(f"component detector '{kind}' returned an unsupported component at index {index}")

    top, left, bottom, right = bbox
    return {
        "id": f"{kind}#{index}",
        "kind": kind,
        "bbox": [top, left, bottom, right],
        "cells": cells,
        "pixel_count": len(cells or []),
        "geometry_source": geometry_source,
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
        for row, col in component.get("cells") or []:
            mask[row, col] = True
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
    observed_shapes = payload.get("observed_shapes") or []
    if observed_shapes:
        lines.append(f"observed_shapes: {', '.join(str(shape) for shape in observed_shapes)}")
    failure = payload.get("first_failure")
    detector_issues = payload.get("detector_issues") or []
    if detector_issues:
        lines.extend(["", "detector_issues:"])
        for issue in detector_issues:
            lines.append(
                f"- {issue['kind']} / {issue['detector']} (line {issue['line']}): {issue['message']}"
            )
    geometry_issues = payload.get("geometry_issues") or []
    if geometry_issues:
        lines.extend(["", "geometry_issues:"])
        for issue in geometry_issues:
            lines.append(
                f"- {issue['kind']} / {issue['component_id']}: {issue['message']}"
            )
    if not failure:
        lines.extend(["", "All seen states for this level are covered by exact component geometry."])
        return "\n".join(lines) + "\n"
    lines.extend(
        [
            "",
            f"first_failure_state: {failure.get('label')}",
            f"state_file: {failure.get('path')}",
            f"state_shape: {failure.get('shape')}",
            f"uncovered_pixel_count: {failure.get('uncovered_pixel_count')}",
            "",
            "uncovered_boxes:",
        ]
    )
    for box in failure.get("uncovered_boxes", []):
        lines.append(f"- bbox={box['bbox']} pixels={box['pixel_count']}")
    lines.extend(["", "components:"])
    for component in failure.get("components", []):
        lines.append(
            f"- {component['id']}: bbox={component['bbox']} pixels={component.get('pixel_count', '?')}"
        )
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
        "observed_shapes": [],
        "first_failure": None,
        "detector_issues": _detector_source_issues(game_dir, components_module),
        "geometry_issues": [],
    }
    observed_shapes: list[str] = []

    if payload["detector_issues"]:
        payload["status"] = "fail"

    for state in states:
        grid = artifact_helpers.load_hex_grid(game_dir / state["path"])
        shape_label = f"{int(grid.shape[0])}x{int(grid.shape[1])}"
        if shape_label not in observed_shapes:
            observed_shapes.append(shape_label)
        if payload["status"] == "fail" and payload["detector_issues"]:
            continue
        components = _collect_components(components_module, grid)
        for component in components:
            if component.get("geometry_source") != "cells":
                payload["geometry_issues"].append(
                    {
                        "kind": component["kind"],
                        "component_id": component["id"],
                        "message": "component output preserved only a bbox; exact geometry must be returned via cells",
                    }
                )
        if payload["geometry_issues"]:
            payload["status"] = "fail"
            payload["observed_shapes"] = observed_shapes
            continue
        covered = _coverage_mask(grid.shape, components)
        uncovered = ~covered
        if uncovered.any():
            payload["status"] = "fail"
            payload["observed_shapes"] = observed_shapes
            payload["first_failure"] = {
                "label": state["label"],
                "path": state["path"],
                "shape": shape_label,
                "uncovered_pixel_count": int(uncovered.sum()),
                "uncovered_boxes": _connected_uncovered_boxes(uncovered),
                "components": components,
            }
            break

    payload["observed_shapes"] = observed_shapes

    json_path, md_path = _component_report_paths(game_dir)
    _write_json_and_markdown(json_path, md_path, payload, _component_coverage_markdown(payload))
    return payload, 0 if payload["status"] == "pass" else 1


def main() -> int:
    try:
        args = parse_args()
        game_dir = Path(args.game_dir).resolve()
        if not args.coverage:
            raise RuntimeError("inspect_components.py only supports --coverage")

        payload, code = run_component_coverage(game_dir, level=args.level)
    except Exception as exc:
        payload = {"status": "error", "message": str(exc)}
        code = 1

    print(json.dumps(payload, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
