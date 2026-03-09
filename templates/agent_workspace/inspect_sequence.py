#!/usr/bin/env python3
"""Print a compact JSON summary for a sequence step or current compare mismatch."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import artifact_helpers


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-dir", default=".", help="Game workspace root (default: current dir)")
    parser.add_argument("--current-compare", action="store_true", help="Summarize current_compare.json and its canonical report paths")
    parser.add_argument("--current-mismatch", action="store_true", help="Inspect the first mismatched report from current_compare.json")
    parser.add_argument("--level", type=int, help="Level number for direct sequence inspection")
    parser.add_argument("--sequence", help="Sequence id such as seq_0002")
    parser.add_argument("--step", type=int, default=None, help="Local step number within the sequence")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    game_dir = Path(args.game_dir).resolve()

    if args.current_compare:
        payload = artifact_helpers.summarize_current_compare(game_dir)
    elif args.current_mismatch:
        payload = artifact_helpers.inspect_current_mismatch(game_dir)
    else:
        if args.level is None or not args.sequence:
            raise SystemExit("--level and --sequence are required unless --current-compare or --current-mismatch is used")
        payload = artifact_helpers.summarize_sequence_step(
            game_dir,
            level=args.level,
            sequence_id=args.sequence,
            local_step=args.step,
        )

    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
