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


def test_model_exec_file_reports_level_completion_signal(tmp_path: Path) -> None:
    game_dir = tmp_path / "game_ls20"
    _copy_model_templates(game_dir)
    _write_hex(game_dir / "level_1" / "initial_state.hex", ["0000", "0000", "0000", "0000"])
    _write_hex(game_dir / "level_2" / "initial_state.hex", ["1111", "1111", "1111", "1111"])

    (game_dir / "play_lib.py").write_text(
        """
def plan_level_actions(state: dict, *, level: int | None = None) -> list[int]:
    _ = state, level
    return [1]
""".strip()
        + "\n"
    )
    (game_dir / "model_lib.py").write_text(
        (game_dir / "model_lib.py").read_text()
        + "\n\ndef is_level_complete(env):\n    return int(env.turn) >= 1\n"
    )

    proc = _run_model(game_dir, ["exec_file", "--game-id", "ls20", "./play.py"])
    assert proc.returncode == 0, proc.stderr

    payload = json.loads("\n".join(proc.stdout.splitlines()[3:]))
    assert payload["ok"] is True
    assert payload["action"] == "exec_file"
    assert payload["current_level"] == 2
    assert payload["levels_completed"] == 1
    assert payload["level_complete"] is True


def test_model_exec_file_reset_level_first_resets_before_running(tmp_path: Path) -> None:
    game_dir = tmp_path / "game_ls20"
    _copy_model_templates(game_dir)
    _write_hex(game_dir / "level_1" / "initial_state.hex", ["0000", "0000", "0000", "0000"])
    _write_hex(game_dir / "level_2" / "initial_state.hex", ["1111", "1111", "1111", "1111"])

    (game_dir / "play_lib.py").write_text(
        """
def plan_level_actions(state: dict, *, level: int | None = None) -> list[int]:
    _ = state, level
    return []
""".strip()
        + "\n"
    )

    proc = _run_model(game_dir, ["set_level", "--game-id", "ls20", "2"])
    assert proc.returncode == 0, proc.stderr

    proc = _run_model(game_dir, ["exec_file", "--reset-level-first", "--game-id", "ls20", "./play.py"])
    assert proc.returncode == 0, proc.stderr
    payload = json.loads("\n".join(proc.stdout.splitlines()[2:]))
    assert payload["action"] == "exec_file"
    assert payload["reset_level_first"] is True
    assert payload["reset_before_exec"]["performed"] is True
    assert payload["current_level"] == 2
