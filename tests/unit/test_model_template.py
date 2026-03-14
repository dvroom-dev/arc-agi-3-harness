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
        "components.py",
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


def test_model_set_level_uses_discovered_initial_states(tmp_path: Path) -> None:
    game_dir = tmp_path / "game_ls20"
    _copy_model_templates(game_dir)
    _write_hex(game_dir / "level_1" / "initial_state.hex", ["0123", "4567"])
    _write_hex(game_dir / "level_2" / "initial_state.hex", ["89AB", "CDEF"])

    proc = _run_model(game_dir, ["set_level", "--game-id", "ls20", "2"])
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["current_level"] == 2
    assert payload["available_model_levels"] == [1, 2]
    assert "grid_hex_rows" not in payload
    assert "available_actions" not in payload

    proc_bad = _run_model(game_dir, ["set_level", "--game-id", "ls20", "3"])
    assert proc_bad.returncode == 1
    payload_bad = json.loads(proc_bad.stdout)
    assert payload_bad["ok"] is False
    assert payload_bad["error"]["type"] == "invalid_level"


def test_model_compare_sequences_writes_markdown_report(tmp_path: Path) -> None:
    game_dir = tmp_path / "game_ls20"
    _copy_model_templates(game_dir)

    initial_rows = ["0000", "0000", "0000", "0000"]
    _write_hex(game_dir / "level_1" / "initial_state.hex", initial_rows)
    step_dir = game_dir / "level_1" / "sequences" / "seq_0001" / "actions" / "step_0001_action_000001_action1"
    _write_hex(step_dir / "before_state.hex", initial_rows)
    _write_hex(step_dir / "after_state.hex", initial_rows)
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
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["all_match"] is True
    assert payload["compared_sequences"] == 1

    report = game_dir / "level_1" / "sequence_compare" / "seq_0001.md"
    assert report.exists()
    report_text = report.read_text()
    assert "Sequence Comparison: seq_0001" in report_text

    current_compare = json.loads((game_dir / "current_compare.json").read_text())
    assert current_compare["all_match"] is True
    assert len(current_compare["reports"]) == 1
    assert current_compare["reports"][0]["sequence_id"] == "seq_0001"
    assert current_compare["mismatched_reports"] == []

    model_status = json.loads((game_dir / "model_status.json").read_text())
    assert model_status["runtime"] == "model"
    assert model_status["last_action_name"] == "compare_sequences"
    assert model_status["ok"] is True
    assert model_status["state"]["current_level"] == 1
    assert model_status["compare"]["all_match"] is True
    assert model_status["compare"]["compared_sequences"] == 1
    assert "grid_hex_rows" not in model_status["state"]
    assert "available_actions" not in model_status["state"]
    assert "grid_hex_rows" not in payload
    assert "available_actions" not in payload


def test_model_compare_sequences_skips_reset_ended_sequences_by_default(tmp_path: Path) -> None:
    game_dir = tmp_path / "game_ls20"
    _copy_model_templates(game_dir)

    initial_rows = ["0000", "0000", "0000", "0000"]
    _write_hex(game_dir / "level_1" / "initial_state.hex", initial_rows)

    for seq_id in ("seq_0001", "seq_0002"):
        step_dir = game_dir / "level_1" / "sequences" / seq_id / "actions" / "step_0001_action_000001_action1"
        _write_hex(step_dir / "before_state.hex", initial_rows)
        _write_hex(step_dir / "after_state.hex", initial_rows)
        (step_dir / "meta.json").write_text(json.dumps({"schema_version": "arc_repl.sequence_action.v1"}, indent=2))

    seq_1 = {
        "schema_version": "arc_repl.level_sequence.v1",
        "game_id": "ls20",
        "level": 1,
        "sequence_id": "seq_0001",
        "sequence_number": 1,
        "start_action_index": 1,
        "end_action_index": 1,
        "start_recorded_at_utc": "",
        "end_recorded_at_utc": "",
        "end_reason": "reset_level",
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
    seq_2 = {
        **seq_1,
        "sequence_id": "seq_0002",
        "sequence_number": 2,
        "end_reason": "open",
        "actions": [
            {
                **seq_1["actions"][0],
                "files": {
                    "before_state_hex": "sequences/seq_0002/actions/step_0001_action_000001_action1/before_state.hex",
                    "after_state_hex": "sequences/seq_0002/actions/step_0001_action_000001_action1/after_state.hex",
                    "meta_json": "sequences/seq_0002/actions/step_0001_action_000001_action1/meta.json",
                },
            }
        ],
    }
    seq_root = game_dir / "level_1" / "sequences"
    seq_root.mkdir(parents=True, exist_ok=True)
    (seq_root / "seq_0001.json").write_text(json.dumps(seq_1, indent=2))
    (seq_root / "seq_0002.json").write_text(json.dumps(seq_2, indent=2))

    proc = _run_model(game_dir, ["compare_sequences", "--game-id", "ls20", "--level", "1"])
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["requested_sequences"] == 2
    assert payload["eligible_sequences"] == 1
    assert payload["compared_sequences"] == 1
    skipped = payload["skipped_sequences"]
    assert any(item.get("sequence_id") == "seq_0001" and item.get("reason") == "reset_ended" for item in skipped)


def test_model_compare_sequences_returns_error_when_no_eligible_sequences(tmp_path: Path) -> None:
    game_dir = tmp_path / "game_ls20"
    _copy_model_templates(game_dir)
    initial_rows = ["0000", "0000", "0000", "0000"]
    _write_hex(game_dir / "level_1" / "initial_state.hex", initial_rows)
    step_dir = game_dir / "level_1" / "sequences" / "seq_0001" / "actions" / "step_0001_action_000001_action1"
    _write_hex(step_dir / "before_state.hex", initial_rows)
    _write_hex(step_dir / "after_state.hex", initial_rows)
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
        "end_reason": "reset_level",
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
    seq_root = game_dir / "level_1" / "sequences"
    seq_root.mkdir(parents=True, exist_ok=True)
    (seq_root / "seq_0001.json").write_text(json.dumps(seq_payload, indent=2))

    proc = _run_model(game_dir, ["compare_sequences", "--game-id", "ls20", "--level", "1"])
    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    assert payload["ok"] is False
    assert payload["error"]["type"] == "no_eligible_sequences"
    assert payload["requested_sequences"] == 1
    assert payload["eligible_sequences"] == 0
    assert any(item.get("reason") == "reset_ended" for item in payload["skipped_sequences"])


def test_model_lib_load_initial_grid_accepts_string_path(tmp_path: Path) -> None:
    game_dir = tmp_path / "game_ls20"
    _copy_model_templates(game_dir)
    _write_hex(game_dir / "level_1" / "initial_state.hex", ["0123", "4567"])

    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "sys.path.insert(0, '.'); "
                "import model_lib; "
                "grid = model_lib.load_initial_grid('.', 1); "
                "print(grid.shape); "
                "print(''.join(format(int(v), 'X') for v in grid[0]))"
            ),
        ],
        cwd=game_dir,
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "(2, 4)" in proc.stdout
    assert "0123" in proc.stdout


def test_inspect_sequence_current_mismatch_reports_step_artifacts(tmp_path: Path) -> None:
    game_dir = tmp_path / "game_ls20"
    _copy_model_templates(game_dir)
    _write_hex(game_dir / "level_2" / "initial_state.hex", ["0000", "0000"])

    step_dir = game_dir / "level_2" / "sequences" / "seq_0002" / "actions" / "step_0001_action_000058_action1"
    _write_hex(step_dir / "before_state.hex", ["0000", "0000"])
    _write_hex(step_dir / "after_state.hex", ["1111", "1111"])
    (step_dir / "meta.json").write_text(json.dumps({"schema_version": "arc_repl.sequence_action.v1"}, indent=2))

    seq_payload = {
        "schema_version": "arc_repl.level_sequence.v1",
        "game_id": "ls20",
        "level": 2,
        "sequence_id": "seq_0002",
        "sequence_number": 2,
        "start_action_index": 58,
        "end_action_index": 58,
        "start_recorded_at_utc": "",
        "end_recorded_at_utc": "",
        "end_reason": "open",
        "action_count": 1,
        "actions": [
            {
                "local_step": 1,
                "action_index": 58,
                "tool_turn": 21,
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
                    "before_state_hex": "sequences/seq_0002/actions/step_0001_action_000058_action1/before_state.hex",
                    "after_state_hex": "sequences/seq_0002/actions/step_0001_action_000058_action1/after_state.hex",
                    "meta_json": "sequences/seq_0002/actions/step_0001_action_000058_action1/meta.json",
                },
            }
        ],
    }
    seq_root = game_dir / "level_2" / "sequences"
    seq_root.mkdir(parents=True, exist_ok=True)
    (seq_root / "seq_0002.json").write_text(json.dumps(seq_payload, indent=2))
    (game_dir / "current_compare.json").write_text(
        json.dumps(
            {
                "level": 2,
                "all_match": False,
                "compared_sequences": 1,
                "diverged_sequences": 1,
                "reports": [
                    {
                        "level": 2,
                        "sequence_id": "seq_0002",
                        "matched": False,
                        "divergence_step": 1,
                        "divergence_reason": "after_state_mismatch",
                        "game_step_diff": {"changed_pixels": 8},
                        "model_step_diff": {"changed_pixels": 4},
                    }
                ],
            },
            indent=2,
        )
    )

    proc = subprocess.run(
        [sys.executable, str(game_dir / "inspect_sequence.py"), "--current-mismatch"],
        cwd=game_dir,
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["compare"]["divergence_reason"] == "after_state_mismatch"
    assert payload["sequence_id"] == "seq_0002"
    assert payload["step"]["local_step"] == 1
    assert payload["step"]["before_state_hex"].endswith("before_state.hex")


def test_inspect_sequence_current_mismatch_returns_clean_status(tmp_path: Path) -> None:
    game_dir = tmp_path / "game_ls20"
    _copy_model_templates(game_dir)
    (game_dir / "current_compare.json").write_text(
        json.dumps(
            {
                "level": 1,
                "all_match": True,
                "compared_sequences": 1,
                "diverged_sequences": 0,
                "reports": [
                    {
                        "level": 1,
                        "sequence_id": "seq_0001",
                        "matched": True,
                        "report_file": "level_1/sequence_compare/seq_0001.md",
                    }
                ],
            },
            indent=2,
        )
    )

    proc = subprocess.run(
        [sys.executable, str(game_dir / "inspect_sequence.py"), "--current-mismatch"],
        cwd=game_dir,
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "clean"
    assert payload["mismatch"] is None
    assert payload["compare"]["status"] == "clean"


def test_inspect_sequence_current_compare_reports_status_and_paths(tmp_path: Path) -> None:
    game_dir = tmp_path / "game_ls20"
    _copy_model_templates(game_dir)
    (game_dir / "current_compare.json").write_text(
        json.dumps(
            {
                "level": 3,
                "all_match": False,
                "compared_sequences": 2,
                "diverged_sequences": 1,
                "reports": [
                    {
                        "level": 3,
                        "sequence_id": "seq_0004",
                        "matched": False,
                        "divergence_step": 5,
                        "divergence_reason": "after_state_mismatch",
                        "report_file": "level_3/sequence_compare/seq_0004.md",
                        "state_diff": {"changed_pixels": 17},
                    }
                ],
            },
            indent=2,
        )
    )

    proc = subprocess.run(
        [sys.executable, str(game_dir / "inspect_sequence.py"), "--current-compare"],
        cwd=game_dir,
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "mismatch"
    assert payload["report_file"] == "level_3/sequence_compare/seq_0004.md"
    assert payload["mismatch"]["sequence_id"] == "seq_0004"
