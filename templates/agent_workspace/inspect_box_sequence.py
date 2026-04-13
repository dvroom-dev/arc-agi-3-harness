#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np

import artifact_helpers


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect a generated feature box across sequence frames.")
    parser.add_argument("--game-dir", default=".", help="Model workspace / game dir")
    parser.add_argument("--level", type=int, required=True, help="Level number")
    parser.add_argument("--box", required=True, help="Box id from feature_boxes_level_<n>.json")
    parser.add_argument("--sequence", help="Optional sequence id to inspect; defaults to all sequences")
    return parser.parse_args()


def crop(grid: np.ndarray, bbox: list[int]) -> list[str]:
    row0, col0, row1, col1 = [int(value) for value in bbox]
    window = grid[row0 : row1 + 1, col0 : col1 + 1]
    return ["".join(format(int(value), "X") for value in row) for row in window]


def main() -> int:
    args = parse_args()
    game_dir = Path(args.game_dir).resolve()
    feature_boxes_path = game_dir / f"feature_boxes_level_{int(args.level)}.json"
    payload = json.loads(feature_boxes_path.read_text())
    boxes = payload.get("boxes") if isinstance(payload.get("boxes"), list) else []
    target = next((box for box in boxes if isinstance(box, dict) and str(box.get("box_id", "")) == str(args.box)), None)
    if not isinstance(target, dict):
        raise RuntimeError(f"box not found: {args.box}")
    bbox = target.get("bbox")
    if not isinstance(bbox, list) or len(bbox) != 4:
        raise RuntimeError(f"invalid bbox for {args.box}")

    sequences = list(artifact_helpers.iter_level_sequences(game_dir, int(args.level)))
    if args.sequence:
        sequences = [seq for seq in sequences if str(seq.get("sequence_id", "")) == str(args.sequence)]

    out: dict[str, Any] = {
        "level": int(args.level),
        "box_id": str(args.box),
        "bbox": [int(value) for value in bbox],
        "sequences": [],
    }
    level_root = artifact_helpers.level_dir(game_dir, int(args.level))
    for sequence in sequences:
        actions = sequence.get("actions") if isinstance(sequence.get("actions"), list) else []
        seq_out: dict[str, Any] = {
            "sequence_id": str(sequence.get("sequence_id", "")),
            "steps": [],
        }
        for action in actions:
            if not isinstance(action, dict):
                continue
            files = action.get("files") if isinstance(action.get("files"), dict) else {}
            before_rel = str(files.get("before_state_hex", "") or "")
            after_rel = str(files.get("after_state_hex", "") or "")
            if not before_rel or not after_rel:
                continue
            before_grid = artifact_helpers.load_hex_grid(level_root / before_rel)
            after_grid = artifact_helpers.load_hex_grid(level_root / after_rel)
            frame_rows: list[dict[str, Any]] = []
            for frame_index, rel in enumerate(files.get("frame_sequence_hex", []) if isinstance(files.get("frame_sequence_hex"), list) else [], start=1):
                frame_path = level_root / str(rel)
                if not frame_path.exists():
                    continue
                frame_grid = artifact_helpers.load_hex_grid(frame_path)
                frame_rows.append({
                    "frame_index": frame_index,
                    "crop": crop(frame_grid, bbox),
                })
            seq_out["steps"].append({
                "local_step": int(action.get("local_step", 0) or 0),
                "action_name": str(action.get("action_name", "") or ""),
                "before_crop": crop(before_grid, bbox),
                "after_crop": crop(after_grid, bbox),
                "frames": frame_rows,
            })
        out["sequences"].append(seq_out)
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
