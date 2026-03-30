#!/usr/bin/env python3
"""Run a single ARC real-game action through arc_repl exec.

Usage:
  arc_action ACTION1
  arc_action ACTION4 --game-id ls20

This is a thin convenience wrapper around `arc_repl exec` that keeps the
one-action probe path short and consistent for agents.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


TOOL = Path(__file__).resolve().parent / "arc_repl.py"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one ARC action probe")
    parser.add_argument("action_name")
    parser.add_argument("--game-id", default="")
    args = parser.parse_args()
    action_name = str(args.action_name or "").strip().upper()
    if not action_name.startswith("ACTION"):
        raise SystemExit("action_name must look like ACTION1..ACTION7")
    script = (
        "from arcengine import GameAction\n"
        f"env.step(GameAction.{action_name})\n"
    )
    payload: dict[str, object] = {
        "action": "exec",
        "script": script,
    }
    game_id = str(args.game_id or "").strip()
    if game_id:
        payload["game_id"] = game_id
    proc = subprocess.run(
        [sys.executable, str(TOOL)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        cwd=".",
    )
    if proc.stdout:
        sys.stdout.write(proc.stdout)
        if not proc.stdout.endswith("\n"):
            sys.stdout.write("\n")
    if proc.stderr:
        sys.stderr.write(proc.stderr)
        if not proc.stderr.endswith("\n"):
            sys.stderr.write("\n")
    return int(proc.returncode or 0)


if __name__ == "__main__":
    raise SystemExit(main())
