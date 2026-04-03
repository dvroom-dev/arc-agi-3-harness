from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from arc_agi.models import EnvironmentInfo

import ui_run_scores


def _environment_info(game_id: str, baseline_actions: list[int]) -> EnvironmentInfo:
    return EnvironmentInfo.model_validate(
        {
            "game_id": game_id,
            "title": game_id,
            "default_fps": 5,
            "tags": [],
            "baseline_actions": baseline_actions,
            "date_downloaded": datetime.now(timezone.utc).isoformat(),
            "class_name": "FakeEnv",
            "local_dir": f"environment_files/{game_id}",
        }
    )


def _seed_run(root: Path, run_id: str, *, final_score: float | None = None) -> None:
    arc_dir = root / "runs" / run_id / "supervisor" / "arc"
    arc_dir.mkdir(parents=True, exist_ok=True)
    (arc_dir / "tool-engine-history.json").write_text(
        json.dumps(
            {
                "game_id": "test-game",
                "events": [
                    {"kind": "step", "action": "ACTION1", "levels_completed": 0},
                    {"kind": "step", "action": "ACTION1", "levels_completed": 1},
                    {"kind": "step", "action": "ACTION2", "levels_completed": 1},
                    {"kind": "step", "action": "ACTION2", "levels_completed": 2},
                ],
            }
        )
    )
    (arc_dir / "state.json").write_text(
        json.dumps(
            {
                "game_id": "test-game",
                "state": "NOT_FINISHED",
                "current_level": 3,
                "levels_completed": 2,
                "win_levels": 3,
            }
        )
    )
    ctx_dir = root / ".ctxs" / run_id
    ctx_dir.mkdir(parents=True, exist_ok=True)
    if final_score is not None:
        (ctx_dir / "scorecard.json").write_text(
            json.dumps(
                {
                    "scorecard_id": "sc-1",
                    "api_url": "https://example.test/api/scorecard/sc-1",
                    "web_url": "https://example.test/scorecards/sc-1",
                    "final_score": final_score,
                    "arc_base_url": "https://example.test",
                }
            )
        )


def test_compute_run_score_payload_without_scorecard(monkeypatch, tmp_path: Path) -> None:
    _seed_run(tmp_path, "local-only")
    monkeypatch.setattr(
        ui_run_scores,
        "_load_environment_infos",
        lambda arc_base_url: [_environment_info("test-game", [2, 2, 2])],
    )

    payload = ui_run_scores.compute_run_score_payload(tmp_path, "local-only")

    assert payload["scorecard"] is None
    assert payload["comparison"] is None
    assert payload["local"]["score"] == 66.66666666666667
    assert payload["local"]["totalLevelsCompleted"] == 2
    assert payload["local"]["totalActions"] == 4
    assert payload["local"]["games"][0]["levels"][0]["score"] == 100.0
    assert payload["local"]["games"][0]["levels"][1]["score"] == 100.0
    assert payload["local"]["games"][0]["levels"][2]["score"] == 0.0


def test_compute_run_score_payload_uses_recorded_final_score_fallback(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _seed_run(tmp_path, "recorded-score", final_score=66.66666666666667)
    monkeypatch.setattr(
        ui_run_scores,
        "_load_environment_infos",
        lambda arc_base_url: [_environment_info("test-game", [2, 2, 2])],
    )
    monkeypatch.setattr(
        ui_run_scores,
        "_load_live_scorecard",
        lambda scorecard_meta: (None, "404 not found"),
    )

    payload = ui_run_scores.compute_run_score_payload(tmp_path, "recorded-score")

    assert payload["scorecard"]["finalScore"] == 66.66666666666667
    assert payload["scorecard"]["live"] is None
    assert payload["scorecard"]["liveFetchError"] == "404 not found"
    assert payload["comparison"] == {
        "mode": "recorded-final-score",
        "matches": True,
        "totalMatches": True,
        "games": [],
    }


def test_compute_run_score_payload_prefers_latest_flux_attempt_artifacts(
    monkeypatch,
    tmp_path: Path,
) -> None:
    run_id = "flux-win"
    _seed_run(tmp_path, run_id)
    root_arc_dir = tmp_path / "runs" / run_id / "supervisor" / "arc"
    (root_arc_dir / "tool-engine-history.json").write_text(
        json.dumps({"game_id": "test-game", "events": []}),
        encoding="utf-8",
    )
    (root_arc_dir / "state.json").write_text(
        json.dumps(
            {
                "game_id": "test-game",
                "state": "NOT_FINISHED",
                "current_level": 1,
                "levels_completed": 0,
                "win_levels": 3,
            }
        ),
        encoding="utf-8",
    )

    attempt_arc_dir = tmp_path / "runs" / run_id / "flux_instances" / "attempt_1" / "supervisor" / "arc"
    attempt_arc_dir.mkdir(parents=True, exist_ok=True)
    (attempt_arc_dir / "tool-engine-history.json").write_text(
        json.dumps(
            {
                "game_id": "test-game",
                "events": [
                    {"kind": "step", "action": "ACTION1", "levels_completed": 0},
                    {"kind": "step", "action": "ACTION1", "levels_completed": 1},
                    {"kind": "step", "action": "ACTION2", "levels_completed": 1},
                    {"kind": "step", "action": "ACTION2", "levels_completed": 2},
                    {"kind": "step", "action": "ACTION3", "levels_completed": 3},
                ],
            }
        ),
        encoding="utf-8",
    )
    (attempt_arc_dir / "state.json").write_text(
        json.dumps(
            {
                "game_id": "test-game",
                "state": "WIN",
                "current_level": 4,
                "levels_completed": 3,
                "win_levels": 3,
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        ui_run_scores,
        "_load_environment_infos",
        lambda arc_base_url: [_environment_info("test-game", [2, 2, 2])],
    )

    payload = ui_run_scores.compute_run_score_payload(tmp_path, run_id)

    assert payload["local"]["totalLevelsCompleted"] == 3
    assert payload["local"]["games"][0]["completed"] is True
