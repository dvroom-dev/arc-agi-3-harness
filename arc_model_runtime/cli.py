from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .intercepts import inject_idle_hint
from .session import ModelHooks, ModelSession


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local ARC model scaffold")
    sub = parser.add_subparsers(dest="action", required=True)
    for name in ("status", "reset_level", "exec"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--game-id", default="game")
    set_level_cmd = sub.add_parser("set_level")
    set_level_cmd.add_argument("--game-id", default="game")
    set_level_cmd.add_argument("level", type=int)
    compare_cmd = sub.add_parser("compare_sequences")
    compare_cmd.add_argument("--game-id", default="game")
    compare_cmd.add_argument("--level", type=int, default=None)
    compare_cmd.add_argument("--sequence", default=None)
    compare_cmd.add_argument(
        "--include-reset-ended",
        action="store_true",
        help="include sequences that ended via reset_level",
    )
    compare_cmd.add_argument(
        "--include-level-regressions",
        action="store_true",
        help="include sequences that contain levels_completed regression events",
    )
    file_cmd = sub.add_parser("exec_file")
    file_cmd.add_argument("--game-id", default="game")
    file_cmd.add_argument("script_path")
    shutdown_cmd = sub.add_parser("shutdown")
    shutdown_cmd.add_argument("--game-id", default="game")
    return parser


def _emit(payload: dict, *, action_name: str) -> int:
    inject_idle_hint(payload, action_name=action_name)
    print(json.dumps(payload, indent=2))
    return 0 if payload.get("ok") else 1


def run_model_cli(hooks: ModelHooks, *, game_dir: Path, argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    session = ModelSession(
        game_id=getattr(args, "game_id", "game"),
        game_dir=game_dir,
        hooks=hooks,
    )
    if args.action == "status":
        return _emit(session.do_status(), action_name="status")
    if args.action == "reset_level":
        return _emit(session.do_reset_level(), action_name="reset_level")
    if args.action == "set_level":
        return _emit(session.do_set_level(int(args.level)), action_name="set_level")
    if args.action == "compare_sequences":
        payload, code = session.do_compare_sequences(
            level=args.level,
            sequence_id=args.sequence,
            include_reset_ended=bool(args.include_reset_ended),
            include_level_regressions=bool(args.include_level_regressions),
        )
        inject_idle_hint(payload, action_name="compare_sequences")
        print(json.dumps(payload, indent=2))
        return code
    if args.action == "exec":
        payload, code = session.do_exec(sys.stdin.read())
        inject_idle_hint(payload, action_name="exec")
        print(json.dumps(payload, indent=2))
        return code
    if args.action == "exec_file":
        payload, code = session.do_exec_file(Path(args.script_path))
        inject_idle_hint(payload, action_name="exec_file")
        print(json.dumps(payload, indent=2))
        return code
    if args.action == "shutdown":
        return _emit(session.do_shutdown(), action_name="shutdown")
    print(json.dumps({"ok": False, "error": {"type": "unknown_action", "message": str(args.action)}}))
    return 1
