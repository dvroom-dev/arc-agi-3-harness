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
    file_cmd.add_argument(
        "--reset-level-first",
        action="store_true",
        help="reset the selected model level to its initial state before executing the script",
    )
    file_cmd.add_argument("script_path")
    shutdown_cmd = sub.add_parser("shutdown")
    shutdown_cmd.add_argument("--game-id", default="game")
    return parser


def _emit(
    payload: dict,
    *,
    session: ModelSession,
    action_name: str,
    code: int | None = None,
    persist_status: bool = True,
) -> int:
    exit_code = 0 if code is None and payload.get("ok") else 1 if code is None else int(code)
    if persist_status:
        session.persist_model_status(payload, action_name=action_name, exit_code=exit_code)
    inject_idle_hint(payload, action_name=action_name)
    print(json.dumps(payload, indent=2))
    return exit_code


def run_model_cli(hooks: ModelHooks, *, game_dir: Path, argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        session = ModelSession(
            game_id=getattr(args, "game_id", "game"),
            game_dir=game_dir,
            hooks=hooks,
        )
    except Exception as exc:
        payload = {
            "ok": False,
            "action": str(getattr(args, "action", "unknown")),
            "error": {
                "type": "model_init_error",
                "message": str(exc),
            },
        }
        print(json.dumps(payload, indent=2))
        return 1
    if args.action == "status":
        return _emit(session.do_status(), session=session, action_name="status")
    if args.action == "reset_level":
        return _emit(session.do_reset_level(), session=session, action_name="reset_level")
    if args.action == "set_level":
        return _emit(session.do_set_level(int(args.level)), session=session, action_name="set_level")
    if args.action == "compare_sequences":
        payload, code = session.do_compare_sequences(
            level=args.level,
            sequence_id=args.sequence,
            include_reset_ended=bool(args.include_reset_ended),
            include_level_regressions=bool(args.include_level_regressions),
        )
        return _emit(payload, session=session, action_name="compare_sequences", code=code)
    if args.action == "exec":
        payload, code = session.do_exec(sys.stdin.read())
        return _emit(payload, session=session, action_name="exec", code=code)
    if args.action == "exec_file":
        payload, code = session.do_exec_file(
            Path(args.script_path),
            reset_level_first=bool(getattr(args, "reset_level_first", False)),
        )
        return _emit(payload, session=session, action_name="exec_file", code=code)
    if args.action == "shutdown":
        return _emit(
            session.do_shutdown(),
            session=session,
            action_name="shutdown",
            persist_status=False,
        )
    payload = {"ok": False, "error": {"type": "unknown_action", "message": str(args.action)}}
    return _emit(payload, session=session, action_name="unknown_action", code=1)
