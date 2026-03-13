#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


def _state_path() -> Path:
    state_dir = str(os.environ.get("ARC_STATE_DIR", "")).strip()
    if not state_dir:
        raise RuntimeError("ARC_STATE_DIR is not set")
    return Path(state_dir) / "state.json"


def _load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"failed to parse {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"invalid state payload in {path}: expected object")
    return data


def _int_or_default(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _load_analysis_pin(game_dir: Path) -> dict[str, Any] | None:
    path = game_dir / ".analysis_level_pin.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _extract(data: dict[str, Any]) -> dict[str, Any]:
    frontier_level = max(1, _int_or_default(data.get("current_level"), 1))
    visible_level = frontier_level
    pin = _load_analysis_pin(Path.cwd())
    if isinstance(pin, dict):
        try:
            pinned_level = int(pin.get("level"))
        except Exception:
            pinned_level = frontier_level
        if pinned_level > 0 and pinned_level < frontier_level:
            visible_level = pinned_level
    return {
        "current_level": int(visible_level),
        "levels_completed": max(0, int(visible_level) - 1),
        "state": str(data.get("state", "") or "").strip() or "UNKNOWN",
    }


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read current ARC level/state from ARC_STATE_DIR/state.json.",
    )
    parser.add_argument(
        "--field",
        choices=["current_level", "levels_completed", "state"],
        default="current_level",
        help="Single field to print (default: current_level).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the full compact JSON payload.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        data = _extract(_load_state(_state_path()))
    except Exception as exc:
        print(f"arc_level error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(data, separators=(",", ":")))
        return 0
    print(data[args.field])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
