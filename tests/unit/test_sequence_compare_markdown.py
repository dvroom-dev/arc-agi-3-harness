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
    repo_root = Path(__file__).resolve().parents[2]
    src_dir = repo_root / "templates" / "agent_workspace"
    runtime_src = repo_root / "arc_model_runtime"
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


def _run_model(game_dir: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["ARC_CONFIG_DIR"] = str((game_dir.parent / "config").resolve())
    return subprocess.run(
        [sys.executable, str(game_dir / "model.py"), *args],
        cwd=game_dir,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def test_model_compare_report_markdown_summarizes_large_diffs(tmp_path: Path) -> None:
    game_dir = tmp_path / "game_ls20"
    _copy_model_templates(game_dir)

    before_rows = ["0000", "0000", "0000", "0000"]
    after_rows = ["F000", "0F00", "00F0", "000F"]
    _write_hex(game_dir / "level_1" / "initial_state.hex", before_rows)
    step_dir = game_dir / "level_1" / "sequences" / "seq_0001" / "actions" / "step_0001_action_000001_action1"
    _write_hex(step_dir / "before_state.hex", before_rows)
    _write_hex(step_dir / "after_state.hex", after_rows)
    (step_dir / "meta.json").write_text(json.dumps({"schema_version": "arc_repl.sequence_action.v1"}, indent=2))

    seq_payload = {
        "schema_version": "arc_repl.level_sequence.v1",
        "game_id": "ls20",
        "level": 1,
        "sequence_id": "seq_0001",
        "sequence_number": 1,
        "start_action_index": 1,
        "end_action_index": 1,
        "start_recorded_at_utc": "",
        "end_recorded_at_utc": "",
        "end_reason": "open",
        "action_count": 1,
        "actions": [
            {
                "local_step": 1,
                "action_index": 1,
                "tool_turn": 1,
                "step_in_call": 1,
                "call_action": "exec",
                "action_name": "ACTION1",
                "action_data": {},
                "state_before": "NOT_FINISHED",
                "state_after": "NOT_FINISHED",
                "level_before": 1,
                "level_after": 1,
                "levels_completed_before": 0,
                "levels_completed_after": 0,
                "recorded_at_utc": "",
                "files": {
                    "before_state_hex": "sequences/seq_0001/actions/step_0001_action_000001_action1/before_state.hex",
                    "after_state_hex": "sequences/seq_0001/actions/step_0001_action_000001_action1/after_state.hex",
                    "meta_json": "sequences/seq_0001/actions/step_0001_action_000001_action1/meta.json",
                },
            }
        ],
    }
    seq_file = game_dir / "level_1" / "sequences" / "seq_0001.json"
    seq_file.parent.mkdir(parents=True, exist_ok=True)
    seq_file.write_text(json.dumps(seq_payload, indent=2))

    proc = _run_model(game_dir, ["compare_sequences", "--game-id", "ls20", "--level", "1"])
    assert proc.returncode == 0, proc.stderr
    report_text = (game_dir / "level_1" / "sequence_compare" / "seq_0001.md").read_text()
    current_compare_text = (game_dir / "current_compare.md").read_text()
    assert "sample_changes:" in report_text
    assert "remaining_changes_not_shown" not in report_text
    assert '"row":' not in report_text
    assert "## Diff Legend" in report_text
    assert "- start_action_index: 1" in report_text
    assert "- sequence_end_reason: open" in report_text
    assert "report_file: level_current/sequence_compare/seq_0001.md" in current_compare_text
    assert "## Current Runtime State" in current_compare_text
    assert "- sequence_end_reason: open" in current_compare_text
    assert (game_dir / "level_current" / "sequence_compare" / "seq_0001.md").exists()


def test_compare_markdown_explains_level_boundary_exclusion(tmp_path: Path) -> None:
    game_dir = tmp_path / "game_ls20"
    _copy_model_templates(game_dir)
    _write_hex(game_dir / "level_1" / "initial_state.hex", ["00", "00"])
    _write_hex(game_dir / "level_2" / "initial_state.hex", ["33", "33"])
    (game_dir / "model_lib.py").write_text(
        (game_dir / "model_lib.py").read_text()
        + "\n\ndef init_level(env, level: int, *, cfg=None):\n"
        + "    import numpy as np\n"
        + "    env.current_level = int(level)\n"
        + "    env.grid = np.array([[0, 0], [0, 0]], dtype=np.int8)\n"
        + "    env._step_n = 0\n"
        + "\n\ndef apply_level_1(env, action, *, data=None, reasoning=None):\n"
        + "    _ = action, data, reasoning\n"
        + "    env._step_n += 1\n"
        + "    if env._step_n == 1:\n"
        + "        env.grid[0, 0] = 1\n"
        + "    else:\n"
        + "        env.grid[:, :] = 15\n"
        + "\n\ndef is_level_complete(env):\n"
        + "    return int(getattr(env, '_step_n', 0)) >= 2\n"
    )

    step1_dir = game_dir / "level_1" / "sequences" / "seq_0001" / "actions" / "step_0001_action_000001_action1"
    _write_hex(step1_dir / "before_state.hex", ["00", "00"])
    _write_hex(step1_dir / "after_state.hex", ["10", "00"])
    (step1_dir / "meta.json").write_text(json.dumps({"schema_version": "arc_repl.sequence_action.v1"}, indent=2))

    step2_dir = game_dir / "level_1" / "sequences" / "seq_0001" / "actions" / "step_0002_action_000002_action1"
    _write_hex(step2_dir / "before_state.hex", ["10", "00"])
    _write_hex(step2_dir / "after_state.hex", ["22", "22"])
    (step2_dir / "meta.json").write_text(json.dumps({"schema_version": "arc_repl.sequence_action.v1"}, indent=2))

    seq_payload = {
        "schema_version": "arc_repl.level_sequence.v1",
        "game_id": "ls20",
        "level": 1,
        "sequence_id": "seq_0001",
        "sequence_number": 1,
        "start_action_index": 1,
        "end_action_index": 2,
        "start_recorded_at_utc": "",
        "end_recorded_at_utc": "",
        "end_reason": "level_change",
        "action_count": 2,
        "actions": [
            {
                "local_step": 1,
                "action_index": 1,
                "tool_turn": 1,
                "step_in_call": 1,
                "call_action": "exec",
                "action_name": "ACTION1",
                "action_data": {},
                "state_before": "NOT_FINISHED",
                "state_after": "NOT_FINISHED",
                "level_before": 1,
                "level_after": 1,
                "levels_completed_before": 0,
                "levels_completed_after": 0,
                "level_complete_before": False,
                "level_complete_after": False,
                "recorded_at_utc": "",
                "files": {
                    "before_state_hex": "sequences/seq_0001/actions/step_0001_action_000001_action1/before_state.hex",
                    "after_state_hex": "sequences/seq_0001/actions/step_0001_action_000001_action1/after_state.hex",
                    "meta_json": "sequences/seq_0001/actions/step_0001_action_000001_action1/meta.json",
                },
            },
            {
                "local_step": 2,
                "action_index": 2,
                "tool_turn": 2,
                "step_in_call": 1,
                "call_action": "exec",
                "action_name": "ACTION1",
                "action_data": {},
                "state_before": "NOT_FINISHED",
                "state_after": "NOT_FINISHED",
                "level_before": 1,
                "level_after": 2,
                "levels_completed_before": 0,
                "levels_completed_after": 1,
                "level_complete_before": False,
                "level_complete_after": True,
                "recorded_at_utc": "",
                "files": {
                    "before_state_hex": "sequences/seq_0001/actions/step_0002_action_000002_action1/before_state.hex",
                    "after_state_hex": "sequences/seq_0001/actions/step_0002_action_000002_action1/after_state.hex",
                    "meta_json": "sequences/seq_0001/actions/step_0002_action_000002_action1/meta.json",
                },
            },
        ],
    }
    seq_root = game_dir / "level_1" / "sequences"
    seq_root.mkdir(parents=True, exist_ok=True)
    (seq_root / "seq_0001.json").write_text(json.dumps(seq_payload, indent=2))

    proc = _run_model(game_dir, ["compare_sequences", "--game-id", "ls20", "--level", "1"])
    assert proc.returncode == 0, proc.stderr

    report_text = (game_dir / "level_1" / "sequence_compare" / "seq_0001.md").read_text()
    current_compare_text = (game_dir / "current_compare.md").read_text()
    assert "- comparison_stop_reason: post_level_complete_state_diff_excluded" in report_text
    assert "Compare checked the boundary action's completion transition" in report_text
    assert "boundary_note: level-completing action transition was compared" in current_compare_text
