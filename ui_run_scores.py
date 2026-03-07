from __future__ import annotations

import argparse
import contextlib
import io
import json
import logging
import math
import os
import sys
from pathlib import Path
from typing import Any

from arc_agi import Arcade, OperationMode
from arc_agi.models import EnvironmentInfo
from arc_agi.scorecard import Card, EnvironmentScore, EnvironmentScoreList, EnvironmentScorecard, GameState, Scorecard


DEFAULT_ARC_BASE_URL = "https://three.arcprize.org"


def _project_root() -> Path:
    return Path(__file__).resolve().parent


def _run_dir(project_root: Path, run_id: str) -> Path:
    return project_root / "runs" / run_id


def _ctx_dir(project_root: Path, run_id: str) -> Path:
    return project_root / ".ctxs" / run_id


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _arcade_logger() -> logging.Logger:
    logger = logging.getLogger("ui_run_scores.arcade")
    logger.handlers = []
    logger.propagate = False
    logger.setLevel(logging.CRITICAL)
    return logger


def _with_suppressed_stdout(fn, /, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*args, **kwargs)


def _load_environment_infos(arc_base_url: str) -> list[EnvironmentInfo]:
    arcade = _with_suppressed_stdout(
        Arcade,
        arc_api_key=os.environ.get("ARC_API_KEY", ""),
        arc_base_url=arc_base_url,
        operation_mode=OperationMode.NORMAL,
        logger=_arcade_logger(),
    )
    return list(arcade.available_environments)


def _build_card_from_history(
    game_id: str,
    history_payload: dict[str, Any],
    final_state: dict[str, Any],
) -> Card:
    card = Card.model_validate({"game_id": game_id})
    current_guid = "attempt-1"
    card.inc_play_count(current_guid)
    observed_levels_completed = 0

    for event in history_payload.get("events", []):
        kind = str(event.get("kind", "") or "").strip()
        if kind == "step":
            levels_completed = int(
                event.get("levels_completed", observed_levels_completed)
                or observed_levels_completed
            )
            if levels_completed < observed_levels_completed:
                current_guid = f"attempt-{len(card.guids) + 1}"
                card.inc_play_count(current_guid)
                observed_levels_completed = 0

            card.inc_action_count(current_guid)
            card.set_levels_completed(current_guid, levels_completed)
            observed_levels_completed = levels_completed
        elif kind == "reset":
            card.inc_reset_count(current_guid)

    final_levels_completed = int(
        final_state.get("levels_completed", observed_levels_completed)
        or observed_levels_completed
    )
    if final_levels_completed < observed_levels_completed:
        current_guid = f"attempt-{len(card.guids) + 1}"
        card.inc_play_count(current_guid)
    card.set_levels_completed(current_guid, final_levels_completed)

    state_name = str(final_state.get("state", "") or "NOT_FINISHED").strip()
    try:
        game_state = GameState(state_name)
    except Exception:
        game_state = GameState.NOT_FINISHED
    card.set_state(current_guid, game_state)
    return card


def _build_local_scorecard(
    run_id: str,
    history_payload: dict[str, Any],
    final_state: dict[str, Any],
    environment_infos: list[EnvironmentInfo],
) -> EnvironmentScorecard:
    game_id = str(
        history_payload.get("game_id")
        or final_state.get("game_id")
        or ""
    ).strip()
    if not game_id:
        raise RuntimeError("missing game_id in run artifacts")

    card = _build_card_from_history(game_id, history_payload, final_state)
    scorecard = Scorecard.model_validate(
        {
            "card_id": f"local::{run_id}",
            "cards": {
                game_id: card.model_dump(),
            },
        }
    )
    return _with_suppressed_stdout(
        EnvironmentScorecard.from_scorecard,
        scorecard,
        environment_infos,
    )


def _first_run_with_max_score(runs: list[EnvironmentScore]) -> EnvironmentScore | None:
    if not runs:
        return None
    best_run = runs[0]
    for run in runs[1:]:
        if run.score > best_run.score:
            best_run = run
    return best_run


def _levels_summary(selected_run: EnvironmentScore | None) -> list[dict[str, Any]]:
    if selected_run is None:
        return []

    scores = list(selected_run.level_scores or [])
    actions = list(selected_run.level_actions or [])
    baselines = list(selected_run.level_baseline_actions or [])
    level_count = max(len(scores), len(actions), len(baselines))
    levels: list[dict[str, Any]] = []

    for index in range(level_count):
        score = float(scores[index]) if index < len(scores) else 0.0
        actions_taken = int(actions[index]) if index < len(actions) else 0
        baseline_actions = (
            int(baselines[index])
            if index < len(baselines) and baselines[index] is not None
            else None
        )
        levels.append(
            {
                "level": index + 1,
                "completed": index < int(selected_run.levels_completed or 0),
                "score": score,
                "actions": actions_taken,
                "baselineActions": baseline_actions,
            }
        )

    return levels


def _game_summary(score_list: EnvironmentScoreList) -> dict[str, Any]:
    selected_run = _first_run_with_max_score(list(score_list.runs))
    return {
        "gameId": score_list.id,
        "score": float(score_list.score),
        "levelsCompleted": int(score_list.levels_completed),
        "levelCount": int(score_list.level_count),
        "actions": int(score_list.actions),
        "resets": int(score_list.resets),
        "completed": bool(score_list.completed),
        "attempts": len(score_list.runs),
        "selectedAttemptGuid": selected_run.guid if selected_run else None,
        "selectedAttemptState": selected_run.state.value if selected_run and selected_run.state else None,
        "selectedAttemptMessage": selected_run.message if selected_run else None,
        "levels": _levels_summary(selected_run),
    }


def _scorecard_summary(scorecard: EnvironmentScorecard) -> dict[str, Any]:
    games = [_game_summary(environment) for environment in scorecard.environments]
    return {
        "score": float(scorecard.score),
        "totalGames": int(scorecard.total_environments),
        "totalGamesCompleted": int(scorecard.total_environments_completed),
        "totalLevelsCompleted": int(scorecard.total_levels_completed),
        "totalLevels": int(scorecard.total_levels),
        "totalActions": int(scorecard.total_actions),
        "games": games,
    }


def _compare_levels(
    local_levels: list[dict[str, Any]],
    scorecard_levels: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    max_len = max(len(local_levels), len(scorecard_levels))
    comparisons: list[dict[str, Any]] = []
    for index in range(max_len):
        local_level = local_levels[index] if index < len(local_levels) else None
        scorecard_level = scorecard_levels[index] if index < len(scorecard_levels) else None
        score_match = (
            local_level is not None
            and scorecard_level is not None
            and math.isclose(
                float(local_level["score"]),
                float(scorecard_level["score"]),
                rel_tol=1e-9,
                abs_tol=1e-9,
            )
        )
        comparisons.append(
            {
                "level": index + 1,
                "matches": (
                    local_level is not None
                    and scorecard_level is not None
                    and local_level["completed"] == scorecard_level["completed"]
                    and local_level["actions"] == scorecard_level["actions"]
                    and local_level["baselineActions"] == scorecard_level["baselineActions"]
                    and score_match
                ),
            }
        )
    return comparisons


def _compare_summaries(
    local_summary: dict[str, Any],
    scorecard_summary: dict[str, Any] | None,
    scorecard_meta: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if scorecard_summary is not None:
        scorecard_games = {
            game["gameId"]: game for game in scorecard_summary.get("games", [])
        }
        game_comparisons: list[dict[str, Any]] = []
        for local_game in local_summary.get("games", []):
            scorecard_game = scorecard_games.get(local_game["gameId"])
            if scorecard_game is None:
                game_comparisons.append(
                    {
                        "gameId": local_game["gameId"],
                        "matches": False,
                        "reason": "missing in scorecard",
                        "levels": [],
                    }
                )
                continue
            score_match = math.isclose(
                float(local_game["score"]),
                float(scorecard_game["score"]),
                rel_tol=1e-9,
                abs_tol=1e-9,
            )
            level_comparisons = _compare_levels(
                list(local_game.get("levels", [])),
                list(scorecard_game.get("levels", [])),
            )
            game_comparisons.append(
                {
                    "gameId": local_game["gameId"],
                    "matches": (
                        score_match
                        and local_game["levelsCompleted"] == scorecard_game["levelsCompleted"]
                        and local_game["actions"] == scorecard_game["actions"]
                        and all(level["matches"] for level in level_comparisons)
                    ),
                    "levels": level_comparisons,
                }
            )

        total_match = math.isclose(
            float(local_summary["score"]),
            float(scorecard_summary["score"]),
            rel_tol=1e-9,
            abs_tol=1e-9,
        )
        return {
            "mode": "live",
            "matches": total_match and all(game["matches"] for game in game_comparisons),
            "totalMatches": total_match,
            "games": game_comparisons,
        }

    final_score = None
    if scorecard_meta is not None and scorecard_meta.get("final_score") is not None:
        final_score = float(scorecard_meta["final_score"])
    if final_score is None:
        return None

    total_match = math.isclose(
        float(local_summary["score"]),
        final_score,
        rel_tol=1e-9,
        abs_tol=1e-9,
    )
    return {
        "mode": "recorded-final-score",
        "matches": total_match,
        "totalMatches": total_match,
        "games": [],
    }


def _load_live_scorecard(
    scorecard_meta: dict[str, Any],
) -> tuple[EnvironmentScorecard | None, str | None]:
    scorecard_id = str(scorecard_meta.get("scorecard_id", "") or "").strip()
    arc_base_url = str(scorecard_meta.get("arc_base_url", "") or DEFAULT_ARC_BASE_URL).strip() or DEFAULT_ARC_BASE_URL
    arc_api_key = str(os.environ.get("ARC_API_KEY", "") or "").strip()

    if not scorecard_id:
        return None, "missing scorecard_id"
    if not arc_api_key:
        return None, "ARC_API_KEY is not set"

    try:
        arcade = _with_suppressed_stdout(
            Arcade,
            arc_api_key=arc_api_key,
            arc_base_url=arc_base_url,
            operation_mode=OperationMode.ONLINE,
            logger=_arcade_logger(),
        )
        scorecard = _with_suppressed_stdout(arcade.get_scorecard, scorecard_id)
        if scorecard is None:
            return None, "scorecard not found"
        return scorecard, None
    except Exception as exc:
        return None, str(exc)


def compute_run_score_payload(project_root: Path, run_id: str) -> dict[str, Any]:
    arc_dir = _run_dir(project_root, run_id) / "supervisor" / "arc"
    state_payload = _read_json(arc_dir / "state.json")
    history_payload = _read_json(arc_dir / "tool-engine-history.json")
    if state_payload is None or history_payload is None:
        raise RuntimeError("missing state.json or tool-engine-history.json")

    scorecard_meta = _read_json(_ctx_dir(project_root, run_id) / "scorecard.json")
    arc_base_url = str(scorecard_meta.get("arc_base_url", "") if scorecard_meta else "").strip() or DEFAULT_ARC_BASE_URL
    environment_infos = _load_environment_infos(arc_base_url)
    local_scorecard = _build_local_scorecard(run_id, history_payload, state_payload, environment_infos)
    local_summary = _scorecard_summary(local_scorecard)

    live_scorecard = None
    live_fetch_error = None
    if scorecard_meta is not None:
        live_scorecard, live_fetch_error = _load_live_scorecard(scorecard_meta)
    live_summary = _scorecard_summary(live_scorecard) if live_scorecard is not None else None

    return {
        "runId": run_id,
        "local": local_summary,
        "scorecard": (
            {
                "cardId": scorecard_meta.get("scorecard_id") if scorecard_meta else None,
                "apiUrl": scorecard_meta.get("api_url") if scorecard_meta else None,
                "webUrl": scorecard_meta.get("web_url") if scorecard_meta else None,
                "closed": bool(scorecard_meta.get("closed")) if scorecard_meta else False,
                "finalScore": scorecard_meta.get("final_score") if scorecard_meta else None,
                "createdHere": scorecard_meta.get("created_here") if scorecard_meta else None,
                "live": live_summary,
                "liveFetchError": live_fetch_error,
            }
            if scorecard_meta is not None
            else None
        ),
        "comparison": _compare_summaries(local_summary, live_summary, scorecard_meta),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute local and scorecard-backed scores for a harness run")
    parser.add_argument("--run-id", required=True, help="Run directory/session ID")
    args = parser.parse_args()
    try:
        payload = compute_run_score_payload(_project_root(), args.run_id)
        print(json.dumps(payload, indent=2))
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
