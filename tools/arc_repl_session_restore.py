from __future__ import annotations


def restore_session_from_history(session, events: list[dict]) -> list[dict]:
    replayed_events: list[dict] = []
    for index, event in enumerate(events, start=1):
        kind = str(event.get("kind", "")).strip()
        if kind == "reset":
            session.frame = session.deps._reset_env_with_retry(
                session.env,
                context=f"during history replay at event {index}",
            )
            session.pixels = session.deps._get_pixels(session.env, session.frame)
            replayed_events.append(event)
            continue
        if kind == "step":
            action = session.deps._action_from_event_name(event.get("action", ""))
            data = event.get("data")
            frame = session.env.step(action, data=data, reasoning=None)
            if frame is None:
                failure = {}
                if hasattr(session.deps, "_last_step_failure_details"):
                    try:
                        failure = session.deps._last_step_failure_details(session.env)
                    except Exception:
                        failure = {}
                raise RuntimeError(
                    "failed to replay persisted ARC step event "
                    f"{index}: action={event.get('action')!r} details={failure}"
                )
            session.frame = frame
            session.pixels = session.deps._get_pixels(session.env, session.frame)
            replayed_events.append(event)
            continue
        raise RuntimeError(
            "failed to replay persisted ARC history: "
            f"unsupported event kind {kind!r} at index {index}"
        )
    return replayed_events
