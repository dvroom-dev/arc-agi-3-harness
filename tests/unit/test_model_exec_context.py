from __future__ import annotations

import json
from pathlib import Path

from tests.unit.test_model_template import _copy_model_templates, _run_model, _write_hex


def test_model_exec_file_matches_arc_repl_script_context_for_play_files(tmp_path: Path) -> None:
    game_dir = tmp_path / "game_ls20"
    _copy_model_templates(game_dir)
    _write_hex(game_dir / "level_1" / "initial_state.hex", ["0000", "0000", "0000", "0000"])

    (game_dir / "play_lib.py").write_text(
        """
from pathlib import Path

PLAY_LIB_DIR = Path(__file__).resolve().parent

def plan_level_actions(state: dict, *, level: int | None = None) -> list[int]:
    _ = state, level
    return [1]
""".strip()
        + "\n"
    )

    proc = _run_model(game_dir, ["exec_file", "--game-id", "ls20", "./play.py"])
    assert proc.returncode == 0, proc.stderr

    lines = [json.loads(line) for line in proc.stdout.splitlines()[:3]]
    assert lines[0]["mode"] == "model-dry-run"
    assert lines[1]["planned_actions"] == 1
    assert lines[2]["step"] == 1
    assert lines[2]["state"] == "NOT_FINISHED"
    assert lines[2]["current_level"] == 1
