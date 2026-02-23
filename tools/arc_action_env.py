from __future__ import annotations

import io
import json
import os
import re
import time
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import arc_agi
import numpy as np
from arc_agi import OperationMode
from arcengine import GameAction
from arcengine.enums import FrameDataRaw


def _resolve_environments_dir() -> Path:
    env_value = os.getenv("ARC_ENVIRONMENTS_DIR", "").strip()
    if not env_value:
        raise RuntimeError("ARC_ENVIRONMENTS_DIR is required in OFFLINE mode")
    from_env = Path(env_value).expanduser()
    if not from_env.is_dir():
        raise RuntimeError(
            f"ARC_ENVIRONMENTS_DIR does not exist or is not a directory: {from_env}"
        )
    return from_env


def _resolve_operation_mode() -> OperationMode:
    value = os.getenv("ARC_OPERATION_MODE", "NORMAL").strip().upper()
    if value in OperationMode.__members__:
        return OperationMode[value]
    raise RuntimeError(
        f"Invalid ARC_OPERATION_MODE={value!r}. "
        f"Expected one of: {', '.join(OperationMode.__members__.keys())}"
    )


def _make_id_candidates(game_id: str) -> list[str]:
    normalized = str(game_id).strip()
    if not normalized:
        return []
    out = [normalized]
    if re.fullmatch(r".+-[0-9a-f]{8}", normalized):
        base = normalized.rsplit("-", 1)[0]
        if base and base not in out:
            out.append(base)
    return out


def _call_quiet(fn, *args, **kwargs):
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        return fn(*args, **kwargs)


def _apply_scorecard_cookies_from_env(arcade) -> None:
    payload = str(os.getenv("ARC_SCORECARD_COOKIES", "") or "").strip()
    if not payload:
        return
    try:
        data = json.loads(payload)
    except Exception as exc:
        raise RuntimeError(f"invalid ARC_SCORECARD_COOKIES JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError("invalid ARC_SCORECARD_COOKIES JSON: expected object")
    try:
        import requests.utils
    except Exception as exc:
        raise RuntimeError(f"requests.utils unavailable for ARC scorecard cookies: {exc}") from exc
    session = getattr(arcade, "_session", None)
    if session is None:
        raise RuntimeError("cannot apply ARC_SCORECARD_COOKIES: Arcade client has no _session")
    existing_jar = getattr(session, "cookies", None)
    session.cookies = requests.utils.cookiejar_from_dict(
        {str(k): str(v) for k, v in data.items()},
        cookiejar=existing_jar,
        overwrite=True,
    )


def _get_pixels(env, frame: FrameDataRaw | None = None) -> np.ndarray:
    if frame is not None:
        data = getattr(frame, "frame", None)
        if isinstance(data, (list, tuple)) and data:
            pixels = data[-1]
            if isinstance(pixels, np.ndarray):
                return pixels
            return np.array(pixels)
        raise RuntimeError(
            "FrameDataRaw.frame is unavailable; cannot compute authoritative diff/state grid."
        )

    game = env._game
    return game.get_pixels(
        game.camera.x,
        game.camera.y,
        game.camera.width,
        game.camera.height,
    )


def _make_env(game_id: str):
    mode = _resolve_operation_mode()
    kwargs: dict[str, object] = {"operation_mode": mode}
    arc_base_url = str(os.getenv("ARC_BASE_URL", "") or "").strip()
    if arc_base_url:
        kwargs["arc_base_url"] = arc_base_url
    arc_api_key = str(os.getenv("ARC_API_KEY", "") or "").strip()
    if arc_api_key:
        kwargs["arc_api_key"] = arc_api_key
    env_value = os.getenv("ARC_ENVIRONMENTS_DIR", "").strip()
    if env_value:
        kwargs["environments_dir"] = str(Path(env_value).expanduser())
    elif mode == OperationMode.OFFLINE:
        kwargs["environments_dir"] = str(_resolve_environments_dir())
    arcade = arc_agi.Arcade(**kwargs)
    _apply_scorecard_cookies_from_env(arcade)
    scorecard_id = str(os.getenv("ARC_SCORECARD_ID", "") or "").strip() or None
    tried: list[str] = []
    for candidate in _make_id_candidates(game_id):
        tried.append(candidate)
        env = arcade.make(candidate, render_mode=None, scorecard_id=scorecard_id)
        if env is not None:
            return env
    raise RuntimeError(f"failed to load game: {game_id} (tried: {', '.join(tried)})")


def _action_from_event_name(name: str) -> GameAction:
    normalized = str(name).strip()
    if not normalized:
        raise RuntimeError(f"unknown action name in history: {name}")
    if hasattr(GameAction, normalized):
        return getattr(GameAction, normalized)
    upper = normalized.upper()
    if hasattr(GameAction, upper):
        return getattr(GameAction, upper)
    if re.fullmatch(r"-?\d+", normalized):
        numeric = int(normalized)
        for member in GameAction:
            try:
                if int(member.value) == numeric:
                    return member
            except Exception:
                continue
    raise RuntimeError(f"unknown action name in history: {name}")


def _replay_history(env, events: list[dict]) -> FrameDataRaw:
    def _reset_with_retry(context: str) -> FrameDataRaw:
        last_none = False
        for attempt in range(8):
            frame_obj = env.reset()
            if frame_obj is not None:
                return frame_obj
            last_none = True
            time.sleep(min(8.0, 0.25 * (2**attempt)))
        if last_none:
            raise RuntimeError(f"env.reset() returned None {context}")
        raise RuntimeError(f"env.reset() failed {context}")

    frame = _reset_with_retry("at replay start")
    terminal = str(getattr(frame, "state", "").value) in {"GAME_OVER", "WIN"}
    for event in events:
        kind = str(event.get("kind", "")).strip()
        if kind == "reset":
            try:
                frame = _reset_with_retry("during replay")
            except RuntimeError:
                break
            terminal = str(getattr(frame, "state", "").value) in {"GAME_OVER", "WIN"}
            continue
        if kind != "step":
            continue
        if terminal:
            continue
        action_name = str(event.get("action", "")).strip()
        data = event.get("data")
        try:
            result = env.step(_action_from_event_name(action_name), data=data)
        except Exception:
            break
        if result is None:
            terminal = True
            continue
        frame = result
        terminal = str(getattr(frame, "state", "").value) in {"GAME_OVER", "WIN"}
    return frame
