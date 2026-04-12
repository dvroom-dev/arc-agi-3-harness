from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.arc_repl_session_sequences import sync_level_sequences


def _record(
    *,
    action_index: int,
    action_name: str,
    level_before: int,
    level_after: int,
    levels_completed_before: int,
    levels_completed_after: int,
    before_rows: list[str],
    after_rows: list[str],
    state_before: str = "NOT_FINISHED",
    state_after: str = "NOT_FINISHED",
) -> dict:
    return {
        "action_index": int(action_index),
        "recorded_at_utc": f"2026-03-19T00:00:{int(action_index):02d}Z",
        "tool_turn": int(action_index),
        "call_action": "exec",
        "step_in_call": 1,
        "action_name": str(action_name),
        "action_data": {},
        "level_before": int(level_before),
        "level_after": int(level_after),
        "levels_completed_before": int(levels_completed_before),
        "levels_completed_after": int(levels_completed_after),
        "level_complete_before": False,
        "level_complete_after": int(levels_completed_after) > int(levels_completed_before),
        "game_over_before": False,
        "game_over_after": False,
        "state_before": {"state": str(state_before), "grid_hex_rows": list(before_rows)},
        "state_after": {"state": str(state_after), "grid_hex_rows": list(after_rows)},
        "diff": {},
    }


def _session(records: list[dict]) -> SimpleNamespace:
    return SimpleNamespace(
        game_id="ls20",
        action_history=SimpleNamespace(records=list(records)),
    )


def _read_rows(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_bootstrap_initial_state(game_dir: Path, *, level: int, rows: list[str]) -> None:
    level_dir = game_dir / f"level_{int(level)}"
    level_dir.mkdir(parents=True, exist_ok=True)
    (level_dir / "initial_state.hex").write_text("\n".join(rows) + "\n", encoding="utf-8")
    (level_dir / "initial_state.meta.json").write_text(
        json.dumps(
            {
                "schema_version": "arc_repl.level_initial_state.v1",
                "game_id": "ls20",
                "level": int(level),
                "rows": len(rows),
                "cols": len(rows[0]) if rows else 0,
                "initial_state_source": "session_bootstrap_reset",
                "provisional": False,
                "reset_verified": False,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def test_sync_level_sequences_uses_level_transition_as_canonical_level_start(tmp_path: Path) -> None:
    _write_bootstrap_initial_state(tmp_path, level=1, rows=["000", "000"])
    session = _session(
        [
            _record(
                action_index=1,
                action_name="ACTION1",
                level_before=1,
                level_after=2,
                levels_completed_before=0,
                levels_completed_after=1,
                before_rows=["000", "000"],
                after_rows=["111", "111"],
            )
        ]
    )

    sync_level_sequences(session=session, game_dir=tmp_path)

    level2 = tmp_path / "level_2"
    assert _read_rows(level2 / "initial_state.hex") == ["111", "111"]
    meta = json.loads((level2 / "initial_state.meta.json").read_text(encoding="utf-8"))
    assert meta["initial_state_source"] == "level_transition_after_state"
    assert meta["source_action_index"] == 1
    assert meta["provisional"] is False
    assert meta["reset_verified"] is False


def test_sync_level_sequences_uses_reset_state_for_level_one_when_available(tmp_path: Path) -> None:
    session = _session(
        [
            _record(
                action_index=1,
                action_name="ACTION1",
                level_before=1,
                level_after=1,
                levels_completed_before=0,
                levels_completed_after=0,
                before_rows=["000", "000"],
                after_rows=["999", "999"],
            ),
            _record(
                action_index=2,
                action_name="RESET_LEVEL",
                level_before=1,
                level_after=1,
                levels_completed_before=0,
                levels_completed_after=0,
                before_rows=["999", "999"],
                after_rows=["000", "000"],
                state_before="GAME_OVER",
            ),
        ]
    )

    sync_level_sequences(session=session, game_dir=tmp_path)

    level1 = tmp_path / "level_1"
    assert _read_rows(level1 / "initial_state.hex") == ["000", "000"]
    meta = json.loads((level1 / "initial_state.meta.json").read_text(encoding="utf-8"))
    assert meta["initial_state_source"] == "reset_level_after_state"
    assert meta["source_action_index"] == 2
    assert meta["provisional"] is False
    assert meta["reset_verified"] is True


def test_sync_level_sequences_fails_loudly_when_reset_disagrees_with_transition_start(tmp_path: Path) -> None:
    _write_bootstrap_initial_state(tmp_path, level=1, rows=["000", "000"])
    session = _session(
        [
            _record(
                action_index=1,
                action_name="ACTION1",
                level_before=1,
                level_after=2,
                levels_completed_before=0,
                levels_completed_after=1,
                before_rows=["000", "000"],
                after_rows=["111", "111"],
            ),
            _record(
                action_index=2,
                action_name="RESET_LEVEL",
                level_before=2,
                level_after=2,
                levels_completed_before=1,
                levels_completed_after=1,
                before_rows=["999", "999"],
                after_rows=["222", "222"],
                state_before="GAME_OVER",
            ),
        ]
    )

    with pytest.raises(RuntimeError, match="reset state does not match canonical level start"):
        sync_level_sequences(session=session, game_dir=tmp_path)


def test_sync_level_sequences_fails_without_canonical_level_start(tmp_path: Path) -> None:
    session = _session(
        [
            _record(
                action_index=1,
                action_name="ACTION1",
                level_before=1,
                level_after=1,
                levels_completed_before=0,
                levels_completed_after=0,
                before_rows=["000", "000"],
                after_rows=["111", "111"],
            )
        ]
    )

    with pytest.raises(RuntimeError, match="missing canonical initial state for level 1"):
        sync_level_sequences(session=session, game_dir=tmp_path)


def test_sync_level_sequences_starts_a_new_sequence_after_level_completion(tmp_path: Path) -> None:
    _write_bootstrap_initial_state(tmp_path, level=1, rows=["000", "000"])
    session = _session(
        [
            _record(
                action_index=1,
                action_name="ACTION1",
                level_before=1,
                level_after=2,
                levels_completed_before=0,
                levels_completed_after=1,
                before_rows=["000", "000"],
                after_rows=["111", "111"],
            ),
            _record(
                action_index=2,
                action_name="ACTION2",
                level_before=2,
                level_after=2,
                levels_completed_before=1,
                levels_completed_after=1,
                before_rows=["111", "111"],
                after_rows=["222", "222"],
            ),
        ]
    )

    sync_level_sequences(session=session, game_dir=tmp_path)

    level1_seq = json.loads((tmp_path / "level_1" / "sequences" / "seq_0001.json").read_text(encoding="utf-8"))
    level2_seq = json.loads((tmp_path / "level_2" / "sequences" / "seq_0001.json").read_text(encoding="utf-8"))

    assert level1_seq["action_count"] == 1
    assert level1_seq["end_reason"] == "level_change"
    assert level1_seq["actions"][0]["action_index"] == 1

    assert level2_seq["action_count"] == 1
    assert level2_seq["actions"][0]["action_index"] == 2
