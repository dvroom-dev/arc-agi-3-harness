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


def test_model_status_hides_frontier_level_while_analysis_pin_is_active(tmp_path: Path) -> None:
    game_dir = tmp_path / "game_ls20"
    _copy_model_templates(game_dir)
    _write_hex(game_dir / "level_1" / "initial_state.hex", ["0123", "4567"])
    _write_hex(game_dir / "level_2" / "initial_state.hex", ["89AB", "CDEF"])
    (game_dir / ".analysis_level_pin.json").write_text(
        json.dumps({"level": 1, "phase": "theory_passed"}, indent=2)
    )
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
    assert payload["current_level"] == 1
    assert payload["levels_completed"] == 0
    assert payload["available_model_levels"] == [1]


def test_model_discovers_level_initial_state_via_level_current_symlink(tmp_path: Path) -> None:
    game_dir = tmp_path / "game_ls20"
    _copy_model_templates(game_dir)
    _write_hex(game_dir / "level_current" / "initial_state.hex", ["0123", "4567"])
    (game_dir / "level_current" / "meta.json").write_text(
        json.dumps({"schema_version": "arc_repl.level_current.v1", "level": 1}, indent=2)
    )
    (game_dir / "level_1").symlink_to("level_current", target_is_directory=True)

    proc = _run_model_with_env(game_dir, ["status", "--game-id", "ls20"], extra_env={})
    assert proc.returncode == 0, proc.stdout
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["available_model_levels"] == [1]


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
    assert "visible level 2 is active for model work" in payload["error"]["message"]


def test_compare_sequences_uses_pinned_solved_level_until_theory_and_code_model_finish(tmp_path: Path) -> None:
    game_dir = tmp_path / "game_ls20"
    _copy_model_templates(game_dir)
    _write_hex(game_dir / "level_1" / "initial_state.hex", ["0000", "0000"])
    _write_hex(game_dir / "level_2" / "initial_state.hex", ["1111", "1111"])
    (game_dir / "model_lib.py").write_text(
        (game_dir / "model_lib.py").read_text() + "\n\ndef is_level_complete(env):\n    return int(env.turn) >= 1\n"
    )
    arc_state_dir = tmp_path / "arc"
    arc_state_dir.mkdir(parents=True, exist_ok=True)
    (arc_state_dir / "state.json").write_text(json.dumps({"current_level": 2, "levels_completed": 1}, indent=2))
    (game_dir / ".analysis_level_pin.json").write_text(
        json.dumps({"level": 1, "phase": "pending_theory"}, indent=2)
    )

    step_dir = game_dir / "level_1" / "sequences" / "seq_0001" / "actions" / "step_0001_action_000001_action1"
    _write_hex(step_dir / "before_state.hex", ["0000", "0000"])
    _write_hex(step_dir / "after_state.hex", ["1111", "1111"])
    (step_dir / "meta.json").write_text(json.dumps({"schema_version": "arc_repl.sequence_action.v1"}, indent=2))
    seq_payload = {
        "schema_version": "arc_repl.level_sequence.v1",
        "game_id": "ls20",
        "level": 1,
        "sequence_id": "seq_0001",
        "end_reason": "level_change",
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
                "level_after": 2,
                "levels_completed_before": 0,
                "levels_completed_after": 1,
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

    proc = _run_model_with_env(
        game_dir,
        ["compare_sequences", "--game-id", "ls20"],
        extra_env={"ARC_STATE_DIR": str(arc_state_dir)},
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["level"] == 1
    assert payload["analysis_level_pinned"] is True
    pin = json.loads((game_dir / ".analysis_level_pin.json").read_text())
    assert pin["phase"] == "pending_theory"
    assert pin["last_compare_all_match"] is True
    assert pin["last_compare_level"] == 1


def test_sync_workspace_level_view_uses_pinned_level(tmp_path: Path) -> None:
    from arc_model_runtime.utils import sync_workspace_level_view

    game_dir = tmp_path / "game_ls20"
    game_dir.mkdir(parents=True, exist_ok=True)
    _write_hex(game_dir / "level_1" / "initial_state.hex", ["0000", "0000"])
    _write_hex(game_dir / "level_2" / "initial_state.hex", ["1111", "1111"])
    (game_dir / ".analysis_level_pin.json").write_text(
        json.dumps({"level": 1, "phase": "pending_theory"}, indent=2)
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
    meta = json.loads((game_dir / "level_current" / "meta.json").read_text())
    assert meta["level"] == 1
    assert meta["analysis_level_pinned"] is True
    assert (game_dir / "level_1").exists()
    assert not (game_dir / "level_2").exists()


def test_sync_workspace_level_view_redacts_cross_level_turn_artifacts_while_pinned(tmp_path: Path) -> None:
    from arc_model_runtime.utils import sync_workspace_level_view

    game_dir = tmp_path / "game_ls20"
    game_dir.mkdir(parents=True, exist_ok=True)
    (game_dir / ".analysis_level_pin.json").write_text(
        json.dumps({"level": 1, "phase": "pending_theory"}, indent=2)
    )
    arc_state_dir = tmp_path / "arc"
    artifacts_root = arc_state_dir / "game_artifacts" / "game_ls20" / "level_1"
    _write_hex(artifacts_root / "initial_state.hex", ["0000", "0000"])
    _write_hex(artifacts_root / "current_state.hex", ["2222", "2222"])
    _write_hex(artifacts_root / "turn_0021" / "before_state.hex", ["0000", "0000"])
    _write_hex(artifacts_root / "turn_0021" / "after_state.hex", ["2222", "2222"])
    (artifacts_root / "turn_0021" / "meta.json").write_text(
        json.dumps(
            {
                "schema_version": "arc_repl.level_turn_artifact.v1",
                "level_before": 1,
                "level_after": 2,
                "levels_completed_before": 0,
                "levels_completed_after": 1,
            },
            indent=2,
        )
    )

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
    copied_meta = json.loads((game_dir / "level_current" / "turn_0021" / "meta.json").read_text())
    assert copied_meta["level_after"] == 1
    assert copied_meta["levels_completed_after"] == 0
    assert copied_meta["analysis_level_boundary_redacted"] is True
    level_status = json.loads((game_dir / "level_current" / "analysis_level_status.json").read_text())
    assert level_status["analysis_level_pinned"] is True
    assert level_status["frontier_hidden_by_pin"] is True
    assert level_status["next_allowed_operation"] == "finalize_pinned_level"
    transition_status = json.loads((game_dir / "level_current" / "level_transition.json").read_text())
    assert transition_status["analysis_level_boundary_redacted"] is True
    assert (game_dir / "level_current" / "after_state.hex").exists() is False
    assert (game_dir / "level_current" / "current_state.hex").read_text().splitlines() == ["0000", "0000"]
    assert (game_dir / "level_current" / "turn_0021" / "after_state.hex").read_text().splitlines() == [
        "0000",
        "0000",
    ]
