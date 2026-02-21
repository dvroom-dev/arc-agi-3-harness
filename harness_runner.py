from __future__ import annotations

import json
import re
import sys
import time
from argparse import Namespace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harness_explore import run_input_exploration_from_reset
from harness_runtime import HarnessRuntime
from harness_scorecard_timeout_hack import (
    has_new_agent_steps,
    maybe_inject_scorecard_keepalive_hack,
)


def _resolve_arc_base_url(args) -> str:
    if args.arc_base_url and str(args.arc_base_url).strip():
        return str(args.arc_base_url).strip()
    if args.arc_backend == "server":
        return "http://127.0.0.1:8000"
    return "https://three.arcprize.org"


def _resolve_game_ids(args) -> list[str]:
    raw = str(getattr(args, "game_ids", "") or "").strip()
    if not raw:
        gid = str(args.game_id or "").strip()
        if not gid:
            raise RuntimeError("No game ID provided.")
        return [gid]
    tokens = [t.strip() for t in re.split(r"[,\s]+", raw) if t.strip()]
    if not tokens:
        raise RuntimeError("Failed to parse --game-ids (expected comma/space-separated IDs).")
    unique: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        if token in seen:
            continue
        seen.add(token)
        unique.append(token)
    return unique


def _session_name_for_game(session_base: str, game_id: str, index: int) -> str:
    safe_game = re.sub(r"[^A-Za-z0-9_.-]+", "-", game_id).strip("-")
    if not safe_game:
        safe_game = f"game-{index:02d}"
    return f"{session_base}-{index:02d}-{safe_game}"


def _build_scorecard_client(
    *,
    operation_mode_name: str,
    arc_base_url: str,
    environments_dir: Path,
):
    import arc_agi
    from arc_agi import OperationMode

    mode = OperationMode[operation_mode_name]
    return arc_agi.Arcade(
        operation_mode=mode,
        arc_base_url=arc_base_url,
        environments_dir=str(environments_dir),
    )


def _open_shared_scorecard(
    *,
    args,
    game_ids: list[str],
    operation_mode_name: str,
    arc_base_url: str,
    session_base: str,
) -> tuple[Any, str, str, str]:
    if operation_mode_name != "ONLINE":
        raise RuntimeError(
            "Scorecards require ONLINE mode. Re-run with --operation-mode ONLINE."
        )
    environments_dir = Path("/tmp/arc-agi-env-cache") / f"{session_base}-scorecard"
    environments_dir.mkdir(parents=True, exist_ok=True)
    client = _build_scorecard_client(
        operation_mode_name=operation_mode_name,
        arc_base_url=arc_base_url,
        environments_dir=environments_dir,
    )
    tags = [
        "arc-agi-harness",
        "tool-driven",
        "multi-game-batch",
    ]
    for gid in game_ids:
        tags.append(f"game:{gid}")
    opaque = {
        "session_name": session_base,
        "game_ids": game_ids,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    scorecard_id = str(client.open_scorecard(tags=tags, opaque=opaque))
    api_url = f"{arc_base_url.rstrip('/')}/api/scorecard/{scorecard_id}"
    web_url = f"{arc_base_url.rstrip('/')}/scorecards/{scorecard_id}"
    return client, scorecard_id, api_url, web_url


def _close_shared_scorecard(*, log, client, scorecard_id: str) -> None:
    try:
        final = client.close_scorecard(scorecard_id)
        score = getattr(final, "score", None) if final is not None else None
        log(f"[harness] scorecard closed: id={scorecard_id} score={score}")
    except Exception as exc:
        log(f"[harness] WARNING: failed to close shared scorecard id={scorecard_id}: {exc}")


def _run_single_game(
    deps,
    args,
    *,
    operation_mode_name: str,
    arc_base_url: str,
    game_index: int,
    total_games: int,
) -> None:
    runtime = HarnessRuntime(
        deps,
        args,
        operation_mode_name=operation_mode_name,
        arc_base_url=arc_base_url,
    )

    runtime.log(f"[harness] session: {runtime.session_dir}")
    runtime.log(f"[harness] run dir: {runtime.run_dir}")
    runtime.log(f"[harness] agent dir: {runtime.agent_dir}")
    runtime.log(f"[harness] supervisor dir: {runtime.supervisor_dir}")
    runtime.log(f"[harness] arc state dir: {runtime.arc_state_dir}")
    runtime.log(f"[harness] game: {args.game_id} ({game_index}/{total_games})")
    runtime.log(f"[harness] arc backend: {args.arc_backend}")
    runtime.log(f"[harness] arc base url: {arc_base_url}")
    if runtime.offline_mode:
        runtime.log(
            "[harness] NOTE: operation-mode OFFLINE ignores ARC backend/base-url "
            "and uses local environments only."
        )
    if runtime.active_scorecard_id:
        created_status = "created_new" if runtime.scorecard_created_here else "reusing_existing"
        runtime.log(f"[harness] scorecard: {runtime.active_scorecard_id} ({created_status})")
        if runtime.scorecard_web_url:
            runtime.log(f"[harness] scorecard web url: {runtime.scorecard_web_url}")
        if runtime.scorecard_api_url:
            runtime.log(f"[harness] scorecard api url: {runtime.scorecard_api_url}")
    if args.no_explore:
        runtime.log("[harness] auto input exploration is disabled (--no-explore).")
    else:
        runtime.log("[harness] auto input exploration is enabled.")
    runtime.log("[harness] level-start prompt image attachments are disabled.")

    try:
        init_result, _, init_rc = runtime.run_arc_repl({"action": "status", "game_id": args.game_id})
        if init_rc != 0:
            runtime.log("[harness] failed to initialize state with arc_repl status")
            deps.sys.exit(1)

        runtime.log(f"[harness] active game id: {runtime.active_game_id}")
        runtime.log(f"[harness] initialized: {runtime.format_state_summary(runtime.load_state())}")

        initial_prompt = (
            "Game state initialized. Use shell exactly once this turn to execute arc_repl "
            "(status, exec, or reset_level). "
            "For exec, pass Python via stdin heredoc, e.g. "
            "`cat <<'PY' | arc_repl exec` ... `PY`. "
            "Inside exec scripts, use `get_state()` and `env` for state inspection and actions. "
            "Use agent_lib.py for persistent reusable helper functions."
        )
        if init_result and isinstance(init_result.get("state"), str):
            initial_prompt += f"\nCurrent state: {init_result.get('state')}"

        safe_game = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(args.game_id)).strip("_") or "game"
        runtime.auto_explore_once_marker = (
            runtime.arc_state_dir / f"auto_explore_once_{safe_game}.done"
        )

        init_state = runtime.load_state() or {}
        at_fresh_game_start = (
            int(init_state.get("current_level", 0) or 0) == 1
            and int(init_state.get("levels_completed", 0) or 0) == 0
        )
        should_auto_explore_once = (
            (not args.no_explore)
            and at_fresh_game_start
            and (not runtime.auto_explore_once_marker.exists())
        )
        if should_auto_explore_once:
            auto_explore_summary = run_input_exploration_from_reset(runtime)
            if auto_explore_summary.strip():
                initial_prompt += "\n\n" + auto_explore_summary
            runtime.auto_explore_once_marker.parent.mkdir(parents=True, exist_ok=True)
            runtime.auto_explore_once_marker.write_text(datetime.now(timezone.utc).isoformat() + "\n")
            runtime.log("[harness] auto input exploration completed (one-time at game start).")
        elif not args.no_explore:
            if not at_fresh_game_start:
                runtime.log("[harness] skipping auto input exploration (not fresh game start).")
            else:
                runtime.log("[harness] skipping auto input exploration (already ran once).")

        runtime.log("[harness] starting super new...")
        init_images = runtime.level_start_prompt_images(init_state, initial=True)
        runtime.super_env["ARC_CONVERSATION_ID"] = runtime.active_conversation_id
        deps.run_super(
            [
                "new",
                "--config", str(runtime.super_config),
                "--workspace", str(runtime.run_dir),
                "--config-dir", str(runtime.run_config_dir),
                "--agent-dir", str(runtime.agent_dir),
                "--supervisor-dir", str(runtime.supervisor_dir),
                *runtime.provider_args(),
                *runtime.supervisor_args(),
                "--cycle-limit", str(runtime.cycle_limit),
                *runtime.prompt_args(initial_prompt, prompt_kind="new", image_paths=init_images),
                "--output", str(runtime.session_file),
            ],
            stream=args.verbose,
            cwd=runtime.run_dir,
            env=runtime.super_env,
        )
        runtime.sync_active_conversation_id_from_session()
        history_events_after_new = deps.load_history_events(runtime.history_json)
        agent_history_floor = len(history_events_after_new)
        processed_history_len = len(history_events_after_new)
        last_scorecard_action_at = time.monotonic()

        super_turn = 1
        stale_turns = 0
        game_over_resets = 0
        last_engine_turn = runtime.load_engine_turn()
        last_recorded_completed_level = deps.read_max_recorded_completion_level(runtime.completions_md)
        pending_auto_explore_summary = ""

        while True:
            if args.max_turns is not None and super_turn > args.max_turns:
                runtime.log(f"[harness] max turns ({args.max_turns}) reached")
                break

            last_scorecard_action_at, injected_keepalive = maybe_inject_scorecard_keepalive_hack(
                runtime,
                last_action_at_monotonic=last_scorecard_action_at,
                agent_history_floor=agent_history_floor,
            )
            if injected_keepalive:
                history_after_keepalive = deps.load_history_events(runtime.history_json)
                processed_history_len = len(history_after_keepalive)
                last_engine_turn = runtime.load_engine_turn()

            state = runtime.load_state()
            prev_completed = int(state.get("levels_completed", 0)) if state else 0
            runtime.log(f"[harness] turn {super_turn}: {runtime.format_state_summary(state)}")

            if state and state.get("state") == "WIN":
                runtime.log(f"[harness] GAME WON after {super_turn} turns")
                break

            prompt_lines: list[str] = []
            current_engine_turn = runtime.load_engine_turn()
            if current_engine_turn <= last_engine_turn:
                stale_turns += 1
            else:
                stale_turns = 0
                last_engine_turn = current_engine_turn

            if state and state.get("state") == "GAME_OVER":
                game_over_resets += 1
                runtime.log(
                    f"[harness] GAME_OVER detected "
                    f"(auto-reset {game_over_resets}/{args.max_game_over_resets})"
                )
                if game_over_resets > args.max_game_over_resets:
                    runtime.log("[harness] max GAME_OVER auto-resets reached, stopping")
                    break
                reset_result, reset_stdout, reset_rc = runtime.run_arc_repl(
                    {"action": "reset_level", "game_id": args.game_id}
                )
                if reset_rc != 0:
                    runtime.log("[harness] auto-reset failed")
                    if reset_stdout:
                        runtime.log(f"[harness] reset output: {reset_stdout}")
                    break
                state = runtime.load_state()
                prompt_lines.append(
                    "Previous script ended in GAME_OVER. Harness auto-reset the level. "
                    "Continue from the new post-reset state."
                )
                if reset_result:
                    prompt_lines.append(f"Reset result: {json.dumps(reset_result)}")

            if stale_turns >= 2:
                prompt_lines.append(
                    "No arc_repl execution was detected in recent turns. "
                    "Execute exactly one shell command invoking arc_repl this turn."
                )
            if pending_auto_explore_summary.strip():
                prompt_lines.append(pending_auto_explore_summary.strip())
                pending_auto_explore_summary = ""

            prompt_lines.append(f"Current summary: {runtime.format_state_summary(state)}")
            prompt_lines.append("Continue solving the current level.")
            prompt = "\n".join(prompt_lines)

            prompt_images = runtime.level_start_prompt_images(state)
            stdout = runtime.resume_super(prompt, image_paths=prompt_images)
            runtime.sync_active_conversation_id_from_session()
            if not stdout.strip():
                runtime.log(
                    "[harness] super returned empty assistant response; "
                    "continuing (likely supervisor fork/transition without assistant text)."
                )
            history_after_resume = deps.load_history_events(runtime.history_json)
            if has_new_agent_steps(
                events=history_after_resume,
                since_event_index=processed_history_len,
                agent_history_floor=agent_history_floor,
            ):
                last_scorecard_action_at = time.monotonic()
            processed_history_len = len(history_after_resume)

            post_state = runtime.load_state()
            post_completed = int(post_state.get("levels_completed", 0)) if post_state else 0
            if post_completed > prev_completed:
                last_recorded_completed_level = max(
                    last_recorded_completed_level,
                    deps.read_max_recorded_completion_level(runtime.completions_md),
                )
                events = deps.load_history_events(runtime.history_json)
                completion_windows = deps.completion_action_windows_by_level(events)
                tool_turn = runtime.load_engine_turn()
                win_script = runtime.arc_state_dir / "script-history" / f"turn_{tool_turn:03d}_script.py"
                win_script_rel = None
                if win_script.exists():
                    try:
                        win_script_rel = str(win_script.relative_to(runtime.run_dir))
                    except Exception:
                        win_script_rel = str(win_script)

                for completed_level in range(prev_completed + 1, post_completed + 1):
                    if completed_level <= last_recorded_completed_level:
                        continue
                    level_actions = completion_windows.get(completed_level, [])
                    deps.append_level_completion_record(
                        completions_file=runtime.completions_md,
                        completed_level=completed_level,
                        actions=level_actions,
                        harness_turn=super_turn,
                        tool_turn=tool_turn,
                        winning_script_relpath=win_script_rel,
                    )
                    last_recorded_completed_level = completed_level
                    runtime.log(
                        "[harness] level completion recorded: "
                        f"level={completed_level} actions_in_level_window={len(level_actions)}"
                    )
                if not args.no_explore and (post_state and post_state.get("state") != "WIN"):
                    runtime.log(
                        "[harness] skipping post-completion auto exploration "
                        "(reset_level would reset campaign progress)"
                    )

            super_turn += 1

        runtime.log(f"[harness] session files: {runtime.session_dir}")
    finally:
        runtime.close_scorecard_if_needed()
        runtime.cleanup_repl_daemons()


def run_main(deps) -> None:
    args = deps.parse_args()
    operation_mode_name = str(args.operation_mode).strip().upper()
    if args.open_scorecard and args.scorecard_id:
        raise RuntimeError(
            "Use either --open-scorecard (create new) or --scorecard-id (reuse existing), not both."
        )
    game_ids = _resolve_game_ids(args)
    arc_base_url = _resolve_arc_base_url(args)

    session_base = args.session_name or datetime.now().strftime("%Y%m%d_%H%M%S")
    shared_scorecard_id = str(args.scorecard_id or "").strip() or None
    shared_scorecard_client = None
    shared_scorecard_created_here = False

    if len(game_ids) > 1 and args.open_scorecard:
        (
            shared_scorecard_client,
            shared_scorecard_id,
            scorecard_api_url,
            scorecard_web_url,
        ) = _open_shared_scorecard(
            args=args,
            game_ids=game_ids,
            operation_mode_name=operation_mode_name,
            arc_base_url=arc_base_url,
            session_base=session_base,
        )
        shared_scorecard_created_here = True
        print(
            f"[harness] scorecard: {shared_scorecard_id} (created_new, shared across {len(game_ids)} games)",
            file=sys.stderr,
            flush=True,
        )
        print(f"[harness] scorecard web url: {scorecard_web_url}", file=sys.stderr, flush=True)
        print(f"[harness] scorecard api url: {scorecard_api_url}", file=sys.stderr, flush=True)

    try:
        for index, game_id in enumerate(game_ids, start=1):
            game_args = Namespace(**vars(args))
            game_args.game_id = game_id
            if len(game_ids) > 1:
                game_args.session_name = _session_name_for_game(session_base, game_id, index)
            if shared_scorecard_id:
                game_args.open_scorecard = False
                game_args.scorecard_id = shared_scorecard_id
            _run_single_game(
                deps,
                game_args,
                operation_mode_name=operation_mode_name,
                arc_base_url=arc_base_url,
                game_index=index,
                total_games=len(game_ids),
            )
    finally:
        if (
            len(game_ids) > 1
            and shared_scorecard_created_here
            and shared_scorecard_client is not None
            and shared_scorecard_id
        ):
            _close_shared_scorecard(
                log=lambda msg: print(msg, file=sys.stderr, flush=True),
                client=shared_scorecard_client,
                scorecard_id=shared_scorecard_id,
            )
