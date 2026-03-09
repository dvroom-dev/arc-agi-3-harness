from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable


def load_state_json(state_path: Path) -> dict[str, Any] | None:
    if not state_path.exists():
        return None
    try:
        data = json.loads(state_path.read_text())
        if not isinstance(data, dict):
            raise RuntimeError("state.json must contain a JSON object")
        return data
    except Exception as exc:
        raise RuntimeError(f"Failed to parse state JSON: {state_path}: {exc}") from exc


def load_model_status_json(model_status_path: Path) -> dict[str, Any] | None:
    if not model_status_path.exists():
        return None
    try:
        data = json.loads(model_status_path.read_text())
        if not isinstance(data, dict):
            raise RuntimeError("model_status.json must contain a JSON object")
        return data
    except Exception as exc:
        raise RuntimeError(f"Failed to parse model status JSON: {model_status_path}: {exc}") from exc


def load_history_payload(history_path: Path) -> dict[str, Any]:
    if not history_path.exists():
        return {"turn": 0, "events": []}
    try:
        data = json.loads(history_path.read_text())
    except Exception as exc:
        raise RuntimeError(
            f"Failed to parse engine history JSON: {history_path}: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise RuntimeError("tool-engine-history.json must contain a JSON object")
    return data


def load_engine_turn(history_path: Path) -> int:
    data = load_history_payload(history_path)
    turn = data.get("turn", 0)
    if not isinstance(turn, int):
        raise RuntimeError("tool-engine-history.json turn must be an integer")
    return int(turn)


def load_history_events(history_path: Path) -> list[dict[str, Any]]:
    data = load_history_payload(history_path)
    raw_events = data.get("events", [])
    if not isinstance(raw_events, list):
        raise RuntimeError("tool-engine-history.json events must be a JSON array")
    out: list[dict[str, Any]] = []
    for event in raw_events:
        if isinstance(event, dict):
            out.append(event)
    return out


def format_state_summary(state: dict[str, Any] | None, *, history_turn: int) -> str:
    if not state:
        return "State unavailable."
    telemetry = state.get("telemetry") if isinstance(state.get("telemetry"), dict) else {}
    steps_since_reset = telemetry.get("steps_since_last_reset", "n/a")
    action_input = state.get("action_input_name", "?")
    full_reset = state.get("full_reset", False)
    return (
        f"state={state.get('state','?')} level={state.get('current_level','?')} "
        f"levels={state.get('levels_completed','?')}/{state.get('win_levels','?')} "
        f"last_action={state.get('last_action','?')} "
        f"action_input={action_input} full_reset={full_reset} "
        f"tool_turn={history_turn} steps_since_last_reset={steps_since_reset}"
    )


def format_model_status_summary(model_status: dict[str, Any] | None) -> str:
    if not model_status:
        return "Model status unavailable."
    state = model_status.get("state") if isinstance(model_status.get("state"), dict) else {}
    summary = (
        f"action={model_status.get('last_action_name','?')} "
        f"ok={model_status.get('ok', False)} "
        f"exit_code={model_status.get('exit_code','?')} "
        f"state={state.get('state','?')} "
        f"level={state.get('current_level','?')} "
        f"levels={state.get('levels_completed','?')}/{state.get('win_levels','?')}"
    )
    compare = model_status.get("compare") if isinstance(model_status.get("compare"), dict) else None
    if not compare:
        return summary
    compare_summary = (
        f" compare_ok={compare.get('all_match', False)} "
        f"compared={compare.get('compared_sequences','?')} "
        f"diverged={compare.get('diverged_sequences','?')}"
    )
    first_divergence = (
        compare.get("first_divergence") if isinstance(compare.get("first_divergence"), dict) else None
    )
    if not first_divergence:
        return summary + compare_summary
    return (
        summary
        + compare_summary
        + " first_divergence="
        + f"{first_divergence.get('sequence_id','?')}@{first_divergence.get('divergence_step','?')}:"
        + f"{first_divergence.get('divergence_reason','?')}"
    )


def resolve_raw_events_path(
    *,
    run_dir: Path,
    session_file: Path,
    active_actual_conversation_id: str | None,
    active_conversation_id: str | None,
    load_conversation_id: Callable[[Path], str | None],
) -> Path | None:
    ids: list[str] = []
    if active_actual_conversation_id:
        ids.append(str(active_actual_conversation_id))
    if active_conversation_id:
        ids.append(str(active_conversation_id))
    parsed = load_conversation_id(session_file)
    if parsed:
        ids.append(str(parsed))

    ordered: list[str] = []
    seen: set[str] = set()
    for conv_id in ids:
        if conv_id in seen:
            continue
        seen.add(conv_id)
        ordered.append(conv_id)

    for conv_id in ordered:
        prefixed = conv_id if conv_id.startswith("conversation_") else f"conversation_{conv_id}"
        candidates = [
            run_dir / ".ai-supervisor" / "conversations" / prefixed / "raw_events" / "events.ndjson",
            run_dir / ".ai-supervisor" / "conversations" / conv_id / "raw_events" / "events.ndjson",
        ]
        for path in candidates:
            if path.exists():
                return path
    return None


def monitor_snapshot(
    *,
    state_path: Path,
    history_path: Path,
    model_status_path: Path,
    run_dir: Path,
    session_file: Path,
    active_actual_conversation_id: str | None,
    active_conversation_id: str | None,
    load_conversation_id: Callable[[Path], str | None],
) -> dict[str, Any]:
    state = load_state_json(state_path)
    model_status = load_model_status_json(model_status_path)
    history_events = load_history_events(history_path)
    history_turn = load_engine_turn(history_path)
    raw_events_path = resolve_raw_events_path(
        run_dir=run_dir,
        session_file=session_file,
        active_actual_conversation_id=active_actual_conversation_id,
        active_conversation_id=active_conversation_id,
        load_conversation_id=load_conversation_id,
    )
    raw_events_exists = bool(raw_events_path and raw_events_path.exists())
    raw_events_size = int(raw_events_path.stat().st_size) if raw_events_exists else 0
    return {
        "state": state,
        "history_turn": history_turn,
        "history_events_len": len(history_events),
        "model_status": model_status,
        "model_status_exists": bool(model_status_path.exists()),
        "model_status_path": str(model_status_path),
        "raw_events_path": str(raw_events_path) if raw_events_path else None,
        "raw_events_exists": raw_events_exists,
        "raw_events_size_bytes": raw_events_size,
        "state_path": str(state_path),
        "history_path": str(history_path),
        "session_path": str(session_file),
    }
