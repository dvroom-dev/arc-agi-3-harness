"""Agent-owned component definitions.

Theory mode owns this file.
Define evidence-backed visible components here and keep every visible pixel in
every seen state covered by at least one exact component geometry.
Use neutral code names only. Do not encode assumed functions or semantic roles
into component identifiers unless action-linked evidence has already proven that
role. Semantic guesses belong in
`theory.md`, not in this file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable

import numpy as np


GridCell = tuple[int, int]


def _normalize_cells(cells: Iterable[GridCell]) -> tuple[GridCell, ...]:
    normalized = sorted({(int(row), int(col)) for row, col in cells})
    if not normalized:
        raise ValueError("components must preserve exact geometry with at least one occupied cell")
    return tuple(normalized)


def _bbox_from_cells(cells: tuple[GridCell, ...]) -> tuple[int, int, int, int]:
    rows = [row for row, _col in cells]
    cols = [col for _row, col in cells]
    return min(rows), min(cols), max(rows), max(cols)


@dataclass(frozen=True)
class ComponentShape:
    kind: str
    cells: tuple[GridCell, ...]
    attrs: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "cells", _normalize_cells(self.cells))

    @property
    def bbox(self) -> tuple[int, int, int, int]:
        return _bbox_from_cells(self.cells)


# Backward-compatible alias for existing imports in agent-owned files.
ComponentBox = ComponentShape


ComponentDetector = Callable[[np.ndarray], list[ComponentShape]]


# Theory mode should keep this registry broad enough that every visible pixel in
# every seen state lies inside at least one exact component geometry.
# Component `kind` names should stay neutral and structural rather than semantic.
COMPONENT_REGISTRY: dict[str, ComponentDetector] = {}


def iter_components(grid: np.ndarray) -> list[ComponentShape]:
    """Return all detected components for a grid."""
    components: list[ComponentShape] = []
    for kind, detector in COMPONENT_REGISTRY.items():
        for component in detector(grid):
            if component.kind != kind:
                component = ComponentShape(kind=kind, cells=component.cells, attrs=dict(component.attrs))
            components.append(component)
    return components


def make_component(
    kind: str,
    *,
    cells: Iterable[GridCell],
    **attrs: object,
) -> ComponentShape:
    """Build a component from exact occupied cells."""
    return ComponentShape(kind=kind, cells=tuple(cells), attrs=dict(attrs))


def make_rect_component(
    kind: str,
    *,
    top: int,
    left: int,
    bottom: int,
    right: int,
    **attrs: object,
) -> ComponentShape:
    """Convenience helper for solid rectangular regions discovered from grid evidence."""
    cells = ((row, col) for row in range(top, bottom + 1) for col in range(left, right + 1))
    return make_component(kind, cells=cells, **attrs)


# Example detector style:
# - return one ComponentShape per independently moving/recoloring/consumable region
# - preserve exact occupied cells; bbox is derived convenience data, not the canonical geometry
# - avoid one giant umbrella region when separate regions can change independently
# - detectors must inspect grid contents (pattern/color/connectivity), not just
#   return a fixed coordinate box or a box derived only from `grid.shape`
# - prefer neutral names like `feature_x`, `cluster_a`, `shape_1`, `marker_b`
#   rather than names that assume purpose or behavior
#
# def find_all_feature_x(grid: np.ndarray) -> list[ComponentShape]:
#     cells = [(int(row), int(col)) for row, col in np.argwhere(np.isin(grid, [0xC, 0x9]))]
#     return [make_component("feature_x", cells=cells)] if cells else []
#
# COMPONENT_REGISTRY["feature_x"] = find_all_feature_x
