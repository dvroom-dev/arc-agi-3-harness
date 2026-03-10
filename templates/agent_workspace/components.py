"""Agent-owned component definitions.

Theory mode owns this file.
Define evidence-backed visible components here and keep every visible pixel in
every seen state covered by at least one component bounding box.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np


@dataclass(frozen=True)
class ComponentBox:
    kind: str
    bbox: tuple[int, int, int, int]
    attrs: dict[str, object] = field(default_factory=dict)


ComponentDetector = Callable[[np.ndarray], list[ComponentBox]]


# Theory mode should keep this registry broad enough that every visible pixel in
# every seen state lies inside at least one component bounding box.
COMPONENT_REGISTRY: dict[str, ComponentDetector] = {}


def iter_components(grid: np.ndarray) -> list[ComponentBox]:
    """Return all detected components for a grid."""
    components: list[ComponentBox] = []
    for kind, detector in COMPONENT_REGISTRY.items():
        for component in detector(grid):
            if component.kind != kind:
                component = ComponentBox(kind=kind, bbox=component.bbox, attrs=dict(component.attrs))
            components.append(component)
    return components


def make_component(
    kind: str,
    *,
    top: int,
    left: int,
    bottom: int,
    right: int,
    **attrs: object,
) -> ComponentBox:
    """Helper for detector implementations."""
    return ComponentBox(kind=kind, bbox=(top, left, bottom, right), attrs=dict(attrs))


# Example detector style:
# - return one ComponentBox per independently moving/recoloring/consumable region
# - avoid one giant umbrella bbox when separate regions can change independently
#
# def find_all_feature_x(grid: np.ndarray) -> list[ComponentBox]:
#     boxes: list[ComponentBox] = []
#     for top, left, bottom, right in find_connected_regions(grid, colors={"C", "9"}):
#         boxes.append(
#             make_component(
#                 "feature_x",
#                 top=top,
#                 left=left,
#                 bottom=bottom,
#                 right=right,
#             )
#         )
#     return boxes
#
# COMPONENT_REGISTRY["feature_x"] = find_all_feature_x
