#!/usr/bin/env python3
"""Print a compact slice from a visible workspace .hex grid."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import artifact_helpers


def _parse_range(value: str, *, label: str) -> tuple[int, int]:
    try:
        start_text, end_text = str(value).split(":", 1)
        start = int(start_text)
        end = int(end_text)
    except Exception as exc:
        raise argparse.ArgumentTypeError(f"{label} must be START:END") from exc
    if start < 0 or end < start:
        raise argparse.ArgumentTypeError(f"{label} must satisfy 0 <= START <= END")
    return start, end


def _normalize_range(*, start: int, end: int, size: int, label: str) -> int:
    """Accept inclusive END, plus END==size as a full-span convenience."""
    if end == size:
        return end
    if end > size - 1:
        raise SystemExit(
            f"{label} range {start}:{end} exceeds {label} count {size}; "
            f"max inclusive index is {size - 1}, or use END={size} for a full-span slice"
        )
    return end + 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-dir", default=".", help="Game workspace root (default: current dir)")
    parser.add_argument("--file", required=True, help="Workspace-relative .hex file path")
    parser.add_argument("--rows", required=True, type=lambda value: _parse_range(value, label="rows"))
    parser.add_argument("--cols", required=True, type=lambda value: _parse_range(value, label="cols"))
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of compact text lines")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    game_dir = Path(args.game_dir).resolve()
    target = (game_dir / args.file).resolve()
    try:
        target.relative_to(game_dir)
    except ValueError as exc:
        raise SystemExit(f"--file must stay inside the workspace: {args.file}") from exc
    if not target.exists():
        raise SystemExit(f"file not found: {args.file}")

    rows = artifact_helpers.load_hex_rows(target)
    if not rows:
        raise SystemExit(f"no hex rows found in: {args.file}")

    row_start, row_end = args.rows
    col_start, col_end = args.cols
    row_stop = _normalize_range(start=row_start, end=row_end, size=len(rows), label="row")
    width = len(rows[0])
    if any(len(row) != width for row in rows):
        raise SystemExit("hex grid rows are not rectangular")
    col_stop = _normalize_range(start=col_start, end=col_end, size=width, label="col")
    row_display_end = row_stop - 1
    col_display_end = col_stop - 1

    payload = {
        "file": artifact_helpers.display_path(game_dir, target),
        "row_range": [row_start, row_display_end],
        "col_range": [col_start, col_display_end],
        "rows": [
            {
                "row": row_index,
                "slice": rows[row_index][col_start:col_stop],
            }
            for row_index in range(row_start, row_stop)
        ],
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        for item in payload["rows"]:
            print(f"row {item['row']} cols {col_start}-{col_display_end}: {item['slice']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
