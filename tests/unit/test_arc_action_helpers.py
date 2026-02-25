from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import arc_action


def _frame(**overrides):
    action_id = SimpleNamespace(name="ACTION1", value=1)
    action_input = SimpleNamespace(id=action_id, data={"x": 1}, reasoning=None)
    base = dict(
        game_id="ls20",
        guid="g1",
        state=SimpleNamespace(value="NOT_FINISHED"),
        levels_completed=2,
        win_levels=7,
        available_actions=[1, 2, 3],
        full_reset=False,
        action_input=action_input,
        frame=[np.zeros((2, 2), dtype=np.int8)],
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_make_id_candidates() -> None:
    assert arc_action._make_id_candidates("ls20-cb3b57cc") == ["ls20-cb3b57cc", "ls20"]
    assert arc_action._make_id_candidates("ls20") == ["ls20"]
    assert arc_action._make_id_candidates("") == []


def test_change_helpers() -> None:
    before = np.array([[0, 1], [2, 3]], dtype=np.int8)
    after = np.array([[0, 2], [2, 3]], dtype=np.int8)
    changes = arc_action._iter_cell_changes(before, after)
    assert changes == [(0, 1, 1, 2)]
    assert arc_action._change_bbox(changes) == {
        "min_row": 0,
        "max_row": 0,
        "min_col": 1,
        "max_col": 1,
    }
    assert arc_action._change_bbox([]) is None
    assert arc_action._changes_sample(changes) == [
        {"row": 0, "col": 1, "before": "1", "after": "2"}
    ]


def test_format_diff_and_change_records() -> None:
    before = np.array([[0, 1]], dtype=np.int8)
    after = np.array([[0, 10]], dtype=np.int8)
    text = arc_action.format_diff_minimal(before, after)
    assert "(0,1): 1->A" in text
    rec = arc_action.format_change_records([{"row": 0, "col": 1, "before": "1", "after": "A"}])
    assert "(0,1): 1->A" in rec


def test_step_and_aggregate_diff_records() -> None:
    pre = np.array([[0, 0], [0, 0]], dtype=np.int8)
    s1 = np.array([[1, 0], [0, 0]], dtype=np.int8)
    s2 = np.array([[1, 2], [0, 0]], dtype=np.int8)
    step_records = arc_action.build_step_diff_records(
        pre,
        [("a1", s1), ("a2", s2)],
        step_results=[{"levels_gained_in_step": 0}, {"levels_gained_in_step": 1}],
    )
    assert step_records[0]["changed_pixels"] == 1
    assert step_records[1]["suppressed_cross_level_diff"] is True

    agg = arc_action.build_aggregate_diff_record(
        pre,
        s2,
        step_snapshots=[("a1", s1), ("a2", s2)],
        step_results=[{"levels_gained_in_step": 0}, {"levels_gained_in_step": 1}],
    )
    assert agg["suppressed_cross_level_diff"] is True
    assert agg["aggregate_baseline_step"] == 2


def test_frame_action_metadata() -> None:
    meta = arc_action.frame_action_metadata(_frame())
    assert meta["action_input_name"] == "ACTION1"
    assert meta["action_input_id"] == 1


def test_state_and_history_file_helpers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARC_STATE_DIR", str(tmp_path / "arc"))
    cwd = tmp_path / "wd"
    cwd.mkdir()

    arc_dir = arc_action._arc_dir(cwd)
    assert arc_dir.exists()

    lc = arc_action._ensure_level_completions_file(cwd)
    assert lc.exists()
    al = arc_action._ensure_play_lib_file(cwd)
    assert al.exists()

    history = {"game_id": "ls20", "events": [], "turn": 3}
    arc_action._save_history(cwd, history)
    loaded = arc_action._load_history(cwd, "ls20")
    assert loaded["turn"] == 3


def test_error_payload_without_details() -> None:
    err = arc_action._error_payload(
        action="status",
        requested_game_id="ls20",
        message="x",
    )
    assert err["ok"] is False
    assert "details" not in err["error"]


def test_completion_window_and_append_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARC_STATE_DIR", str(tmp_path / "arc"))
    path = tmp_path / "arc" / "level_completions.md"
    path.parent.mkdir(parents=True)
    path.write_text("# Level Completions\n")
    events = [
        {"kind": "step", "action": "ACTION1", "levels_completed": 0},
        {"kind": "step", "action": "ACTION2", "levels_completed": 1},
    ]
    windows = arc_action._completion_action_windows_by_level(events)
    assert windows[1] == ["ACTION1", "ACTION2"]
    arc_action._append_level_completion(
        path=path,
        completed_level=1,
        actions=windows[1],
        tool_turn=4,
        winning_script_relpath="script.py",
    )
    text = path.read_text()
    assert "## Level 1 Completion" in text
    assert arc_action._read_max_recorded_completion_level(path) == 1


def test_default_game_id_and_action_name_mapping(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARC_STATE_DIR", str(tmp_path / "arc"))
    arc_dir = tmp_path / "arc"
    arc_dir.mkdir()
    (arc_dir / "state.json").write_text(json.dumps({"game_id": "ls20-cb3b57cc"}))
    assert arc_action._default_game_id(tmp_path) == "ls20-cb3b57cc"
    assert arc_action._action_from_event_name("ACTION1").name == "ACTION1"
    assert arc_action._action_from_event_name("1").name == "ACTION1"


def test_read_args_and_error_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    stdin = io.TextIOWrapper(io.BytesIO(b'{"action":"status"}'), encoding="utf-8")
    monkeypatch.setattr(sys, "stdin", stdin)
    parsed = arc_action._read_args()
    assert parsed["action"] == "status"
    err = arc_action._error_payload(
        action="status",
        requested_game_id="ls20",
        message="x",
        details="d",
    )
    assert err["ok"] is False
    assert err["error"]["details"] == "d"


def test_write_state_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARC_STATE_DIR", str(tmp_path / "arc"))
    frame = _frame(frame=[np.zeros((64, 64), dtype=np.int8)])
    pixels = np.zeros((64, 64), dtype=np.int8)
    arc_action.write_machine_state(
        tmp_path / "arc",
        frame,
        pixels,
        game_id="ls20",
        last_action="status",
        step_snapshots=[],
    )
    arc_action.write_game_state(
        tmp_path / "arc" / "game-state.md",
        frame,
        pixels,
        game_id="ls20",
        last_action="status",
        script_output="ok",
        error="",
        step_snapshots=[],
        pre_turn_pixels=None,
        step_results=[],
    )
    assert (tmp_path / "arc" / "state.json").exists()
    assert (tmp_path / "arc" / "game-state.md").exists()
