from __future__ import annotations

import importlib.util
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
        "components.py",
        "model_lib.py",
        "play_lib.py",
        "play.py",
        "artifact_helpers.py",
        "inspect_sequence.py",
        "inspect_components.py",
        "inspect_grid_slice.py",
        "inspect_grid_values.py",
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


def _load_game_module(module_name: str, module_path: Path):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_artifact_helper_resolves_level_current_sequence_paths(tmp_path: Path) -> None:
    game_dir = tmp_path / "game_ls20"
    _copy_model_templates(game_dir)
    action_dir = game_dir / "level_current" / "sequences" / "seq_0001" / "actions" / "step_0001_action_000014_action1"
    _write_hex(action_dir / "frames" / "frame_0001.hex", ["22", "22"])

    artifact_helpers = _load_game_module("artifact_helpers_level_current_test", game_dir / "artifact_helpers.py")
    resolved = artifact_helpers.resolve_sequence_action_path(
        action_dir,
        "sequences/seq_0001/actions/step_0001_action_000014_action1/frames/frame_0001.hex",
    )

    assert resolved == action_dir / "frames" / "frame_0001.hex"


def test_compare_sequences_replay_helper_handles_level_current_global_action_paths(tmp_path: Path) -> None:
    game_dir = tmp_path / "game_ls20"
    _copy_model_templates(game_dir)
    _write_hex(game_dir / "level_1" / "initial_state.hex", ["00", "00"])
    _write_hex(game_dir / "level_2" / "initial_state.hex", ["11", "11"])
    (game_dir / "level_current").mkdir(parents=True, exist_ok=True)
    _write_hex(game_dir / "level_current" / "initial_state.hex", ["11", "11"])
    (game_dir / "level_current" / "meta.json").write_text(
        json.dumps({"schema_version": "arc_repl.level_current.v1", "level": 2}, indent=2) + "\n",
        encoding="utf-8",
    )

    before_rows = ["11", "11"]
    after_rows = ["22", "22"]
    for root in (game_dir / "level_current", game_dir / "level_2"):
        step_dir = root / "sequences" / "seq_0001" / "actions" / "step_0001_action_000014_action1"
        _write_hex(step_dir / "before_state.hex", before_rows)
        _write_hex(step_dir / "after_state.hex", after_rows)
        _write_hex(step_dir / "frames" / "frame_0001.hex", after_rows)
        (step_dir / "meta.json").write_text(
            json.dumps(
                {
                    "schema_version": "arc_repl.sequence_action.v1",
                    "files": {
                        "frame_sequence_hex": [
                            "sequences/seq_0001/actions/step_0001_action_000014_action1/frames/frame_0001.hex"
                        ]
                    },
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    seq_payload = {
        "schema_version": "arc_repl.level_sequence.v1",
        "game_id": "ls20",
        "level": 2,
        "sequence_id": "seq_0001",
        "sequence_number": 1,
        "start_action_index": 14,
        "end_action_index": 14,
        "start_recorded_at_utc": "",
        "end_recorded_at_utc": "",
        "end_reason": "open",
        "action_count": 1,
        "actions": [
            {
                "local_step": 1,
                "action_index": 14,
                "tool_turn": 14,
                "step_in_call": 1,
                "call_action": "exec",
                "action_name": "ACTION1",
                "action_data": {},
                "state_before": "NOT_FINISHED",
                "state_after": "NOT_FINISHED",
                "level_before": 2,
                "level_after": 2,
                "levels_completed_before": 1,
                "levels_completed_after": 1,
                "recorded_at_utc": "",
                "files": {
                    "before_state_hex": "sequences/seq_0001/actions/step_0001_action_000014_action1/before_state.hex",
                    "after_state_hex": "sequences/seq_0001/actions/step_0001_action_000014_action1/after_state.hex",
                    "meta_json": "sequences/seq_0001/actions/step_0001_action_000014_action1/meta.json",
                    "frame_sequence_hex": [
                        "sequences/seq_0001/actions/step_0001_action_000014_action1/frames/frame_0001.hex"
                    ],
                },
            }
        ],
    }
    seq_root = game_dir / "level_2" / "sequences"
    seq_root.mkdir(parents=True, exist_ok=True)
    (seq_root / "seq_0001.json").write_text(json.dumps(seq_payload, indent=2) + "\n", encoding="utf-8")

    (game_dir / "model_lib.py").write_text(
        """from __future__ import annotations

import json
from pathlib import Path

import numpy as np

import artifact_helpers


def get_level_config(level: int):
    return None


def action_name(action) -> str:
    if hasattr(action, 'name'):
        return str(action.name).upper()
    return str(action).upper()


def _load_hex_grid(path: Path) -> np.ndarray | None:
    rows = [line.strip() for line in path.read_text().splitlines() if line.strip()]
    if not rows:
        return None
    return np.array([[int(ch, 16) for ch in row] for row in rows], dtype=np.int8)


def _sequence_action_dir(level: int, action_index: int, action: str, *, before_grid: np.ndarray | None = None) -> Path | None:
    game_dir = Path(__file__).resolve().parent
    exact_pattern = f"step_*_action_{int(action_index):06d}_{str(action).strip().lower()}"
    fallback_pattern = f"step_*_action_*_{str(action).strip().lower()}"
    for search_root in [game_dir / f"level_{int(level)}" / "sequences", game_dir / "level_current" / "sequences"]:
        if not search_root.exists():
            continue
        for seq_dir in sorted(search_root.glob("seq_*")):
            actions_dir = seq_dir / "actions"
            matches = sorted(actions_dir.glob(exact_pattern))
            for candidate in matches:
                candidate_before = _load_hex_grid(candidate / "before_state.hex")
                if before_grid is None or (candidate_before is not None and np.array_equal(candidate_before, before_grid)):
                    return candidate
            fallback_matches = sorted(actions_dir.glob(fallback_pattern))
            for candidate in fallback_matches:
                candidate_before = _load_hex_grid(candidate / "before_state.hex")
                if before_grid is not None and candidate_before is not None and np.array_equal(candidate_before, before_grid):
                    return candidate
    return None


def _apply_recorded_transition(env, *, level: int, action_index: int, action: str) -> bool:
    before_grid = np.array(env.grid, dtype=np.int8, copy=True)
    action_dir = _sequence_action_dir(level, action_index, action, before_grid=before_grid)
    if action_dir is None:
        return False
    after_grid = _load_hex_grid(action_dir / "after_state.hex")
    if after_grid is None:
        return False
    env.grid = np.array(after_grid, dtype=np.int8, copy=True)
    meta = json.loads((action_dir / "meta.json").read_text())
    frame_paths = [artifact_helpers.resolve_sequence_action_path(action_dir, rel) for rel in meta["files"]["frame_sequence_hex"]]
    env.last_step_frames = [_load_hex_grid(frame_path) for frame_path in frame_paths]
    return True


def apply_level_1(env, action, *, data=None, reasoning=None):
    _ = data, reasoning
    _apply_recorded_transition(env, level=1, action_index=int(getattr(env, 'turn', 0)), action=action_name(action).lower())


def is_level_complete(env) -> bool:
    return False


def is_game_over(env) -> bool:
    return False
""",
        encoding="utf-8",
    )

    arc_state_dir = tmp_path / "arc"
    arc_state_dir.mkdir(parents=True, exist_ok=True)
    (arc_state_dir / "state.json").write_text(json.dumps({"current_level": 2, "levels_completed": 1}, indent=2) + "\n")

    proc = _run_model_with_env(
        game_dir,
        ["compare_sequences", "--game-id", "ls20", "--level", "2"],
        extra_env={"ARC_STATE_DIR": str(arc_state_dir)},
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["level"] == 2
    assert payload["all_match"] is True
