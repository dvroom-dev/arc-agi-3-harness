#!/usr/bin/env python3
"""Summarize counts and bounding boxes for specific values in a visible workspace .hex grid."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import artifact_helpers


def _parse_value(raw: str) -> tuple[str, int]:
    text = str(raw).strip().upper()
    if len(text) != 1 or text not in "0123456789ABCDEF":
        raise argparse.ArgumentTypeError(f"value must be one hex digit 0-9 or A-F; got {raw!r}")
    return text, int(text, 16)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-dir", default=".", help="Game workspace root (default: current dir)")
    parser.add_argument("--file", required=True, help="Workspace-relative .hex file path")
    parser.add_argument(
        "--value",
        dest="values",
        action="append",
        required=True,
        type=_parse_value,
        help="Hex value to summarize; repeat for multiple values",
    )
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

    grid = artifact_helpers.load_hex_grid(target)
    payload = {
        "file": artifact_helpers.display_path(game_dir, target),
        "shape": [int(grid.shape[0]), int(grid.shape[1])],
        "values": [],
    }
    for symbol, numeric in args.values:
        positions = [(int(row), int(col)) for row, col in zip(*((grid == numeric).nonzero()), strict=False)]
        if positions:
            rows = [row for row, _col in positions]
            cols = [col for _row, col in positions]
            bbox = [min(rows), min(cols), max(rows), max(cols)]
        else:
            bbox = None
        payload["values"].append(
            {
                "value": symbol,
                "count": len(positions),
                "bbox": bbox,
            }
        )

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        for item in payload["values"]:
            if item["bbox"] is None:
                print(f"value {item['value']}: count=0")
            else:
                top, left, bottom, right = item["bbox"]
                print(
                    f"value {item['value']}: count={item['count']} "
                    f"bbox=rows {top}-{bottom} cols {left}-{right}"
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
