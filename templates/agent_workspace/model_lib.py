"""Agent-owned model helper stubs.

Goal: keep model.py thin. Put feature detection and reusable mechanics here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

import artifact_helpers


@dataclass(frozen=True)
class LevelConfig:
    level_num: int
    turn_budget: int = 100


@dataclass(frozen=True)
class ComponentBox:
    kind: str
    bbox: tuple[int, int, int, int]
    attrs: dict[str, object] = field(default_factory=dict)


ComponentDetector = Callable[[np.ndarray], list[ComponentBox]]


LEVEL_REGISTRY = {
    1: LevelConfig(level_num=1, turn_budget=100),
}


# Map every evidence-backed visible feature to a detector.
# Theory mode should keep this registry broad enough that every pixel in every
# seen state lies inside at least one component bounding box.
COMPONENT_REGISTRY: dict[str, ComponentDetector] = {}


def get_level_config(level: int) -> LevelConfig | None:
    return LEVEL_REGISTRY.get(int(level))


# ---------------------------------------------------------------------------
# Feature definitions template (fill with evidence-backed entries).
#
# FEATURE_DEFINITIONS = [
#   {
#     "name": "feature_x",
#     "shape": "describe visual shape/extent",
#     "mechanics": [
#       {"confidence": "low|medium|high", "claim": "...", "evidence": ["..."]},
#     ],
#   },
# ]
# ---------------------------------------------------------------------------


def get_feature_positions(grid):
    """Return discovered feature positions from current grid.

    Start simple and deterministic. Suggested return shape:
      {
        "feature_x": [(row, col), ...],
        "feature_y": [(row, col), ...],
        "composite_feature_z": {"anchor": (row, col), "cells": [(row, col), ...]},
      }

    Important:
    - Prefer evidence-backed neutral names until a role is proven.
    - Return all detected copies of a feature unless evidence proves uniqueness.
    """
    _ = grid
    return {}


def iter_components(grid: np.ndarray) -> list[ComponentBox]:
    """Return all detected components for a grid.

    Keep detectors evidence-backed and plural-first.
    Each detector should return every visible copy of its feature.
    """
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


def load_initial_grid(game_dir: str | Path, level: int) -> np.ndarray | None:
    """Load an initial grid using run-local artifact helpers.

    Accepts either `str` or `Path` so quick one-off debugging snippets do not
    fail on path-type friction.
    """
    rows = artifact_helpers.load_level_hex_rows(game_dir, level, kind="initial")
    if not rows:
        return None
    return np.array([[int(ch, 16) for ch in row] for row in rows], dtype=np.int8)


# ---------------------------------------------------------------------------
# Example helpers/mechanics (commented out by default):
#
# def find_all_feature_x(grid):
#     \"\"\"Return every observed copy of feature_x, not just the first one.\"\"\"
#     matches = []
#     _ = grid, matches
#     return matches
#
# def trigger_feature_x_at(env, row, col):
#     \"\"\"Apply an evidence-backed interaction at one feature location.\"\"\"
#     _ = env, row, col
#
# def apply_example_mechanic(env, feature_positions, action):
#     \"\"\"Example state transform skeleton using neutral feature names.\"\"\"
#     feature_x_positions = feature_positions.get("feature_x", [])
#     if action.name == "ACTION1":
#         for row, col in feature_x_positions:
#             trigger_feature_x_at(env, row, col)
# ---------------------------------------------------------------------------


def is_level_complete(env) -> bool:
    """Stub completion check.

    Replace with level-aware completion criteria derived from evidence.
    """
    _ = env
    return False
