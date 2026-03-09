from __future__ import annotations

import json
from pathlib import Path

from harness_runtime_monitor import format_model_status_summary, monitor_snapshot


def test_monitor_snapshot_keeps_real_and_model_state_distinct(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "smoke"
    run_dir.mkdir(parents=True, exist_ok=True)
    session_file = tmp_path / ".ctxs" / "smoke" / "session.md"
    session_file.parent.mkdir(parents=True, exist_ok=True)
    session_file.write_text("---\nconversation_id: conversation_test\n---\n")
    state_path = run_dir / "supervisor" / "arc" / "state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "state": "NOT_FINISHED",
                "current_level": 1,
                "levels_completed": 0,
                "win_levels": 7,
                "last_action": "reset_level",
                "action_input_name": "ACTION1",
                "full_reset": False,
                "telemetry": {"steps_since_last_reset": 0},
            }
        )
    )
    history_path = run_dir / "supervisor" / "arc" / "tool-engine-history.json"
    history_path.write_text(json.dumps({"turn": 5, "events": []}))
    model_status_path = run_dir / "agent" / "game_ls20" / "model_status.json"
    model_status_path.parent.mkdir(parents=True, exist_ok=True)
    model_status_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "runtime": "model",
                "last_action_name": "compare_sequences",
                "ok": True,
                "exit_code": 0,
                "state": {
                    "state": "NOT_FINISHED",
                    "current_level": 2,
                    "levels_completed": 1,
                    "win_levels": 7,
                },
                "compare": {
                    "all_match": True,
                    "compared_sequences": 3,
                    "diverged_sequences": 0,
                },
            }
        )
    )
    raw_events_path = run_dir / ".ai-supervisor" / "conversations" / "conversation_test" / "raw_events" / "events.ndjson"
    raw_events_path.parent.mkdir(parents=True, exist_ok=True)
    raw_events_path.write_text('{"type":"assistant"}\n')

    snapshot = monitor_snapshot(
        state_path=state_path,
        history_path=history_path,
        model_status_path=model_status_path,
        run_dir=run_dir,
        session_file=session_file,
        active_actual_conversation_id=None,
        active_conversation_id="conversation_test",
        load_conversation_id=lambda path: "conversation_test" if Path(path) == session_file else None,
    )

    assert snapshot["state"]["current_level"] == 1
    assert snapshot["model_status"]["state"]["current_level"] == 2
    assert snapshot["history_turn"] == 5
    assert snapshot["model_status_exists"] is True
    assert snapshot["raw_events_exists"] is True
    assert "compare_ok=True" in format_model_status_summary(snapshot["model_status"])
