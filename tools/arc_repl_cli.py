#!/usr/bin/env python3
"""Command-line wrapper for arc_repl tool.

Usage:
  arc_repl [--enable-history-functions] status [--game-id GAME]
  arc_repl [--enable-history-functions] reset_level [--game-id GAME]
  arc_repl [--enable-history-functions] exec [--game-id GAME] < script.py
  arc_repl [--enable-history-functions] exec_file [--game-id GAME] [--reset-level-first] SCRIPT_PATH
  arc_repl shutdown

Output contract:
- status/reset_level/shutdown: JSON object
- exec: raw script stdout/stderr plus an `<arc_repl_result>` JSON block
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


TOOL = Path(__file__).resolve().parent / "arc_repl.py"
SCHEMA_VERSION = "arc_repl.v1"


def _emit_json(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, indent=2))
    if not sys.stdout.isatty():
        sys.stdout.write("\n")


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        _emit_json(
            {
                "schema_version": SCHEMA_VERSION,
                "ok": False,
                "action": "",
                "requested_game_id": "",
                "error": {
                    "type": "cli_parse_error",
                    "message": str(message),
                },
            }
        )
        raise SystemExit(2)


def _run(payload: dict) -> int:
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


def main() -> int:
    parser = JsonArgumentParser(description="ARC REPL CLI")
    parser.add_argument(
        "--enable-history-functions",
        action="store_true",
        help=(
            "Enable read-only action-history helpers (`get_action_history`, "
            "`get_action_record`) inside arc_repl exec globals."
        ),
    )
    sub = parser.add_subparsers(dest="action", required=True)

    p_status = sub.add_parser("status")
    p_status.add_argument("--game-id", default="")

    p_reset = sub.add_parser("reset_level")
    p_reset.add_argument("--game-id", default="")

    p_exec = sub.add_parser("exec")
    p_exec.add_argument("--game-id", default="")

    p_exec_file = sub.add_parser("exec_file")
    p_exec_file.add_argument("--game-id", default="")
    p_exec_file.add_argument(
        "--reset-level-first",
        action="store_true",
        help="reset the live level to its initial state before executing the script",
    )
    p_exec_file.add_argument("script_path")

    sub.add_parser("shutdown")

    args = parser.parse_args()

    payload: dict[str, object] = {"action": args.action}
    if bool(getattr(args, "enable_history_functions", False)):
        payload["enable_history_functions"] = True
    game_id = str(getattr(args, "game_id", "") or "").strip()
    if game_id:
        payload["game_id"] = game_id

    if args.action == "exec":
        if sys.stdin.isatty():
            _emit_json(
                {
                    "schema_version": SCHEMA_VERSION,
                    "ok": False,
                    "action": "exec",
                    "requested_game_id": game_id,
                    "error": {
                        "type": "invalid_exec_args",
                        "message": "exec requires script content on stdin",
                    },
                }
            )
            return 2
        script = sys.stdin.read()
        if not script.strip():
            _emit_json(
                {
                    "schema_version": SCHEMA_VERSION,
                    "ok": False,
                    "action": "exec",
                    "requested_game_id": game_id,
                    "error": {
                        "type": "invalid_exec_args",
                        "message": "exec stdin script is empty",
                    },
                }
            )
            return 2
        payload["script"] = script
    elif args.action == "exec_file":
        script_path = Path(str(getattr(args, "script_path", "") or "").strip())
        if not script_path:
            _emit_json(
                {
                    "schema_version": SCHEMA_VERSION,
                    "ok": False,
                    "action": "exec_file",
                    "requested_game_id": game_id,
                    "error": {
                        "type": "invalid_exec_file_args",
                        "message": "exec_file requires SCRIPT_PATH",
                    },
                }
            )
            return 2
        try:
            script = script_path.read_text()
        except Exception as exc:
            _emit_json(
                {
                    "schema_version": SCHEMA_VERSION,
                    "ok": False,
                    "action": "exec_file",
                    "requested_game_id": game_id,
                    "error": {
                        "type": "invalid_exec_file_args",
                        "message": f"failed reading script file: {script_path}: {exc}",
                    },
                }
            )
            return 2
        if not script.strip():
            _emit_json(
                {
                    "schema_version": SCHEMA_VERSION,
                    "ok": False,
                    "action": "exec_file",
                    "requested_game_id": game_id,
                    "error": {
                        "type": "invalid_exec_file_args",
                        "message": f"exec_file script is empty: {script_path}",
                    },
                }
            )
            return 2
        payload["action"] = "exec"
        payload["script"] = script
        payload["script_path"] = str(script_path.resolve())
        if bool(getattr(args, "reset_level_first", False)):
            payload["reset_level_first"] = True

    return _run(payload)


if __name__ == "__main__":
    raise SystemExit(main())
