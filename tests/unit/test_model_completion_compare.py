from __future__ import annotations

import json
from pathlib import Path

from tests.unit.test_model_runtime_sync import _copy_model_templates, _run_model_with_env, _write_hex


def test_compare_sequences_compares_level_complete_boundary_transition(tmp_path: Path) -> None:
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

    proc = _run_model_with_env(game_dir, ["compare_sequences", "--game-id", "ls20"], extra_env={})
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["all_match"] is True
    report = payload["reports"][0]
    assert report["matched"] is True
    assert report["actions_total"] == 2
    assert report["actions_compared"] == 2
    assert report["comparison_stop_reason"] == "post_level_complete_state_diff_excluded"
    assert report["divergence_step"] is None


def test_compare_sequences_catches_level_complete_transition_mismatch(tmp_path: Path) -> None:
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
        + "    return False\n"
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

    proc = _run_model_with_env(game_dir, ["compare_sequences", "--game-id", "ls20"], extra_env={})
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    report = payload["reports"][0]
    assert report["matched"] is False
    assert report["divergence_step"] == 2
    assert report["divergence_reason"] == "state_transition_mismatch"
    assert report["transition_mismatch"]["game"]["level_complete_after"] is True
    assert report["transition_mismatch"]["model"]["level_complete_after"] is False
