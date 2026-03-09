from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import arc_repl_compare_intercepts
import arc_repl_intercepts
from arc_model_runtime import intercepts as model_intercepts


def _write_action_history(path: Path, *, recorded_at_utc: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "arc_repl.action_history.v1",
        "game_id": "ls20",
        "records": [
            {
                "action_index": 1,
                "recorded_at_utc": recorded_at_utc,
                "action_name": "ACTION1",
            }
        ],
        "next_action_index": 2,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_arc_repl_idle_marker_is_sticky_and_cleared(monkeypatch, tmp_path: Path) -> None:
    arc_state_dir = tmp_path / "arc"
    marker_path = arc_state_dir / "intercepts" / "idle_keepalive.flag"
    action_history = arc_state_dir / "action-history.json"
    old_ts = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
    _write_action_history(action_history, recorded_at_utc=old_ts)

    monkeypatch.setenv("ARC_OPERATION_MODE", "ONLINE")
    monkeypatch.setenv("ARC_BACKEND", "api")
    monkeypatch.setenv("ARC_BASE_URL", "https://three.arcprize.org")

    result = {
        "ok": True,
        "action": "status",
        "current_level": 2,
        "action_history_file": str(action_history),
    }
    marker = arc_repl_intercepts.idle_keepalive_marker_for_call(
        cwd=tmp_path,
        arc_state_dir=arc_state_dir,
        action="status",
        result=result,
    )
    assert marker is not None
    assert "__ARC_INTERCEPT_IDLE_KEEPALIVE__" in marker
    assert "source=tool" in marker
    assert marker_path.exists()

    marker_again = arc_repl_intercepts.idle_keepalive_marker_for_call(
        cwd=tmp_path,
        arc_state_dir=arc_state_dir,
        action="status",
        result=result,
    )
    assert marker_again == marker
    assert arc_repl_intercepts.read_idle_keepalive_marker(tmp_path, arc_state_dir) == marker
    assert arc_repl_intercepts.read_idle_keepalive_marker(tmp_path, arc_state_dir) == marker

    arc_repl_intercepts.clear_idle_keepalive_marker(tmp_path, arc_state_dir)
    assert arc_repl_intercepts.read_idle_keepalive_marker(tmp_path, arc_state_dir) is None


def test_arc_repl_idle_marker_disabled_outside_online_api(monkeypatch, tmp_path: Path) -> None:
    arc_state_dir = tmp_path / "arc"
    action_history = arc_state_dir / "action-history.json"
    old_ts = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
    _write_action_history(action_history, recorded_at_utc=old_ts)

    monkeypatch.setenv("ARC_OPERATION_MODE", "OFFLINE")
    monkeypatch.setenv("ARC_BACKEND", "api")
    monkeypatch.setenv("ARC_BASE_URL", "https://three.arcprize.org")

    marker = arc_repl_intercepts.idle_keepalive_marker_for_call(
        cwd=tmp_path,
        arc_state_dir=arc_state_dir,
        action="status",
        result={"current_level": 2, "action_history_file": str(action_history)},
    )
    assert marker is None


def test_arc_repl_idle_marker_enabled_without_scorecard(monkeypatch, tmp_path: Path) -> None:
    arc_state_dir = tmp_path / "arc"
    action_history = arc_state_dir / "action-history.json"
    old_ts = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
    _write_action_history(action_history, recorded_at_utc=old_ts)

    monkeypatch.setenv("ARC_OPERATION_MODE", "ONLINE")
    monkeypatch.setenv("ARC_BACKEND", "api")
    monkeypatch.delenv("ARC_SCORECARD_ID", raising=False)
    monkeypatch.setenv("ARC_BASE_URL", "https://three.arcprize.org")

    marker = arc_repl_intercepts.idle_keepalive_marker_for_call(
        cwd=tmp_path,
        arc_state_dir=arc_state_dir,
        action="status",
        result={"current_level": 2, "action_history_file": str(action_history)},
    )
    assert marker is not None
    assert "__ARC_INTERCEPT_IDLE_KEEPALIVE__" in marker


def test_model_runtime_injects_keepalive_from_same_history_signal(monkeypatch, tmp_path: Path) -> None:
    arc_state_dir = tmp_path / "arc"
    action_history = arc_state_dir / "action-history.json"
    old_ts = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
    _write_action_history(action_history, recorded_at_utc=old_ts)

    monkeypatch.setenv("ARC_STATE_DIR", str(arc_state_dir))
    monkeypatch.setenv("ARC_OPERATION_MODE", "ONLINE")
    monkeypatch.setenv("ARC_BACKEND", "api")
    monkeypatch.setenv("ARC_BASE_URL", "https://three.arcprize.org")

    payload: dict[str, object] = {"ok": True, "action": "status", "current_level": 4}
    model_intercepts.inject_idle_hint(payload, action_name="status")
    hint = str(payload.get("intercept_hint", ""))
    assert "__ARC_INTERCEPT_IDLE_KEEPALIVE__" in hint
    assert "action=status" in hint

    marker_path = arc_state_dir / "intercepts" / "idle_keepalive.flag"
    assert marker_path.exists()


def test_model_runtime_injects_compare_clean_marker(monkeypatch, tmp_path: Path) -> None:
    arc_state_dir = tmp_path / "arc"
    monkeypatch.setenv("ARC_STATE_DIR", str(arc_state_dir))
    monkeypatch.setenv("ARC_OPERATION_MODE", "OFFLINE")
    monkeypatch.delenv("ARC_BACKEND", raising=False)
    monkeypatch.delenv("ARC_SCORECARD_ID", raising=False)

    payload: dict[str, object] = {
        "ok": True,
        "action": "compare_sequences",
        "all_match": True,
    }
    model_intercepts.inject_idle_hint(payload, action_name="compare_sequences")
    hint = str(payload.get("intercept_hint", ""))
    hints = payload.get("intercept_hints")

    assert "__ARC_INTERCEPT_COMPARE_CLEAN__" in hint
    assert isinstance(hints, list)
    assert "__ARC_INTERCEPT_COMPARE_CLEAN__" in hints


def test_latest_sequence_id_for_level_skips_reset_and_regression(tmp_path: Path) -> None:
    level_dir = tmp_path / "level_3"
    seq_root = level_dir / "sequences"
    seq_root.mkdir(parents=True, exist_ok=True)

    (seq_root / "seq_0001.json").write_text(
        json.dumps(
            {
                "sequence_id": "seq_0001",
                "end_reason": "reset_level",
                "actions": [
                    {
                        "levels_completed_before": 2,
                        "levels_completed_after": 2,
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (seq_root / "seq_0002.json").write_text(
        json.dumps(
            {
                "sequence_id": "seq_0002",
                "end_reason": "level_change",
                "actions": [
                    {
                        "levels_completed_before": 2,
                        "levels_completed_after": 1,
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (seq_root / "seq_0003.json").write_text(
        json.dumps(
            {
                "sequence_id": "seq_0003",
                "end_reason": "level_change",
                "actions": [
                    {
                        "levels_completed_before": 2,
                        "levels_completed_after": 3,
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    assert arc_repl_intercepts.latest_sequence_id_for_level(level_dir) == "seq_0003"


def test_latest_sequence_id_for_level_returns_none_when_no_eligible(tmp_path: Path) -> None:
    level_dir = tmp_path / "level_4"
    seq_root = level_dir / "sequences"
    seq_root.mkdir(parents=True, exist_ok=True)
    (seq_root / "seq_0001.json").write_text(
        json.dumps(
            {
                "sequence_id": "seq_0001",
                "end_reason": "reset_level",
                "actions": [
                    {
                        "levels_completed_before": 3,
                        "levels_completed_after": 3,
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    assert arc_repl_intercepts.latest_sequence_id_for_level(level_dir) is None


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
