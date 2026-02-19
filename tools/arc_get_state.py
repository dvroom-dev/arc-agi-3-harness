#!/usr/bin/env python3
"""Read current ARC machine state from ARC_STATE_DIR and emit JSON."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np


def _state_dir() -> Path:
    raw = os.getenv("ARC_STATE_DIR", "").strip()
    if not raw:
        raise RuntimeError("ARC_STATE_DIR is required")
    return Path(raw).expanduser()


def _grid_to_hex_rows(grid: np.ndarray) -> list[str]:
    return ["".join(f"{int(v):X}" for v in row) for row in grid]


def _emit(payload: dict) -> int:
    sys.stdout.write(json.dumps(payload, indent=2))
    if not sys.stdout.isatty():
        sys.stdout.write("\n")
    return 0 if payload.get("ok") else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Read ARC runtime state")
    parser.add_argument(
        "--no-grid",
        action="store_true",
        help="Do not include full grid hex rows",
    )
    args = parser.parse_args()

    try:
        arc_dir = _state_dir()
    except Exception as exc:
        return _emit(
            {
                "ok": False,
                "error": {
                    "type": "missing_state_dir",
                    "message": str(exc),
                },
            }
        )
    state_file = arc_dir / "state.json"
    grid_file = arc_dir / "current_grid.npy"
    game_state_file = arc_dir / "game-state.md"
    history_file = arc_dir / "tool-engine-history.json"

    if not state_file.exists():
        return _emit(
            {
                "ok": False,
                "error": {
                    "type": "missing_state",
                    "message": f"state file not found: {state_file}",
                },
            }
        )

    try:
        state = json.loads(state_file.read_text())
    except Exception as exc:
        return _emit(
            {
                "ok": False,
                "error": {
                    "type": "invalid_state_json",
                    "message": str(exc),
                },
            }
        )

    payload: dict = {
        "ok": True,
        "state": state,
        "artifacts": {
            "state_file": str(state_file),
            "grid_file": str(grid_file),
            "game_state_file": str(game_state_file),
            "history_file": str(history_file),
        },
    }

    if not args.no_grid and grid_file.exists():
        try:
            grid = np.load(grid_file)
            payload["grid_hex_rows"] = _grid_to_hex_rows(grid)
        except Exception as exc:
            return _emit(
                {
                    "ok": False,
                    "error": {
                        "type": "invalid_grid_file",
                        "message": str(exc),
                    },
                    "artifacts": payload["artifacts"],
                }
            )
    elif not args.no_grid and not grid_file.exists():
        return _emit(
            {
                "ok": False,
                "error": {
                    "type": "missing_grid",
                    "message": f"grid file not found: {grid_file}",
                },
                "artifacts": payload["artifacts"],
            }
        )

    return _emit(payload)


if __name__ == "__main__":
    raise SystemExit(main())
