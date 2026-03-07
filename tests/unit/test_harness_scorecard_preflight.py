from __future__ import annotations

import sys
from types import ModuleType

import harness_scorecard_helpers as helpers


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if int(self.status_code) >= 400:
            raise RuntimeError(f"http {self.status_code}")

    def json(self) -> dict:
        return dict(self._payload)


def test_scorecard_session_preflight_exercises_failure_path(monkeypatch) -> None:
    monkeypatch.setenv("ARC_API_KEY", "k-test")
    monkeypatch.setattr(helpers, "resolve_arc_api_key", lambda **_kwargs: "k-test")

    cards: dict[str, int] = {}
    guid_to_card: dict[str, str] = {}
    observed_game_ids: list[str] = []
    next_id = {"n": 0}
    next_guid = {"n": 0}

    def _new_card_id() -> str:
        next_id["n"] += 1
        return f"card-{next_id['n']}"

    def _new_guid() -> str:
        next_guid["n"] += 1
        return f"guid-{next_guid['n']}"

    class FakeSession:
        def __init__(self):
            self.headers = {}

        def post(self, url, json=None, headers=None, timeout=0):
            if url.endswith("/api/scorecard/open"):
                cid = _new_card_id()
                cards[cid] = 0
                return _FakeResponse({"card_id": cid})
            if url.endswith("/api/cmd/RESET"):
                cid = str((json or {}).get("card_id", ""))
                observed_game_ids.append(str((json or {}).get("game_id", "")))
                guid = _new_guid()
                guid_to_card[guid] = cid
                return _FakeResponse({"guid": guid})
            if url.endswith("/api/cmd/ACTION1"):
                guid = str((json or {}).get("guid", ""))
                observed_game_ids.append(str((json or {}).get("game_id", "")))
                cid = guid_to_card.get(guid, "")
                cards[cid] = int(cards.get(cid, 0)) + 1
                return _FakeResponse({"ok": True})
            if url.endswith("/api/scorecard/close"):
                return _FakeResponse({"ok": True})
            raise AssertionError(f"unexpected session.post URL: {url}")

        def get(self, url, timeout=0):
            if "/api/scorecard/" in url:
                cid = url.rsplit("/", 1)[-1]
                return _FakeResponse({"total_actions": int(cards.get(cid, 0))})
            raise AssertionError(f"unexpected session.get URL: {url}")

    # Stateless calls used by failure-path probe: never attach actions.
    def stateless_post(url, json=None, headers=None, timeout=0):
        if url.endswith("/api/cmd/RESET"):
            observed_game_ids.append(str((json or {}).get("game_id", "")))
            return _FakeResponse({"guid": _new_guid()})
        if url.endswith("/api/cmd/ACTION1"):
            observed_game_ids.append(str((json or {}).get("game_id", "")))
            return _FakeResponse({"ok": True})
        raise AssertionError(f"unexpected requests.post URL: {url}")

    fake_requests = ModuleType("requests")
    fake_requests.Session = FakeSession
    fake_requests.post = stateless_post
    monkeypatch.setitem(sys.modules, "requests", fake_requests)

    logs: list[str] = []
    helpers.run_scorecard_session_preflight(
        operation_mode_name="ONLINE",
        arc_base_url="http://example.test",
        game_id="ft09-12345678",
        log=logs.append,
    )
    assert logs
    assert "failure-path-reproduced=True" in logs[-1]
    assert observed_game_ids == ["ft09-12345678"] * 4
