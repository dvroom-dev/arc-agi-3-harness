from __future__ import annotations

from typing import Any

import numpy as np

from game_state import COLOR_NAMES, _connected_components_8


def format_change_records(changes: list[dict]) -> str:
    """Format tool diff records (`changes`) as explicit cell transitions."""
    if not changes:
        return "(no changes)"
    lines = [
        f"changed_pixels={len(changes)}",
        "format: (row,col): before->after",
    ]
    skipped = 0
    for ch in changes:
        try:
            row = int(ch.get("row"))
            col = int(ch.get("col"))
            before = str(ch.get("before", "?"))
            after = str(ch.get("after", "?"))
        except Exception:
            skipped += 1
            continue
        lines.append(f"({row},{col}): {before}->{after}")
    if len(lines) <= 2:
        return "(invalid change records)"
    if skipped:
        lines.append(f"note: skipped_malformed_change_records={skipped}")
    return "\n".join(lines)


def diff_change_records(before: np.ndarray, after: np.ndarray) -> list[dict]:
    """Return per-cell before/after records between two 64x64 grids."""
    if before.shape != after.shape:
        raise RuntimeError(
            f"Grid shape mismatch for diff generation: before={before.shape} after={after.shape}"
        )
    changed = np.argwhere(before != after)
    records: list[dict] = []
    for row, col in changed:
        r = int(row)
        c = int(col)
        records.append(
            {
                "row": r,
                "col": c,
                "before": f"{int(before[r, c]):X}",
                "after": f"{int(after[r, c]):X}",
            }
        )
    return records


def collect_palette_from_change_records(changes: list[dict]) -> set[int]:
    """Collect numeric color IDs appearing in change records."""
    palette: set[int] = set()
    for ch in changes:
        before = _parse_color_id(ch.get("before"))
        after = _parse_color_id(ch.get("after"))
        if before is not None:
            palette.add(before)
        if after is not None:
            palette.add(after)
    return palette


def find_click_targets(pixels: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Find contiguous color regions and return their centroids as click targets.

    Returns list of (x, y, color_id, size) sorted by size descending.
    x/y are centroid coordinates (col, row) for ACTION6 data format.
    Skips color 0 (background).
    """
    targets: list[tuple[int, int, int, int]] = []
    seen_pixels: set[tuple[int, int]] = set()

    for color_id in range(1, 16):
        mask = pixels == color_id
        if not np.any(mask):
            continue
        components = _connected_components_8(mask)
        for component in components:
            size = len(component)
            rows = [p[0] for p in component]
            cols = [p[1] for p in component]
            cy = int(round(sum(rows) / size))
            cx = int(round(sum(cols) / size))
            if (cx, cy) not in seen_pixels:
                seen_pixels.add((cx, cy))
                targets.append((cx, cy, color_id, size))

    targets.sort(key=lambda t: t[3], reverse=True)
    return targets


def _parse_color_id(value: Any) -> int | None:
    """Parse a color token from tool diffs into an integer color id."""
    if value is None:
        return None
    try:
        if isinstance(value, int):
            return value
        s = str(value).strip()
        if not s:
            return None
        return int(s, 16)
    except Exception:
        return None


def summarize_static_features(
    pixels: np.ndarray,
    *,
    excluded_colors: set[int],
    max_components: int = 24,
) -> list[str]:
    """Summarize connected components in the reset frame for probe targeting."""
    entries: list[tuple[int, int, int, int, int, int, int, str]] = []
    for color_id in range(16):
        if color_id in excluded_colors:
            continue
        mask = pixels == color_id
        if not np.any(mask):
            continue
        components = _connected_components_8(mask)
        for component in components:
            if not component:
                continue
            size = len(component)
            rows = [int(p[0]) for p in component]
            cols = [int(p[1]) for p in component]
            r0, r1 = min(rows), max(rows)
            c0, c1 = min(cols), max(cols)
            h = r1 - r0 + 1
            w = c1 - c0 + 1
            cy = int(round(sum(rows) / size))
            cx = int(round(sum(cols) / size))
            color_name = COLOR_NAMES.get(color_id, f"color-{color_id:X}")
            entries.append((size, h * w, color_id, cx, cy, r0, c0, color_name))

    entries.sort(key=lambda t: (-t[0], t[1], t[2], t[4], t[3]))
    lines: list[str] = []
    for size, _, color_id, cx, cy, r0, c0, color_name in entries[:max_components]:
        lines.append(
            f"{color_name} (id={color_id:X}) size={size} origin=({r0},{c0}) center=({cy},{cx})"
        )
    return lines
