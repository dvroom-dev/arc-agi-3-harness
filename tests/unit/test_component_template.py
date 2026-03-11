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


def _run_helper(game_dir: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["ARC_CONFIG_DIR"] = str((game_dir.parent / "config").resolve())
    return subprocess.run(
        [sys.executable, str(game_dir / "inspect_components.py"), *args],
        cwd=game_dir,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def test_component_coverage_helper_reports_uncovered_pixels(tmp_path: Path) -> None:
    game_dir = tmp_path / "game_ls20"
    _copy_model_templates(game_dir)
    _write_hex(game_dir / "level_1" / "initial_state.hex", ["0123", "4567"])

    proc = _run_helper(game_dir, ["--coverage", "--level", "1"])
    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    assert payload["status"] == "fail"
    assert payload["observed_shapes"] == ["2x4"]
    assert payload["first_failure"]["label"] == "level_1:initial_state"
    assert payload["first_failure"]["shape"] == "2x4"
    assert payload["first_failure"]["uncovered_pixel_count"] == 8
    assert (game_dir / "component_coverage.json").exists()
    assert (game_dir / "component_coverage.md").exists()


def test_component_coverage_does_not_advance_analysis_level_pin_phase(tmp_path: Path) -> None:
    game_dir = tmp_path / "game_ls20"
    _copy_model_templates(game_dir)
    _write_hex(game_dir / "level_1" / "initial_state.hex", ["0000", "0000", "0000", "0000"])
    (game_dir / "components.py").write_text(
        "from dataclasses import dataclass, field\n"
        "from typing import Callable\n"
        "import numpy as np\n"
        "@dataclass(frozen=True)\n"
        "class ComponentBox:\n"
        "    kind: str\n"
        "    bbox: tuple[int, int, int, int]\n"
        "    attrs: dict[str, object] = field(default_factory=dict)\n"
        "ComponentDetector = Callable[[np.ndarray], list[ComponentBox]]\n"
        "COMPONENT_REGISTRY = {}\n"
        "def make_component(kind, *, top, left, bottom, right, **attrs):\n"
        "    return ComponentBox(kind=kind, bbox=(top, left, bottom, right), attrs=dict(attrs))\n"
        "def iter_components(grid):\n"
        "    out = []\n"
        "    for kind, detector in COMPONENT_REGISTRY.items():\n"
        "        out.extend(detector(grid))\n"
        "    return out\n"
        "def find_all_bg(grid):\n"
        "    rows, cols = grid.shape\n"
        "    return [make_component('bg', top=0, left=0, bottom=rows - 1, right=cols - 1)]\n"
        "COMPONENT_REGISTRY['bg'] = find_all_bg\n"
    )
    (game_dir / ".analysis_level_pin.json").write_text(
        json.dumps({"level": 1, "phase": "pending_theory"}, indent=2)
    )

    proc = _run_helper(game_dir, ["--coverage", "--level", "1"])
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["observed_shapes"] == ["4x4"]
    pin = json.loads((game_dir / ".analysis_level_pin.json").read_text())
    assert pin["phase"] == "pending_theory"
    assert "coverage_checked_level" not in pin


def test_component_mismatch_helper_reads_wrapped_current_compare_payload(tmp_path: Path) -> None:
    game_dir = tmp_path / "game_ls20"
    _copy_model_templates(game_dir)
    _write_hex(game_dir / "level_1" / "initial_state.hex", ["4444", "4444", "4444", "4444"])

    step_dir = game_dir / "level_1" / "sequences" / "seq_0001" / "actions" / "step_0001_action_000001_action1"
    _write_hex(step_dir / "before_state.hex", ["4444", "4444", "4444", "4444"])
    _write_hex(step_dir / "after_state.hex", ["4444", "4994", "4994", "4444"])
    _write_hex(step_dir / "diff.hex", ["....", ".99.", ".99.", "...."])
    (step_dir / "meta.json").write_text(json.dumps({"schema_version": "arc_repl.sequence_action.v1"}, indent=2))

    seq_payload = {
        "schema_version": "arc_repl.level_sequence.v1",
        "game_id": "ls20",
        "level": 1,
        "sequence_id": "seq_0001",
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
                    "diff_hex": "sequences/seq_0001/actions/step_0001_action_000001_action1/diff.hex",
                    "meta_json": "sequences/seq_0001/actions/step_0001_action_000001_action1/meta.json",
                },
            }
        ],
    }
    seq_file = game_dir / "level_1" / "sequences" / "seq_0001.json"
    seq_file.parent.mkdir(parents=True, exist_ok=True)
    seq_file.write_text(json.dumps(seq_payload, indent=2))

    (game_dir / "current_compare.json").write_text(
        json.dumps(
            {
                "level": 1,
                "all_match": False,
                "compared_sequences": 1,
                "diverged_sequences": 1,
                "compare_payload": {
                    "level": 1,
                    "all_match": False,
                    "compared_sequences": 1,
                    "diverged_sequences": 1,
                    "reports": [
                        {
                            "level": 1,
                            "sequence_id": "seq_0001",
                            "matched": False,
                            "divergence_step": 1,
                            "divergence_reason": "after_state_mismatch",
                            "game_step_diff": {"changed_pixels": 4},
                            "model_step_diff": {"changed_pixels": 0},
                            "state_diff": {"changed_pixels": 4},
                        }
                    ],
                },
            },
            indent=2,
        )
    )

    proc = _run_helper(game_dir, ["--current-mismatch"])
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "mismatch"
    assert payload["compare"]["divergence_reason"] == "after_state_mismatch"
    assert payload["sequence"]["sequence_id"] == "seq_0001"


def test_component_mismatch_helper_errors_when_compare_is_red_without_report(tmp_path: Path) -> None:
    game_dir = tmp_path / "game_ls20"
    _copy_model_templates(game_dir)
    _write_hex(game_dir / "level_1" / "initial_state.hex", ["4444", "4444"])
    (game_dir / "current_compare.json").write_text(
        json.dumps(
            {
                "level": 1,
                "all_match": False,
                "compared_sequences": 1,
                "diverged_sequences": 1,
                "reports": [],
            },
            indent=2,
        )
    )

    proc = _run_helper(game_dir, ["--current-mismatch"])
    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    assert payload["status"] == "error"
    assert "not clean" in payload["message"]


def test_component_mismatch_helper_falls_back_to_canonical_level_artifacts(tmp_path: Path) -> None:
    game_dir = tmp_path / "game_ls20"
    _copy_model_templates(game_dir)
    state_dir = tmp_path / "arc_state"
    canonical_level = state_dir / "game_artifacts" / "game_ls20" / "level_1"
    canonical_step = canonical_level / "sequences" / "seq_0001" / "actions" / "step_0001_action_000001_action1"
    canonical_step.mkdir(parents=True, exist_ok=True)
    _write_hex(canonical_level / "initial_state.hex", ["4444", "4444", "4444", "4444"])
    _write_hex(canonical_step / "before_state.hex", ["4444", "4444", "4444", "4444"])
    _write_hex(canonical_step / "after_state.hex", ["4444", "4994", "4994", "4444"])
    _write_hex(canonical_step / "diff.hex", ["....", ".99.", ".99.", "...."])
    (canonical_step / "meta.json").write_text(json.dumps({"schema_version": "arc_repl.sequence_action.v1"}, indent=2))
    (canonical_level / "sequences" / "seq_0001.json").write_text(
        json.dumps(
            {
                "schema_version": "arc_repl.level_sequence.v1",
                "game_id": "ls20",
                "level": 1,
                "sequence_id": "seq_0001",
                "action_count": 1,
                "actions": [
                    {
                        "local_step": 1,
                        "action_index": 1,
                        "tool_turn": 1,
                        "step_in_call": 1,
                        "call_action": "exec",
                        "action_name": "ACTION1",
                        "state_before": "NOT_FINISHED",
                        "state_after": "NOT_FINISHED",
                        "level_before": 1,
                        "level_after": 1,
                        "levels_completed_before": 0,
                        "levels_completed_after": 0,
                        "files": {
                            "before_state_hex": "sequences/seq_0001/actions/step_0001_action_000001_action1/before_state.hex",
                            "after_state_hex": "sequences/seq_0001/actions/step_0001_action_000001_action1/after_state.hex",
                            "diff_hex": "sequences/seq_0001/actions/step_0001_action_000001_action1/diff.hex",
                            "meta_json": "sequences/seq_0001/actions/step_0001_action_000001_action1/meta.json",
                        },
                    }
                ],
            },
            indent=2,
        )
    )

    (game_dir / "current_compare.json").write_text(
        json.dumps(
            {
                "level": 1,
                "all_match": False,
                "reports": [
                    {
                        "level": 1,
                        "sequence_id": "seq_0001",
                        "matched": False,
                        "divergence_step": 1,
                        "divergence_reason": "after_state_mismatch",
                    }
                ],
            },
            indent=2,
        )
    )

    env = dict(os.environ)
    env["ARC_CONFIG_DIR"] = str((game_dir.parent / "config").resolve())
    env["ARC_STATE_DIR"] = str(state_dir.resolve())
    env["ARC_ACTIVE_GAME_ID"] = "ls20"
    proc = subprocess.run(
        [sys.executable, str(game_dir / "inspect_components.py"), "--current-mismatch"],
        cwd=game_dir,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "mismatch"
    assert payload["sequence"]["sequence_id"] == "seq_0001"
