from __future__ import annotations

import re
import sys
import time
import traceback
from argparse import Namespace
from datetime import datetime, timezone
from pathlib import Path

from harness_explore import run_input_exploration_from_reset
from harness_repl_health import format_repl_health_summary
from harness_repl_health import collect_repl_health, format_repl_crash_diagnostics
from harness_runner_regression import (
    _classify_level_drop,
    _find_step_level_regression,
)
from harness_runtime import HarnessRuntime
from harness_scorecard_helpers import (
    close_shared_scorecard,
    open_shared_scorecard,
    run_scorecard_session_preflight,
    validate_scorecard_owner_check,
)
from harness_scorecard_timeout_hack import (
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
    if runtime.arc_api_key_prefix:
        runtime.log(f"[harness] arc api key prefix: {runtime.arc_api_key_prefix}")
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
    explore_inputs = bool(getattr(args, "explore_inputs", False))
    if explore_inputs:
        runtime.log("[harness] input exploration is enabled (--explore-inputs).")
    else:
        runtime.log("[harness] input exploration is disabled (default).")
    runtime.log("[harness] level-start prompt image attachments are disabled.")

    try:
        _, _, init_rc = runtime.run_arc_repl({"action": "status", "game_id": args.game_id})
        if init_rc != 0:
            runtime.log("[harness] failed to initialize state with arc_repl status")
            deps.sys.exit(1)

        runtime.log(f"[harness] active game id: {runtime.active_game_id}")
        runtime.log(f"[harness] initialized: {runtime.format_state_summary(runtime.load_state())}")

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
            explore_inputs
            and at_fresh_game_start
            and (not runtime.auto_explore_once_marker.exists())
        )
        if should_auto_explore_once:
            auto_explore_summary = run_input_exploration_from_reset(runtime)
            summary_file = runtime.arc_state_dir / "auto_explore_report.md"
            summary_file.write_text(auto_explore_summary.strip() + "\n", encoding="utf-8")
            runtime.auto_explore_once_marker.parent.mkdir(parents=True, exist_ok=True)
            runtime.auto_explore_once_marker.write_text(datetime.now(timezone.utc).isoformat() + "\n")
            runtime.log(
                "[harness] input exploration completed (one-time at game start): "
                f"{summary_file}"
            )
        elif explore_inputs:
            if not at_fresh_game_start:
                runtime.log("[harness] skipping auto input exploration (not fresh game start).")
            else:
                runtime.log("[harness] skipping auto input exploration (already ran once).")

        super_turn = 1
        game_over_resets = 0
        last_recorded_completed_level = deps.read_max_recorded_completion_level(runtime.completions_md)

        def _start_super_new(*, phase_label: str, start_mode: str | None = None) -> None:
            runtime.log(f"[harness] starting super new ({phase_label})...")
            runtime.super_env["ARC_CONVERSATION_ID"] = runtime.active_conversation_id
            cmd = [
                "new",
                "--config", str(runtime.super_config),
                "--workspace", str(runtime.run_dir),
                "--config-dir", str(runtime.run_config_dir),
                "--agent-dir", str(runtime.agent_dir),
                "--supervisor-dir", str(runtime.supervisor_dir),
                *runtime.provider_args(),
                *runtime.supervisor_args(),
                "--cycle-limit", str(runtime.cycle_limit),
                "--output", str(runtime.session_file),
            ]
            if start_mode:
                cmd.extend(["--start-mode", str(start_mode)])
            deps.run_super(
                cmd,
                stream=True,
                cwd=runtime.run_dir,
                env=runtime.super_env,
            )
            runtime.sync_active_conversation_id_from_session()
            monitor = runtime.monitor_snapshot()
            runtime.log(
                "[harness] monitor sources: "
                f"state={monitor['state_path']} "
                f"history={monitor['history_path']} "
                f"session={monitor['session_path']} "
                f"raw_events={monitor.get('raw_events_path') or '(not-found-yet)'}"
            )

        def _run_super_loop(*, keepalive_enabled: bool) -> bool:
            nonlocal super_turn
            nonlocal game_over_resets
            nonlocal last_recorded_completed_level

            history_events_after_new = runtime.load_history_events()
            agent_history_floor = len(history_events_after_new)
            processed_history_len = len(history_events_after_new)
            processed_engine_turn = runtime.load_engine_turn()
            last_scorecard_action_at = time.monotonic()

            while True:
                if args.max_turns is not None and super_turn > args.max_turns:
                    runtime.log(f"[harness] max turns ({args.max_turns}) reached")
                    return False

                if keepalive_enabled and runtime.active_scorecard_id:
                    last_scorecard_action_at, injected_keepalive = maybe_inject_scorecard_keepalive_hack(
                        runtime,
                        last_action_at_monotonic=last_scorecard_action_at,
                        agent_history_floor=agent_history_floor,
                    )
                    if injected_keepalive:
                        history_after_keepalive = runtime.load_history_events()
                        processed_history_len = len(history_after_keepalive)
                        processed_engine_turn = runtime.load_engine_turn()

                monitor = runtime.monitor_snapshot()
                state = monitor.get("state")
                prev_completed = int(state.get("levels_completed", 0)) if state else 0
                runtime.log(
                    f"[harness] turn {super_turn}: "
                    f"{runtime.format_state_summary(state, history_turn=int(monitor['history_turn']))}"
                )
                runtime.log(
                    "[harness] monitor: "
                    f"history_events={monitor['history_events_len']} "
                    f"raw_events_exists={monitor['raw_events_exists']} "
                    f"raw_events_size={monitor['raw_events_size_bytes']}B"
                )
                repl_health = collect_repl_health(runtime)
                runtime.log(f"[harness] {format_repl_health_summary(runtime)}")
                if bool(repl_health.get("is_crashed", False)):
                    runtime.log("[harness] REPL daemon crash detected; stopping run.")
                    runtime.log(f"[harness] {format_repl_crash_diagnostics(runtime, repl_health)}")
                    return False

                if state and state.get("state") == "WIN":
                    runtime.log(f"[harness] GAME WON after {super_turn} turns")
                    return True

                if state and state.get("state") == "GAME_OVER":
                    game_over_resets += 1
                    runtime.log(
                        f"[harness] GAME_OVER detected "
                        f"(auto-reset {game_over_resets}/{args.max_game_over_resets})"
                    )
                    if args.max_game_over_resets <= 0:
                        runtime.log(
                            "[harness] GAME_OVER auto-reset disabled "
                            "(--max-game-over-resets=0); stopping for agent/supervisor recovery."
                        )
                        return False
                    if game_over_resets > args.max_game_over_resets:
                        runtime.log("[harness] max GAME_OVER auto-resets reached, stopping")
                        return False
                    _, reset_stdout, reset_rc = runtime.run_arc_repl(
                        {"action": "reset_level", "game_id": args.game_id}
                    )
                    if reset_rc != 0:
                        runtime.log("[harness] auto-reset failed")
                        if reset_stdout:
                            runtime.log(f"[harness] reset output: {reset_stdout}")
                        return False
                    state = runtime.load_state()
                history_len_before_resume = processed_history_len
                stdout = runtime.resume_super()
                runtime.sync_active_conversation_id_from_session()
                if not stdout.strip():
                    runtime.log(
                        "[harness] super returned empty assistant response; "
                        "continuing (likely supervisor fork/transition without assistant text)."
                    )
                history_after_resume = runtime.load_history_events()
                new_events = (
                    history_after_resume[history_len_before_resume:]
                    if history_len_before_resume <= len(history_after_resume)
                    else history_after_resume
                )
                current_engine_turn = runtime.load_engine_turn()
                if current_engine_turn > processed_engine_turn:
                    last_scorecard_action_at = time.monotonic()
                processed_history_len = len(history_after_resume)
                processed_engine_turn = current_engine_turn

                post_state = runtime.load_state()
                post_completed = int(post_state.get("levels_completed", 0)) if post_state else 0
                drop = _classify_level_drop(
                    prev_state=state,
                    post_state=post_state,
                    new_events=new_events,
                )
                if drop and drop.get("kind") != "drop_after_game_over":
                    runtime.log(
                        "[harness] ERROR: level regression without GAME_OVER detected; "
                        "stopping run for diagnostics."
                    )
                    runtime.log(
                        "[harness] regression details: "
                        + ", ".join(
                            [
                                f"kind={drop.get('kind')}",
                                f"from={drop.get('from_levels_completed')}",
                                f"to={drop.get('to_levels_completed')}",
                                f"action={drop.get('action', '?')}",
                                f"event_offset={drop.get('event_offset', '?')}",
                            ]
                        )
                    )
                    return False
                if post_completed > prev_completed:
                    last_recorded_completed_level = max(
                        last_recorded_completed_level,
                        deps.read_max_recorded_completion_level(runtime.completions_md),
                    )
                    events = runtime.load_history_events()
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
                    if explore_inputs and (post_state and post_state.get("state") != "WIN"):
                        runtime.log(
                            "[harness] skipping post-completion auto exploration "
                            "(reset_level would reset campaign progress)"
                        )

                super_turn += 1

        score_after_solve = bool(getattr(args, "score_after_solve", False))
        replay_start_mode = str(
            getattr(args, "score_after_solve_start_mode", "recover") or "recover"
        ).strip() or "recover"

        _start_super_new(phase_label="discovery")
        discovery_won = _run_super_loop(keepalive_enabled=not score_after_solve)

        if score_after_solve and discovery_won and not runtime.active_scorecard_id:
            scorecard_id = runtime.open_scorecard_now()
            runtime.log(f"[harness] score-after-solve: opened scorecard id={scorecard_id}")
            if runtime.scorecard_web_url:
                runtime.log(f"[harness] scorecard web url: {runtime.scorecard_web_url}")
            if runtime.scorecard_api_url:
                runtime.log(f"[harness] scorecard api url: {runtime.scorecard_api_url}")

            runtime.active_conversation_id = "harness_bootstrap_scored"
            runtime.active_actual_conversation_id = None
            runtime.conversation_aliases = {}
            runtime.active_repl_session_key = f"{runtime.repl_session_key}__scored"
            runtime.super_env["ARC_REPL_SESSION_KEY"] = runtime.active_repl_session_key
            runtime.last_repl_daemon_pid = None

            _, reset_stdout, reset_rc = runtime.run_arc_repl(
                {"action": "reset_level", "game_id": args.game_id}
            )
            if reset_rc != 0:
                runtime.log("[harness] score-after-solve: failed to initialize scored replay state")
                if reset_stdout:
                    runtime.log(f"[harness] score-after-solve reset output: {reset_stdout}")
            else:
                runtime.log(
                    "[harness] score-after-solve: initialized scored replay at "
                    f"{runtime.format_state_summary(runtime.load_state())}"
                )
                _start_super_new(phase_label="scored-replay", start_mode=replay_start_mode)
                _run_super_loop(keepalive_enabled=False)

        runtime.log(f"[harness] session files: {runtime.session_dir}")
    except BaseException as exc:
        runtime.log(f"[harness] FATAL: {type(exc).__name__}: {exc}")
        runtime.log(traceback.format_exc().rstrip())
        raise
    finally:
        runtime.close_scorecard_if_needed()
        runtime.cleanup_repl_daemons()


def run_main(deps) -> None:
    args = deps.parse_args()
    operation_mode_name = str(args.operation_mode).strip().upper()
    score_after_solve = bool(getattr(args, "score_after_solve", False))
    if args.open_scorecard and args.scorecard_id:
        raise RuntimeError(
            "Use either --open-scorecard (create new) or --scorecard-id (reuse existing), not both."
        )
    if score_after_solve and (args.open_scorecard or args.scorecard_id):
        raise RuntimeError(
            "--score-after-solve cannot be combined with --open-scorecard/--scorecard-id. "
            "The harness will open a fresh scorecard only after unscored solve completes."
        )
    game_ids = _resolve_game_ids(args)
    if score_after_solve and len(game_ids) != 1:
        raise RuntimeError("--score-after-solve currently supports exactly one game ID.")
    arc_base_url = _resolve_arc_base_url(args)

    session_base = args.session_name or datetime.now().strftime("%Y%m%d_%H%M%S")
    shared_scorecard_id = str(args.scorecard_id or "").strip() or None
    shared_scorecard_client = None
    shared_scorecard_created_here = False
    shared_scorecard_cookies_json = (
        str(getattr(args, "scorecard_cookies_json", "") or "").strip() or None
    )

    if args.open_scorecard or shared_scorecard_id or score_after_solve:
        validate_scorecard_owner_check(
            args=args,
            operation_mode_name=operation_mode_name,
            arc_base_url=arc_base_url,
            session_base=session_base,
        )
        if bool(getattr(args, "scorecard_session_preflight", False)):
            run_scorecard_session_preflight(
                operation_mode_name=operation_mode_name,
                arc_base_url=arc_base_url,
                log=lambda msg: print(msg, file=sys.stderr, flush=True),
            )

    if len(game_ids) > 1 and args.open_scorecard:
        (
            shared_scorecard_client,
            shared_scorecard_id,
            scorecard_api_url,
            scorecard_web_url,
            shared_scorecard_cookies_json,
        ) = open_shared_scorecard(
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
                game_args.scorecard_cookies_json = shared_scorecard_cookies_json
                # Only skip per-game GET validation when the shared scorecard
                # was created by this process. For a user-supplied scorecard ID,
                # revalidate in each game session to avoid silent bad-ID runs.
                game_args.skip_scorecard_get_validation = bool(shared_scorecard_created_here)
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
            close_shared_scorecard(
                log=lambda msg: print(msg, file=sys.stderr, flush=True),
                client=shared_scorecard_client,
                scorecard_id=shared_scorecard_id,
            )
