from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from arc_model_runtime.utils import resolve_level_dir


def _write_hex(path: Path, rows: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


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


def _run_model(game_dir: Path, args: list[str], *, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["ARC_CONFIG_DIR"] = str((game_dir.parent / "config").resolve())
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, str(game_dir / "model.py"), *args],
        cwd=game_dir,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def _run_inspect_sequence(game_dir: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["ARC_CONFIG_DIR"] = str((game_dir.parent / "config").resolve())
    return subprocess.run(
        [sys.executable, str(game_dir / "inspect_sequence.py"), *args],
        cwd=game_dir,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def test_resolve_level_dir_prefers_explicit_analysis_level_surface(tmp_path: Path) -> None:
    game_dir = tmp_path / "game_ls20"
    game_dir.mkdir(parents=True, exist_ok=True)
    (game_dir / "analysis_state.json").write_text(
        json.dumps(
            {
                "schema_version": "arc.analysis_state.v2",
                "analysis_scope": "wrapup",
                "analysis_level": 1,
                "frontier_level": 2,
                "analysis_level_dir": "analysis_level",
                "level_current_dir": "level_current",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (game_dir / "analysis_level").mkdir()
    (game_dir / "analysis_level" / "meta.json").write_text(json.dumps({"level": 1}, indent=2) + "\n", encoding="utf-8")
    (game_dir / "level_current").mkdir()
    (game_dir / "level_current" / "meta.json").write_text(json.dumps({"level": 2}, indent=2) + "\n", encoding="utf-8")

    resolved = resolve_level_dir(game_dir, 1)

    assert resolved == game_dir / "analysis_level"


def test_wrapup_compare_and_inspect_sequence_use_analysis_level_surface(tmp_path: Path) -> None:
    game_dir = tmp_path / "game_ls20"
    _copy_model_templates(game_dir)
    (game_dir / "analysis_state.json").write_text(
        json.dumps(
            {
                "schema_version": "arc.analysis_state.v2",
                "analysis_scope": "wrapup",
                "analysis_level": 1,
                "frontier_level": 2,
                "analysis_level_dir": "analysis_level",
                "level_current_dir": "level_current",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (game_dir / "level_current").mkdir(parents=True, exist_ok=True)
    (game_dir / "level_current" / "meta.json").write_text(json.dumps({"level": 2}, indent=2) + "\n", encoding="utf-8")
    _write_hex(game_dir / "level_current" / "initial_state.hex", ["2222", "2222"])
    _write_hex(game_dir / "level_1" / "initial_state.hex", ["0000", "0000"])
    _write_hex(game_dir / "analysis_level" / "initial_state.hex", ["0000", "0000"])
    (game_dir / "analysis_level" / "meta.json").write_text(json.dumps({"level": 1}, indent=2) + "\n", encoding="utf-8")

    step1_dir = game_dir / "analysis_level" / "sequences" / "seq_0001" / "actions" / "step_0001_action_000001_action1"
    _write_hex(step1_dir / "before_state.hex", ["0000", "0000"])
    _write_hex(step1_dir / "after_state.hex", ["1111", "1111"])
    (step1_dir / "meta.json").write_text(json.dumps({"schema_version": "arc_repl.sequence_action.v1"}, indent=2) + "\n", encoding="utf-8")

    seq_payload = {
        "schema_version": "arc_repl.level_sequence.v1",
        "game_id": "ls20",
        "level": 1,
        "sequence_id": "seq_0001",
        "start_action_index": 1,
        "end_action_index": 1,
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
                "files": {
                    "before_state_hex": "sequences/seq_0001/actions/step_0001_action_000001_action1/before_state.hex",
                    "after_state_hex": "sequences/seq_0001/actions/step_0001_action_000001_action1/after_state.hex",
                    "meta_json": "sequences/seq_0001/actions/step_0001_action_000001_action1/meta.json",
                },
            }
        ],
    }
    seq_root = game_dir / "analysis_level" / "sequences"
    seq_root.mkdir(parents=True, exist_ok=True)
    (seq_root / "seq_0001.json").write_text(json.dumps(seq_payload, indent=2) + "\n", encoding="utf-8")

    current_compare_payload = {
        "schema_version": "arc.compare.current.v1",
        "level": 1,
        "all_match": False,
        "compared_sequences": 1,
        "diverged_sequences": 1,
        "reports": [
            {
                "sequence_id": "seq_0001",
                "matched": False,
                "divergence_step": 1,
                "divergence_reason": "after_state_mismatch",
                "report_file": "analysis_level/sequence_compare/seq_0001.md",
            }
        ],
    }
    (game_dir / "current_compare.json").write_text(json.dumps(current_compare_payload, indent=2) + "\n", encoding="utf-8")
    analysis_compare_dir = game_dir / "analysis_level" / "sequence_compare"
    analysis_compare_dir.mkdir(parents=True, exist_ok=True)
    (analysis_compare_dir / "seq_0001.md").write_text("# Sequence Comparison: seq_0001\n", encoding="utf-8")
    (analysis_compare_dir / "current_compare.md").write_text("# Current Compare (Level 1)\n", encoding="utf-8")

    proc = _run_inspect_sequence(game_dir, ["--current-mismatch"])

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["sequence_file"] == "analysis_level/sequences/seq_0001.json"
    assert payload["step"]["before_state_hex"] == "analysis_level/sequences/seq_0001/actions/step_0001_action_000001_action1/before_state.hex"

    compare_proc = _run_model(game_dir, ["compare_sequences", "--game-id", "ls20", "--level", "1"])
    assert compare_proc.returncode == 0, compare_proc.stderr
    root_compare = json.loads((game_dir / "current_compare.json").read_text(encoding="utf-8"))
    assert root_compare["level"] == 1
    assert root_compare["reports"][0]["report_file"] == "analysis_level/sequence_compare/seq_0001.md"
    assert (game_dir / "analysis_level" / "sequence_compare" / "seq_0001.md").exists()
    assert not (game_dir / "level_current" / "sequence_compare" / "seq_0001.md").exists()
