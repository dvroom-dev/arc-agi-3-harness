from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
import requests.utils

import arc_repl_env


def _frame(state="NOT_FINISHED", levels_completed=0):
    return SimpleNamespace(
        state=SimpleNamespace(value=state),
        levels_completed=levels_completed,
        win_levels=7,
        frame=[np.zeros((2, 2), dtype=np.int8)],
    )


def test_resolve_operation_mode(monkeypatch) -> None:
    monkeypatch.setenv("ARC_OPERATION_MODE", "ONLINE")
    assert arc_repl_env._resolve_operation_mode().name == "ONLINE"
    monkeypatch.setenv("ARC_OPERATION_MODE", "BAD")
    with pytest.raises(RuntimeError):
        arc_repl_env._resolve_operation_mode()


def test_resolve_environments_dir(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ARC_ENVIRONMENTS_DIR", str(tmp_path))
    assert arc_repl_env._resolve_environments_dir() == tmp_path
    monkeypatch.setenv("ARC_ENVIRONMENTS_DIR", str(tmp_path / "missing"))
    with pytest.raises(RuntimeError):
        arc_repl_env._resolve_environments_dir()


def test_make_env_uses_candidates(monkeypatch) -> None:
    made = []

    class FakeArcade:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def make(self, gid, render_mode=None, scorecard_id=None):
            made.append(gid)
            if gid == "ls20":
                return object()
            return None

    monkeypatch.setenv("ARC_OPERATION_MODE", "NORMAL")
    monkeypatch.setattr(arc_repl_env.arc_agi, "Arcade", FakeArcade)
    env = arc_repl_env._make_env("ls20-cb3b57cc")
    assert env is not None
    assert made == ["ls20-cb3b57cc", "ls20"]


def test_reset_env_with_retry_eventual_success() -> None:
    class Env:
        def __init__(self):
            self.calls = 0

        def reset(self):
            self.calls += 1
            if self.calls < 3:
                return None
            return _frame()

    env = Env()
    frame = arc_repl_env._reset_env_with_retry(env, context="for test", attempts=4)
    assert frame is not None
    assert env.calls == 3


def test_reset_env_with_retry_surfaces_diagnostics() -> None:
    class Env:
        _arc_last_reset_failure = {"when": "reset", "http": {"status_code": 400}}

        def reset(self):
            return None

    env = Env()
    with pytest.raises(RuntimeError, match=r"env\.reset\(\) returned None.*diagnostics="):
        arc_repl_env._reset_env_with_retry(env, context="for test", attempts=2)


def test_make_env_applies_scorecard_cookies(monkeypatch) -> None:
    created = []

    class FakeArcade:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self._session = SimpleNamespace(cookies=requests.utils.cookiejar_from_dict({}))
            created.append(self)

        def make(self, gid, render_mode=None, scorecard_id=None):
            assert scorecard_id == "sc-123"
            return object()

    monkeypatch.setenv("ARC_OPERATION_MODE", "NORMAL")
    monkeypatch.setenv("ARC_SCORECARD_ID", "sc-123")
    monkeypatch.setenv("ARC_SCORECARD_COOKIES", '{"GAMESESSION":"cookie-123"}')
    monkeypatch.setattr(arc_repl_env.arc_agi, "Arcade", FakeArcade)
    _ = arc_repl_env._make_env("ls20")
    assert created
    cookies = requests.utils.dict_from_cookiejar(created[0]._session.cookies)
    assert cookies.get("GAMESESSION") == "cookie-123"


def test_get_pixels_uses_frame_data() -> None:
    frame = _frame()
    pixels = arc_repl_env._get_pixels(None, frame)
    assert pixels.shape == (2, 2)


def test_get_pixels_returns_owned_copy_from_frame() -> None:
    source = np.array([[1, 2], [3, 4]], dtype=np.int8)
    frame = SimpleNamespace(frame=[source])
    pixels = arc_repl_env._get_pixels(None, frame)
    assert pixels.shape == (2, 2)
    assert np.array_equal(pixels, source)
    assert not np.shares_memory(pixels, source)
    source[0, 0] = 9
    assert int(pixels[0, 0]) == 1
