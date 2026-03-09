from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def _write_hex(path: Path, rows: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(rows) + "\n")


def _copy_model_templates(game_dir: Path) -> None:
    src_dir = Path(__file__).resolve().parents[2] / "templates" / "agent_workspace"
    runtime_src = Path(__file__).resolve().parents[2] / "arc_model_runtime"
    game_dir.mkdir(parents=True, exist_ok=True)
    for name in (
        "model.py",
        "model_lib.py",
        "play_lib.py",
        "play.py",
        "artifact_helpers.py",
        "inspect_sequence.py",
        "inspect_components.py",
    ):
        shutil.copy2(src_dir / name, game_dir / name)
    runtime_dst = game_dir.parent / "config" / "tools" / "arc_model_runtime"
    runtime_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(runtime_src, runtime_dst)


def _run_model_with_env(game_dir: Path, args: list[str], *, extra_env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["ARC_CONFIG_DIR"] = str((game_dir.parent / "config").resolve())
    env.update(extra_env)
    return subprocess.run(
        [sys.executable, str(game_dir / "model.py"), *args],
        cwd=game_dir,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def test_model_status_errors_when_initial_grid_is_missing(tmp_path: Path) -> None:
    game_dir = tmp_path / "game_ls20"
    _copy_model_templates(game_dir)

    proc = _run_model_with_env(game_dir, ["status", "--game-id", "ls20"], extra_env={})
    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    assert payload["ok"] is False
    assert payload["error"]["type"] == "model_init_error"
    assert "missing initial_state.hex for level 1" in payload["error"]["message"]


def test_model_status_implicitly_syncs_to_arc_frontier_level(tmp_path: Path) -> None:
    game_dir = tmp_path / "game_ls20"
    _copy_model_templates(game_dir)
    _write_hex(game_dir / "level_1" / "initial_state.hex", ["0123", "4567"])
    _write_hex(game_dir / "level_2" / "initial_state.hex", ["89AB", "CDEF"])
    arc_state_dir = tmp_path / "arc"
    arc_state_dir.mkdir(parents=True, exist_ok=True)
    (arc_state_dir / "state.json").write_text(
        json.dumps({"current_level": 2, "levels_completed": 1}, indent=2)
    )

    proc = _run_model_with_env(
        game_dir,
        ["status", "--game-id", "ls20"],
        extra_env={"ARC_STATE_DIR": str(arc_state_dir)},
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["current_level"] == 2
    assert payload["levels_completed"] == 1
    assert payload["available_model_levels"] == [1, 2]


def test_model_status_errors_when_frontier_level_has_no_initial_grid(tmp_path: Path) -> None:
    game_dir = tmp_path / "game_ls20"
    _copy_model_templates(game_dir)
    _write_hex(game_dir / "level_1" / "initial_state.hex", ["0123", "4567"])
    arc_state_dir = tmp_path / "arc"
    arc_state_dir.mkdir(parents=True, exist_ok=True)
    (arc_state_dir / "state.json").write_text(
        json.dumps({"current_level": 2, "levels_completed": 1}, indent=2)
    )

    proc = _run_model_with_env(
        game_dir,
        ["status", "--game-id", "ls20"],
        extra_env={"ARC_STATE_DIR": str(arc_state_dir)},
    )
    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    assert payload["ok"] is False
    assert payload["error"]["type"] == "missing_initial_state"
    assert "frontier level 2 is active in ARC state" in payload["error"]["message"]
