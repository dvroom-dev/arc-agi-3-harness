from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import arc_repl_compare_intercepts
import arc_repl_intercepts


def test_run_exec_compare_intercept_writes_current_compare_artifacts(monkeypatch, tmp_path: Path) -> None:
    cwd = tmp_path / "agent"
    cwd.mkdir(parents=True, exist_ok=True)
    (cwd / "model.py").write_text("# model\n", encoding="utf-8")
    (cwd / "inspect_components.py").write_text(
        "import json\nprint(json.dumps({'status': 'clean', 'message': 'ok'}))\n",
        encoding="utf-8",
    )

    arc_state_dir = tmp_path / "arc"
    monkeypatch.setenv("ARC_STATE_DIR", str(arc_state_dir))

    level_dir = arc_state_dir / "game_artifacts" / "game_ls20" / "level_3" / "sequences"
    level_dir.mkdir(parents=True, exist_ok=True)
    (level_dir / "seq_0001.json").write_text(
        json.dumps(
            {
                "sequence_id": "seq_0001",
                "end_reason": "active",
                "actions": [{"levels_completed_before": 2, "levels_completed_after": 2}],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        arc_repl_compare_intercepts.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "ok": True,
                    "all_match": False,
                    "compared_sequences": 1,
                    "diverged_sequences": 1,
                }
            ),
            stderr="",
        ),
    )

    marker = arc_repl_intercepts.run_exec_compare_intercept(
        cwd,
        {
            "ok": True,
            "game_id": "ls20",
            "current_level": 3,
            "steps_executed": 2,
            "levels_gained_in_call": 0,
            "state": "NOT_FINISHED",
        },
    )

    assert marker is not None
    assert "__ARC_INTERCEPT_COMPARE_MISMATCH__" in marker
    assert (cwd / "current_compare.md").exists()
    assert (cwd / "current_compare.json").exists()
    assert (cwd / "level_current" / "sequence_compare" / "current_compare.md").exists()
    current_compare_json = json.loads((cwd / "current_compare.json").read_text(encoding="utf-8"))
    current_compare_md = (cwd / "current_compare.md").read_text(encoding="utf-8")
    assert current_compare_json["all_match"] is False
    assert "- all_match: false" in current_compare_md
    assert "## Full Payload" in current_compare_md
    assert (
        arc_state_dir
        / "game_artifacts"
        / "game_ls20"
        / "level_3"
        / "sequence_compare"
        / "current_compare.md"
    ).exists()


def test_run_exec_compare_intercept_does_not_fail_when_canonical_compare_dir_is_not_writable(
    monkeypatch, tmp_path: Path
) -> None:
    cwd = tmp_path / "agent"
    cwd.mkdir(parents=True, exist_ok=True)
    (cwd / "model.py").write_text("# model\n", encoding="utf-8")

    arc_state_dir = tmp_path / "arc"
    monkeypatch.setenv("ARC_STATE_DIR", str(arc_state_dir))

    level_dir = arc_state_dir / "game_artifacts" / "game_ls20" / "level_1" / "sequences"
    level_dir.mkdir(parents=True, exist_ok=True)
    (level_dir / "seq_0001.json").write_text(
        json.dumps(
            {
                "sequence_id": "seq_0001",
                "end_reason": "active",
                "actions": [{"levels_completed_before": 0, "levels_completed_after": 0}],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        arc_repl_compare_intercepts.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "ok": True,
                    "all_match": False,
                    "compared_sequences": 1,
                    "diverged_sequences": 1,
                }
            ),
            stderr="",
        ),
    )

    original_write_compare_artifact = arc_repl_compare_intercepts._write_compare_artifact

    def fake_write_compare_artifact(path: Path, text: str) -> None:
        if "game_artifacts" in str(path):
            raise PermissionError(13, "Permission denied", str(path))
        original_write_compare_artifact(path, text)

    monkeypatch.setattr(
        arc_repl_compare_intercepts,
        "_write_compare_artifact",
        fake_write_compare_artifact,
    )

    marker = arc_repl_intercepts.run_exec_compare_intercept(
        cwd,
        {
            "ok": True,
            "game_id": "ls20",
            "current_level": 1,
            "steps_executed": 1,
            "levels_gained_in_call": 0,
            "state": "NOT_FINISHED",
        },
    )

    assert marker is not None
    assert "__ARC_INTERCEPT_COMPARE_MISMATCH__" in marker
    assert (cwd / "current_compare.md").exists()
    assert (cwd / "current_compare.json").exists()
    assert (cwd / "level_current" / "sequence_compare" / "current_compare.md").exists()


def test_run_exec_compare_intercept_returns_mismatch_marker_on_level_one_before_first_completion(
    monkeypatch, tmp_path: Path
) -> None:
    cwd = tmp_path / "agent"
    cwd.mkdir(parents=True, exist_ok=True)
    (cwd / "model.py").write_text("# model\n", encoding="utf-8")
    (cwd / "inspect_components.py").write_text(
        "import json\nprint(json.dumps({'status': 'mismatch'}))\n",
        encoding="utf-8",
    )

    arc_state_dir = tmp_path / "arc"
    monkeypatch.setenv("ARC_STATE_DIR", str(arc_state_dir))

    level_dir = arc_state_dir / "game_artifacts" / "game_ls20" / "level_1" / "sequences"
    level_dir.mkdir(parents=True, exist_ok=True)
    (level_dir / "seq_0001.json").write_text(
        json.dumps(
            {
                "sequence_id": "seq_0001",
                "end_reason": "active",
                "actions": [{"levels_completed_before": 0, "levels_completed_after": 0}],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        arc_repl_compare_intercepts.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "ok": True,
                    "all_match": False,
                    "compared_sequences": 1,
                    "diverged_sequences": 1,
                    "reports": [
                        {
                            "sequence_id": "seq_0001",
                            "matched": False,
                            "divergence_step": 1,
                            "divergence_reason": "after_state_mismatch",
                        }
                    ],
                }
            ),
            stderr="",
        ),
    )

    marker = arc_repl_intercepts.run_exec_compare_intercept(
        cwd,
        {
            "ok": True,
            "game_id": "ls20",
            "current_level": 1,
            "steps_executed": 1,
            "levels_gained_in_call": 0,
            "levels_completed": 0,
            "state": "NOT_FINISHED",
        },
    )

    assert marker is not None
    assert "__ARC_INTERCEPT_COMPARE_MISMATCH__" in marker


def test_run_exec_compare_intercept_returns_clean_marker_on_level_gain(monkeypatch, tmp_path: Path) -> None:
    cwd = tmp_path / "agent"
    cwd.mkdir(parents=True, exist_ok=True)
    (cwd / "model.py").write_text("# model\n", encoding="utf-8")
    (cwd / "inspect_components.py").write_text(
        "import json\nprint(json.dumps({'status': 'clean', 'message': 'ok'}))\n",
        encoding="utf-8",
    )

    arc_state_dir = tmp_path / "arc"
    monkeypatch.setenv("ARC_STATE_DIR", str(arc_state_dir))

    level_dir = arc_state_dir / "game_artifacts" / "game_ls20" / "level_2" / "sequences"
    level_dir.mkdir(parents=True, exist_ok=True)
    (level_dir / "seq_0001.json").write_text(
        json.dumps(
            {
                "sequence_id": "seq_0001",
                "end_reason": "level_change",
                "actions": [{"levels_completed_before": 1, "levels_completed_after": 2}],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        arc_repl_compare_intercepts.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "ok": True,
                    "all_match": True,
                    "compared_sequences": 1,
                    "diverged_sequences": 0,
                }
            ),
            stderr="",
        ),
    )

    marker = arc_repl_intercepts.run_exec_compare_intercept(
        cwd,
        {
            "ok": True,
            "game_id": "ls20",
            "current_level": 3,
            "levels_completed": 2,
            "levels_gained_in_call": 1,
            "steps_executed": 4,
            "state": "NOT_FINISHED",
        },
    )

    assert marker is not None
    assert "__ARC_INTERCEPT_COMPARE_CLEAN__" in marker
    assert "level=2" in marker
    assert not (cwd / ".analysis_level_pin.json").exists()


def test_run_exec_compare_intercept_returns_none_when_clean_without_level_gain(
    monkeypatch, tmp_path: Path
) -> None:
    cwd = tmp_path / "agent"
    cwd.mkdir(parents=True, exist_ok=True)
    (cwd / "model.py").write_text("# model\n", encoding="utf-8")
    (cwd / "inspect_components.py").write_text(
        "import json\nprint(json.dumps({'status': 'clean', 'message': 'ok'}))\n",
        encoding="utf-8",
    )

    arc_state_dir = tmp_path / "arc"
    monkeypatch.setenv("ARC_STATE_DIR", str(arc_state_dir))

    level_dir = arc_state_dir / "game_artifacts" / "game_ls20" / "level_1" / "sequences"
    level_dir.mkdir(parents=True, exist_ok=True)
    (level_dir / "seq_0001.json").write_text(
        json.dumps(
            {
                "sequence_id": "seq_0001",
                "end_reason": "active",
                "actions": [{"levels_completed_before": 0, "levels_completed_after": 0}],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        arc_repl_compare_intercepts.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "ok": True,
                    "all_match": True,
                    "compared_sequences": 1,
                    "diverged_sequences": 0,
                }
            ),
            stderr="",
        ),
    )

    marker = arc_repl_intercepts.run_exec_compare_intercept(
        cwd,
        {
            "ok": True,
            "game_id": "ls20",
            "current_level": 1,
            "levels_completed": 0,
            "levels_gained_in_call": 0,
            "steps_executed": 1,
            "state": "NOT_FINISHED",
        },
    )

    assert marker is None


def test_run_exec_compare_intercept_keeps_level_current_surface_frontier_during_wrapup(
    monkeypatch, tmp_path: Path
) -> None:
    cwd = tmp_path / "agent"
    cwd.mkdir(parents=True, exist_ok=True)
    (cwd / "model.py").write_text("# model\n", encoding="utf-8")
    (cwd / "analysis_state.json").write_text(
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
    level_current_compare = cwd / "level_current" / "sequence_compare"
    level_current_compare.mkdir(parents=True, exist_ok=True)
    (level_current_compare / "current_compare.json").write_text(
        json.dumps({"level": 2, "status": "no_sequences_yet"}, indent=2) + "\n",
        encoding="utf-8",
    )

    arc_state_dir = tmp_path / "arc"
    monkeypatch.setenv("ARC_STATE_DIR", str(arc_state_dir))

    level_dir = arc_state_dir / "game_artifacts" / "game_ls20" / "level_1" / "sequences"
    level_dir.mkdir(parents=True, exist_ok=True)
    (level_dir / "seq_0001.json").write_text(
        json.dumps(
            {
                "sequence_id": "seq_0001",
                "end_reason": "active",
                "actions": [{"levels_completed_before": 0, "levels_completed_after": 0}],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        arc_repl_compare_intercepts.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "ok": True,
                    "level": 1,
                    "all_match": False,
                    "compared_sequences": 1,
                    "diverged_sequences": 1,
                    "reports": [{"sequence_id": "seq_0001", "matched": False, "report_file": "analysis_level/sequence_compare/seq_0001.md"}],
                }
            ),
            stderr="",
        ),
    )

    marker = arc_repl_intercepts.run_exec_compare_intercept(
        cwd,
        {
            "ok": True,
            "game_id": "ls20",
            "current_level": 2,
            "levels_completed": 1,
            "steps_executed": 1,
            "levels_gained_in_call": 0,
            "state": "NOT_FINISHED",
        },
    )

    assert marker is not None
    root_compare = json.loads((cwd / "current_compare.json").read_text(encoding="utf-8"))
    visible_compare = json.loads((level_current_compare / "current_compare.json").read_text(encoding="utf-8"))
    analysis_compare = json.loads((cwd / "analysis_level" / "sequence_compare" / "current_compare.json").read_text(encoding="utf-8"))
    assert root_compare["level"] == 1
    assert analysis_compare["level"] == 1
    assert visible_compare["level"] == 2
