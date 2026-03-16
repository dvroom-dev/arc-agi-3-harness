from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from tests.unit.test_model_template import _copy_model_templates, _run_model, _write_hex


def _run_model_exec(game_dir: Path, script: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["ARC_CONFIG_DIR"] = str((game_dir.parent / "config").resolve())
    return subprocess.run(
        [sys.executable, str(game_dir / "model.py"), "exec", "--game-id", "ls20"],
        cwd=game_dir,
        input=script,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def test_model_template_applies_level_hooks_cumulatively(tmp_path: Path) -> None:
    game_dir = tmp_path / "game_ls20"
    _copy_model_templates(game_dir)
    for level in range(1, 6):
        _write_hex(game_dir / f"level_{level}" / "initial_state.hex", ["000", "000", "000"])

    (game_dir / "model_lib.py").write_text(
        (game_dir / "model_lib.py").read_text()
        + "\nLEVEL_REGISTRY = {\n"
        + "    1: LevelConfig(level_num=1, turn_budget=7),\n"
        + "    3: LevelConfig(level_num=3, turn_budget=21),\n"
        + "}\n"
        + "\n\ndef init_level_1(env, *, cfg=None):\n"
        + "    env.seen = ['L1']\n"
        + "\n\ndef init_level_3(env, *, cfg=None):\n"
        + "    env.seen.append('L3')\n"
        + "\n\ndef init_level_5(env, *, cfg=None):\n"
        + "    env.seen.append('L5')\n"
        + "\n\ndef apply_level_1(env, action, *, data=None, reasoning=None):\n"
        + "    _ = action, data, reasoning\n"
        + "    env.grid[0, 0] = 1\n"
        + "\n\ndef apply_level_3(env, action, *, data=None, reasoning=None):\n"
        + "    _ = action, data, reasoning\n"
        + "    env.grid[0, 1] = 3\n"
        + "\n\ndef apply_level_5(env, action, *, data=None, reasoning=None):\n"
        + "    _ = action, data, reasoning\n"
        + "    env.grid[0, 2] = 5\n"
    )

    proc = _run_model(game_dir, ["set_level", "--game-id", "ls20", "5"])
    assert proc.returncode == 0, proc.stderr

    proc = _run_model_exec(
        game_dir,
        "env.step(1)\nprint(json.dumps({'grid': env.grid.tolist(), 'seen': env.seen, 'turn_budget': env.turn_budget}))\n",
    )
    assert proc.returncode == 0, proc.stderr
    first_line = json.loads(proc.stdout.splitlines()[0])
    assert first_line["grid"][0] == [1, 3, 5]
    assert first_line["seen"] == ["L1", "L3", "L5"]
    assert first_line["turn_budget"] == 20


def test_model_template_inherits_completion_from_latest_prior_level_hook(tmp_path: Path) -> None:
    game_dir = tmp_path / "game_ls20"
    _copy_model_templates(game_dir)
    for level in range(1, 7):
        _write_hex(game_dir / f"level_{level}" / "initial_state.hex", ["000", "000"])

    (game_dir / "model_lib.py").write_text(
        (game_dir / "model_lib.py").read_text()
        + "\n\ndef apply_level_1(env, action, *, data=None, reasoning=None):\n"
        + "    _ = action, data, reasoning\n"
        + "    env.grid[0, 0] = 1\n"
        + "\n\ndef is_level_complete_level_3(env):\n"
        + "    return int(env.turn) >= 1\n"
    )

    proc = _run_model(game_dir, ["set_level", "--game-id", "ls20", "5"])
    assert proc.returncode == 0, proc.stderr

    proc = _run_model_exec(game_dir, "env.step(1)\n")
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["level_complete"] is True
    assert payload["last_step_level_complete"] is True
    assert payload["last_completed_level"] == 5
    assert payload["current_level"] == 6
