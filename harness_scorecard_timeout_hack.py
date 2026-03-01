from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


# HACK(scorecard-timeout-keepalive):
# Temporary mitigation for 15-minute scorecard inactivity timeout.
# Remove this module once we have a first-class heartbeat/keepalive in the toolkit flow.
KEEPALIVE_IDLE_SECONDS = 14 * 60
KEEPALIVE_SOURCE = "harness_scorecard_timeout_keepalive_hack"


def _normalize_step_action_name(raw: Any) -> str:
    name = str(raw or "").strip().upper()
    if not name:
        return ""
    if name.startswith("ACTION"):
        return name
    if name.isdigit():
        return f"ACTION{name}"
    return name


def _agent_step_events(
    events: list[dict[str, Any]],
    *,
    min_event_index: int,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for index, event in enumerate(events):
        if index < int(min_event_index):
            continue
        if not isinstance(event, dict):
            continue
        if str(event.get("kind", "")).strip() != "step":
            continue
        if str(event.get("source", "")).strip() == KEEPALIVE_SOURCE:
            continue
        action = _normalize_step_action_name(event.get("action"))
        if not action:
            continue
        normalized = dict(event)
        normalized["action"] = action
        out.append(normalized)
    return out


def _candidate_cells(height: int, width: int) -> list[tuple[int, int]]:
    if height <= 0 or width <= 0:
        return [(0, 0)]

    seen: set[tuple[int, int]] = set()
    corners = [
        (0, 0),
        (width - 1, 0),
        (0, height - 1),
        (width - 1, height - 1),
    ]
    ordered: list[tuple[int, int]] = []
    for cell in corners:
        if cell in seen:
            continue
        seen.add(cell)
        ordered.append(cell)

    # Boundary cells, excluding corners.
    for y in range(height):
        for x in range(width):
            if (x, y) in seen:
                continue
            if x in {0, width - 1} or y in {0, height - 1}:
                seen.add((x, y))
                ordered.append((x, y))

    # Interior cells, preferring smaller distance-to-edge first.
    interior: list[tuple[int, int, int]] = []
    for y in range(1, max(1, height - 1)):
        for x in range(1, max(1, width - 1)):
            if (x, y) in seen:
                continue
            dist = min(x, y, width - 1 - x, height - 1 - y)
            interior.append((dist, y, x))
    interior.sort()
    for _, y, x in interior:
        seen.add((x, y))
        ordered.append((x, y))
    return ordered


def choose_keepalive_action(
    *,
    events: list[dict[str, Any]],
    grid_shape: tuple[int, int] | None,
    min_event_index: int,
    available_actions: list[int] | None,
) -> tuple[int, dict[str, int] | None]:
    """Pick one temporary keepalive action using agent-only history heuristics.

    Important: The returned action must be valid for the current state's
    available_actions. This avoids injecting unsupported actions.
    """
    available: set[int] = set()
    for raw in available_actions or []:
        try:
            available.add(int(raw))
        except Exception:
            continue
    if not available:
        return 0, None

    agent_steps = _agent_step_events(events, min_event_index=min_event_index)
    recent = agent_steps[-100:]
    used_action5 = any(str(step.get("action")) == "ACTION5" for step in recent)
    if 5 in available and not used_action5:
        return 5, None
    if 6 not in available:
        # Fall back to a currently supported action.
        for candidate in (1, 2, 3, 4, 5):
            if candidate in available:
                return candidate, None
        return min(available), None

    height, width = (0, 0)
    if grid_shape and len(grid_shape) == 2:
        try:
            height = int(grid_shape[0])
            width = int(grid_shape[1])
        except Exception:
            height, width = (0, 0)

    clicked: set[tuple[int, int]] = set()
    for step in recent:
        if str(step.get("action")) != "ACTION6":
            continue
        data = step.get("data")
        if not isinstance(data, dict):
            continue
        try:
            x = int(data.get("x"))
            y = int(data.get("y"))
        except Exception:
            continue
        if width > 0 and height > 0 and (x < 0 or y < 0 or x >= width or y >= height):
            continue
        clicked.add((x, y))

    candidates = _candidate_cells(height, width)
    for x, y in candidates:
        if (x, y) not in clicked:
            return 6, {"x": x, "y": y}
    return 6, {"x": 0, "y": 0}


def has_new_agent_steps(
    *,
    events: list[dict[str, Any]],
    since_event_index: int,
    agent_history_floor: int,
) -> bool:
    start = max(int(since_event_index), int(agent_history_floor), 0)
    for index in range(start, len(events)):
        event = events[index]
        if not isinstance(event, dict):
            continue
        if str(event.get("kind", "")).strip() != "step":
            continue
        if str(event.get("source", "")).strip() == KEEPALIVE_SOURCE:
            continue
        return True
    return False


def mark_last_keepalive_event(
    *,
    history_json: Path,
    action_id: int,
    data: dict[str, int] | None,
) -> bool:
    if not history_json.exists():
        return False
    try:
        payload = json.loads(history_json.read_text())
    except Exception:
        return False
    if not isinstance(payload, dict):
        return False
    events = payload.get("events")
    if not isinstance(events, list) or not events:
        return False
    expected_action = f"ACTION{int(action_id)}"

    last = events[-1]
    if not isinstance(last, dict):
        return False
    if str(last.get("kind", "")).strip() != "step":
        return False
    if _normalize_step_action_name(last.get("action")) != expected_action:
        return False
    if action_id == 6:
        if not isinstance(last.get("data"), dict):
            return False
        if not isinstance(data, dict):
            return False
        if int(last["data"].get("x", -1)) != int(data.get("x", -2)):
            return False
        if int(last["data"].get("y", -1)) != int(data.get("y", -2)):
            return False
    last["source"] = KEEPALIVE_SOURCE
    payload["events"] = events
    history_json.write_text(json.dumps(payload, indent=2) + "\n")
    return True


def maybe_inject_scorecard_keepalive_hack(
    rt,
    *,
    last_action_at_monotonic: float,
    agent_history_floor: int,
    now_monotonic: float | None = None,
) -> tuple[float, bool]:
    """Inject one keepalive env.step call if scorecard inactivity is near timeout.

    Returns:
      (updated_last_action_timestamp, injected)
    """
    if not getattr(rt, "active_scorecard_id", None):
        return last_action_at_monotonic, False

    now = time.monotonic() if now_monotonic is None else float(now_monotonic)
    if now - float(last_action_at_monotonic) < KEEPALIVE_IDLE_SECONDS:
        return last_action_at_monotonic, False

    events = rt.deps.load_history_events(rt.history_json)
    pixels = rt.load_current_pixels()
    grid_shape = None if pixels is None else tuple(pixels.shape[:2])
    state = rt.load_state() or {}
    available_actions = state.get("available_actions")
    if not isinstance(available_actions, list):
        available_actions = []
    action_id, data = choose_keepalive_action(
        events=events,
        grid_shape=grid_shape,
        min_event_index=agent_history_floor,
        available_actions=available_actions,
    )
    if action_id <= 0:
        rt.log(
            "[harness] HACK(scorecard-timeout-keepalive) skipped "
            "(no available action from current state)"
        )
        return last_action_at_monotonic, False

    if action_id == 6 and isinstance(data, dict):
        script = f"env.step(6, data={{'x': {int(data['x'])}, 'y': {int(data['y'])}}})"
    elif action_id == 5:
        script = "env.step(5)"
        data = None
    else:
        script = f"env.step({int(action_id)})"
        data = None

    _, stdout, rc = rt.run_arc_repl(
        {
            "action": "exec",
            "game_id": rt.args.game_id,
            "script": script,
        }
    )
    if rc != 0:
        detail = stdout.strip() if stdout.strip() else "no stdout"
        rt.log(
            "[harness] HACK(scorecard-timeout-keepalive) failed "
            f"rc={rc} action=ACTION{action_id} data={data}: {detail}"
        )
        return last_action_at_monotonic, False

    tagged = mark_last_keepalive_event(
        history_json=rt.history_json,
        action_id=action_id,
        data=data,
    )
    rt.log(
        "[harness] HACK(scorecard-timeout-keepalive) injected "
        f"ACTION{action_id} data={data} tagged={tagged}"
    )
    return now, True
