from __future__ import annotations

import json
import os
from pathlib import Path


def _write_hex(path: Path, rows: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(rows) + "\n")


def test_sync_workspace_level_view_rewrites_model_status_to_visible_level(tmp_path: Path) -> None:
    from arc_model_runtime.utils import sync_workspace_level_view

    game_dir = tmp_path / "game_ls20"
    game_dir.mkdir(parents=True, exist_ok=True)
    (game_dir / ".analysis_level_pin.json").write_text(
        json.dumps({"level": 1, "phase": "pending_theory"}, indent=2)
    )
    (game_dir / "model_status.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "runtime": "model",
                "last_action_name": "compare_sequences",
                "state": {
                    "state": "NOT_FINISHED",
                    "current_level": 2,
                    "levels_completed": 1,
                    "available_model_levels": [1, 2],
                    "full_reset": False,
                },
                "compare": {"level": 1, "all_match": False},
            },
            indent=2,
        )
        + "\n"
    )

    arc_state_dir = tmp_path / "arc"
    artifacts_root = arc_state_dir / "game_artifacts" / "game_ls20"
    _write_hex(artifacts_root / "level_1" / "initial_state.hex", ["0000", "0000"])
    _write_hex(artifacts_root / "level_2" / "initial_state.hex", ["1111", "1111"])

    old = os.environ.get("ARC_STATE_DIR")
    os.environ["ARC_STATE_DIR"] = str(arc_state_dir)
    try:
        visible = sync_workspace_level_view(game_dir, game_id="ls20", frontier_level=2)
    finally:
        if old is None:
            os.environ.pop("ARC_STATE_DIR", None)
        else:
            os.environ["ARC_STATE_DIR"] = old

    assert visible == 1
    rewritten = json.loads((game_dir / "model_status.json").read_text())
    assert rewritten["state"]["current_level"] == 1
    assert rewritten["state"]["levels_completed"] == 0
    assert rewritten["state"]["available_model_levels"] == [1]
    assert rewritten["compare"]["level"] == 1
