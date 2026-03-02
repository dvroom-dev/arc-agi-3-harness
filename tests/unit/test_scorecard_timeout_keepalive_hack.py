from __future__ import annotations

from argparse import Namespace

from harness_scorecard_timeout_hack import (
    KEEPALIVE_IDLE_SECONDS,
    maybe_inject_scorecard_keepalive_hack,
)


# HACK TESTS:
# These tests intentionally cover temporary scorecard-timeout keepalive behavior.
# Remove this file when the timeout hack is replaced by a proper heartbeat mechanism.


class _FakeResponse:
    def __init__(self, *, body: dict | None = None, should_raise: bool = False) -> None:
        self._body = body or {}
        self._should_raise = should_raise

    def raise_for_status(self) -> None:
        if self._should_raise:
            raise RuntimeError("http error")

    def json(self) -> dict:
        return dict(self._body)


class _FakeSession:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response
        self.calls: list[dict] = []

    def post(self, url: str, *, json=None, headers=None, timeout=None):
        self.calls.append(
            {
                "url": url,
                "json": dict(json or {}),
                "headers": dict(headers or {}),
                "timeout": timeout,
            }
        )
        return self._response


class _FakeScorecardClient:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session


class _FakeRuntime:
    def __init__(self, *, response: _FakeResponse) -> None:
        self.active_scorecard_id = "sc-1"
        self.active_game_id = "ls20-cb3b57cc"
        self.args = Namespace(game_id="ls20-cb3b57cc")
        self.arc_api_key = "k-test"
        self.arc_base_url = "https://three.arcprize.org"
        self.scorecard_client = _FakeScorecardClient(_FakeSession(response))
        self.scorecard_keepalive_guid: str | None = None
        self.logs: list[str] = []

    def log(self, msg: str) -> None:
        self.logs.append(msg)


def test_timeout_hack_does_not_inject_when_not_idle() -> None:
    rt = _FakeRuntime(response=_FakeResponse(body={"guid": "g-1"}))
    ts, injected = maybe_inject_scorecard_keepalive_hack(
        rt,
        last_action_at_monotonic=100.0,
        agent_history_floor=0,
        now_monotonic=100.0 + KEEPALIVE_IDLE_SECONDS - 1.0,
    )
    assert injected is False
    assert ts == 100.0
    assert rt.scorecard_client._session.calls == []


def test_timeout_hack_posts_reset_without_guid_on_first_injection() -> None:
    rt = _FakeRuntime(response=_FakeResponse(body={"guid": "g-keepalive"}))
    ts, injected = maybe_inject_scorecard_keepalive_hack(
        rt,
        last_action_at_monotonic=0.0,
        agent_history_floor=0,
        now_monotonic=KEEPALIVE_IDLE_SECONDS + 1.0,
    )
    assert injected is True
    assert ts == KEEPALIVE_IDLE_SECONDS + 1.0
    assert len(rt.scorecard_client._session.calls) == 1
    call = rt.scorecard_client._session.calls[0]
    assert call["url"] == "https://three.arcprize.org/api/cmd/RESET"
    assert call["json"] == {
        "card_id": "sc-1",
        "game_id": "ls20-cb3b57cc",
    }
    assert "guid" not in call["json"]
    assert rt.scorecard_keepalive_guid == "g-keepalive"
    assert any("RESET(heartbeat-guid) guid=g-keepalive" in msg for msg in rt.logs)


def test_timeout_hack_reuses_heartbeat_guid_after_bootstrap() -> None:
    rt = _FakeRuntime(response=_FakeResponse(body={"guid": "g-keepalive"}))
    rt.scorecard_keepalive_guid = "g-keepalive"
    ts, injected = maybe_inject_scorecard_keepalive_hack(
        rt,
        last_action_at_monotonic=0.0,
        agent_history_floor=0,
        now_monotonic=KEEPALIVE_IDLE_SECONDS + 1.0,
    )
    assert injected is True
    assert ts == KEEPALIVE_IDLE_SECONDS + 1.0
    assert len(rt.scorecard_client._session.calls) == 1
    call = rt.scorecard_client._session.calls[0]
    assert call["json"] == {
        "card_id": "sc-1",
        "game_id": "ls20-cb3b57cc",
        "guid": "g-keepalive",
    }
    assert rt.scorecard_keepalive_guid == "g-keepalive"


def test_timeout_hack_logs_failure_and_does_not_advance_timer() -> None:
    rt = _FakeRuntime(response=_FakeResponse(should_raise=True))
    ts, injected = maybe_inject_scorecard_keepalive_hack(
        rt,
        last_action_at_monotonic=0.0,
        agent_history_floor=0,
        now_monotonic=KEEPALIVE_IDLE_SECONDS + 1.0,
    )
    assert injected is False
    assert ts == 0.0
    assert any("HACK(scorecard-timeout-keepalive) failed" in msg for msg in rt.logs)


def test_timeout_hack_skips_when_scorecard_not_active() -> None:
    rt = _FakeRuntime(response=_FakeResponse(body={"guid": "unused"}))
    rt.active_scorecard_id = None
    ts, injected = maybe_inject_scorecard_keepalive_hack(
        rt,
        last_action_at_monotonic=0.0,
        agent_history_floor=0,
        now_monotonic=KEEPALIVE_IDLE_SECONDS + 1.0,
    )
    assert injected is False
    assert ts == 0.0
    assert rt.scorecard_client._session.calls == []
