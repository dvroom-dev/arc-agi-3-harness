from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class FrameSnapshot:
    """Simple script-facing snapshot of the current frame/grid state."""

    grid: np.ndarray
    state: str
    current_level: int
    levels_completed: int
    win_levels: int
    guid: str | None
    available_actions: list[int]
    full_reset: bool


def build_frame_snapshot(session) -> FrameSnapshot:
    return FrameSnapshot(
        grid=np.array(session.pixels, copy=True),
        state=str(session.frame.state.value),
        current_level=int(session.frame.levels_completed) + 1,
        levels_completed=int(session.frame.levels_completed),
        win_levels=int(session.frame.win_levels),
        guid=getattr(session.frame, "guid", None),
        available_actions=[
            int(a) for a in getattr(session.frame, "available_actions", [])
        ],
        full_reset=bool(getattr(session.frame, "full_reset", False)),
    )


def install_env_compat_bindings(session) -> None:
    """Expose stable read helpers for script compatibility."""
    try:
        setattr(session.env, "read", session._state_payload)
    except Exception:
        pass
    try:
        setattr(session.env, "get_frame", lambda: build_frame_snapshot(session))
    except Exception:
        pass
