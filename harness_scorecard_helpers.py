from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _read_arc_api_key_from_env_file(path: Path) -> str:
    try:
        text = path.read_text()
    except Exception:
        return ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if not line.startswith("ARC_API_KEY="):
            continue
        value = line.split("=", 1)[1].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        return value.strip()
    return ""


def resolve_arc_api_key(*, required: bool = False, context: str = "scorecard operations") -> str:
    key = str(os.getenv("ARC_API_KEY", "") or "").strip()
    if not key:
        candidates = [
            Path.cwd() / ".env",
            Path(__file__).resolve().parent / ".env",
        ]
        seen: set[Path] = set()
        for candidate in candidates:
            try:
                resolved = candidate.resolve()
            except Exception:
                resolved = candidate
            if resolved in seen:
                continue
            seen.add(resolved)
            key = _read_arc_api_key_from_env_file(candidate)
            if key:
                break
    if required and not key:
        raise RuntimeError(
            "ARC_API_KEY is required for "
            f"{context}. Refusing to run with an anonymous key."
        )
    return key


def build_scorecard_client(
    *,
    operation_mode_name: str,
    arc_base_url: str,
    environments_dir: Path,
    arc_api_key: str,
    scorecard_cookies_json: str | None = None,
):
    import arc_agi
    from arc_agi import OperationMode

    mode = OperationMode[operation_mode_name]
    client = arc_agi.Arcade(
        operation_mode=mode,
        arc_base_url=arc_base_url,
        environments_dir=str(environments_dir),
        arc_api_key=arc_api_key,
    )
    apply_scorecard_cookies_json(client, scorecard_cookies_json)
    return client


def export_scorecard_cookies_json(client: Any) -> str | None:
    try:
        import requests.utils
    except Exception:
        return None
    session = getattr(client, "_session", None)
    if session is None:
        return None
    jar = getattr(session, "cookies", None)
    if jar is None:
        return None
    cookies = requests.utils.dict_from_cookiejar(jar)
    if not cookies:
        return None
    return json.dumps(cookies, separators=(",", ":"), sort_keys=True)


def apply_scorecard_cookies_json(client: Any, scorecard_cookies_json: str | None) -> None:
    payload = str(scorecard_cookies_json or "").strip()
    if not payload:
        return
    try:
        data = json.loads(payload)
    except Exception as exc:
        raise RuntimeError(f"invalid ARC scorecard cookie payload: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError("invalid ARC scorecard cookie payload: expected object")
    try:
        import requests.utils
    except Exception as exc:
        raise RuntimeError(f"requests.utils unavailable for cookie restore: {exc}") from exc
    session = getattr(client, "_session", None)
    if session is None:
        raise RuntimeError("cannot apply ARC scorecard cookies: client has no _session")
    existing_jar = getattr(session, "cookies", None)
    cookie_dict = {str(k): str(v) for k, v in data.items()}
    session.cookies = requests.utils.cookiejar_from_dict(
        cookie_dict,
        cookiejar=existing_jar,
        overwrite=True,
    )


def open_shared_scorecard(
    *,
    args,
    game_ids: list[str],
    operation_mode_name: str,
    arc_base_url: str,
    session_base: str,
) -> tuple[Any, str, str, str, str | None]:
    if operation_mode_name != "ONLINE":
        raise RuntimeError(
            "Scorecards require ONLINE mode. Re-run with --operation-mode ONLINE."
        )
    arc_api_key = resolve_arc_api_key(required=True, context="opening scorecards")
    environments_dir = Path("/tmp/arc-agi-env-cache") / f"{session_base}-scorecard"
    environments_dir.mkdir(parents=True, exist_ok=True)
    client = build_scorecard_client(
        operation_mode_name=operation_mode_name,
        arc_base_url=arc_base_url,
        environments_dir=environments_dir,
        arc_api_key=arc_api_key,
    )
    tags = [
        "arc-agi-harness",
        "tool-driven",
        "multi-game-batch",
    ]
    for gid in game_ids:
        tags.append(f"game:{gid}")
    opaque = {
        "session_name": session_base,
        "game_ids": game_ids,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    scorecard_id = str(client.open_scorecard(tags=tags, opaque=opaque))
    # Fail fast if the scorecard cannot be read shortly after open.
    # Do not proceed with scored runs under uncertain publication state.
    deadline = time.monotonic() + 30.0
    last_exc: Exception | None = None
    while time.monotonic() < deadline:
        try:
            client.get_scorecard(scorecard_id)
            last_exc = None
            break
        except Exception as exc:  # pragma: no cover - backend-dependent behavior
            last_exc = exc
            time.sleep(1.0)
    if last_exc is not None:
        raise RuntimeError(
            "Scorecard open validation failed: created card could not be read "
            f"within 30s (card_id={scorecard_id})."
        ) from last_exc
    api_url = f"{arc_base_url.rstrip('/')}/api/scorecard/{scorecard_id}"
    web_url = f"{arc_base_url.rstrip('/')}/scorecards/{scorecard_id}"
    cookies_json = export_scorecard_cookies_json(client)
    return client, scorecard_id, api_url, web_url, cookies_json


def close_shared_scorecard(*, log, client, scorecard_id: str) -> None:
    try:
        final = client.close_scorecard(scorecard_id)
        score = getattr(final, "score", None) if final is not None else None
        log(f"[harness] scorecard closed: id={scorecard_id} score={score}")
    except Exception as exc:
        log(f"[harness] WARNING: failed to close shared scorecard id={scorecard_id}: {exc}")


def validate_scorecard_owner_check(
    *,
    args,
    operation_mode_name: str,
    arc_base_url: str,
    session_base: str,
) -> None:
    owner_check_id = str(getattr(args, "scorecard_owner_check_id", "") or "").strip()
    if not owner_check_id:
        return
    if operation_mode_name != "ONLINE":
        raise RuntimeError(
            "--scorecard-owner-check-id requires ONLINE mode "
            "(scorecard APIs are online-only)."
        )
    arc_api_key = resolve_arc_api_key(required=True, context="scorecard owner checks")
    environments_dir = Path("/tmp/arc-agi-env-cache") / f"{session_base}-owner-check"
    environments_dir.mkdir(parents=True, exist_ok=True)
    client = build_scorecard_client(
        operation_mode_name=operation_mode_name,
        arc_base_url=arc_base_url,
        environments_dir=environments_dir,
        arc_api_key=arc_api_key,
    )
    try:
        client.get_scorecard(owner_check_id)
    except Exception as exc:
        raise RuntimeError(
            "Scorecard owner check failed: this ARC_API_KEY cannot read "
            f"--scorecard-owner-check-id={owner_check_id}. "
            "Refusing to run scored harness job to avoid publishing to the wrong account."
        ) from exc


def _scorecard_probe_open(
    *,
    session,
    arc_base_url: str,
    tag: str,
) -> str:
    url = f"{arc_base_url.rstrip('/')}/api/scorecard/open"
    payload = {"tags": [tag, "agent"]}
    response = session.post(url, json=payload, timeout=10)
    response.raise_for_status()
    body = response.json()
    card_id = str(body.get("card_id", "")).strip()
    if not card_id:
        raise RuntimeError(f"scorecard preflight open returned no card_id: {body!r}")
    return card_id


def _scorecard_probe_reset_and_action(
    *,
    session,
    arc_base_url: str,
    card_id: str,
    use_session: bool,
    headers: dict[str, str],
) -> None:
    import requests

    caller = session.post if use_session else requests.post
    reset_url = f"{arc_base_url.rstrip('/')}/api/cmd/RESET"
    reset_payload = {
        "card_id": card_id,
        "game_id": "ls20-cb3b57cc",
    }
    reset_resp = caller(reset_url, json=reset_payload, headers=headers, timeout=10)
    reset_resp.raise_for_status()
    reset_body = reset_resp.json()
    guid = str(reset_body.get("guid", "")).strip()
    if not guid:
        raise RuntimeError(f"scorecard preflight reset returned no guid: {reset_body!r}")

    action_url = f"{arc_base_url.rstrip('/')}/api/cmd/ACTION1"
    action_payload = {
        "guid": guid,
        "game_id": "ls20-cb3b57cc",
    }
    action_resp = caller(action_url, json=action_payload, headers=headers, timeout=10)
    action_resp.raise_for_status()


def _scorecard_probe_total_actions(*, session, arc_base_url: str, card_id: str) -> int:
    url = f"{arc_base_url.rstrip('/')}/api/scorecard/{card_id}"
    deadline = time.monotonic() + 15.0
    last_exc: Exception | None = None
    while time.monotonic() < deadline:
        try:
            response = session.get(url, timeout=10)
            response.raise_for_status()
            body = response.json()
            return int(body.get("total_actions", 0) or 0)
        except Exception as exc:
            last_exc = exc
            time.sleep(0.5)
    if last_exc is not None:
        raise last_exc
    return 0


def _scorecard_probe_close(*, session, arc_base_url: str, card_id: str) -> None:
    url = f"{arc_base_url.rstrip('/')}/api/scorecard/close"
    response = session.post(url, json={"card_id": card_id}, timeout=10)
    response.raise_for_status()


def run_scorecard_session_preflight(
    *,
    operation_mode_name: str,
    arc_base_url: str,
    log,
) -> None:
    if operation_mode_name != "ONLINE":
        return
    arc_api_key = resolve_arc_api_key(
        required=True,
        context="scorecard preflight checks",
    )
    try:
        import requests
    except Exception as exc:
        raise RuntimeError(f"scorecard preflight requires requests: {exc}") from exc

    headers = {
        "X-API-Key": arc_api_key,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    session = requests.Session()
    session.headers.update(headers)

    # Positive path: open + cmd calls + get all in one cookie-bound session.
    pos_id = _scorecard_probe_open(
        session=session,
        arc_base_url=arc_base_url,
        tag="diag-scorecard-preflight-pos",
    )
    try:
        _scorecard_probe_reset_and_action(
            session=session,
            arc_base_url=arc_base_url,
            card_id=pos_id,
            use_session=True,
            headers=headers,
        )
        pos_actions = _scorecard_probe_total_actions(
            session=session,
            arc_base_url=arc_base_url,
            card_id=pos_id,
        )
        if pos_actions < 1:
            raise RuntimeError(
                "scorecard preflight failed: positive-path actions did not attach "
                f"(card_id={pos_id}, total_actions={pos_actions})"
            )
    finally:
        try:
            _scorecard_probe_close(
                session=session,
                arc_base_url=arc_base_url,
                card_id=pos_id,
            )
        except Exception:
            pass

    # Failure path exercise: open in sticky session, then call cmd endpoints
    # statelessly (no shared cookie jar). Historically this drops score updates.
    neg_id = _scorecard_probe_open(
        session=session,
        arc_base_url=arc_base_url,
        tag="diag-scorecard-preflight-neg",
    )
    failure_path_reproduced = False
    try:
        _scorecard_probe_reset_and_action(
            session=session,
            arc_base_url=arc_base_url,
            card_id=neg_id,
            use_session=False,
            headers=headers,
        )
        neg_actions = _scorecard_probe_total_actions(
            session=session,
            arc_base_url=arc_base_url,
            card_id=neg_id,
        )
        failure_path_reproduced = neg_actions == 0
    finally:
        try:
            _scorecard_probe_close(
                session=session,
                arc_base_url=arc_base_url,
                card_id=neg_id,
            )
        except Exception:
            pass
    log(
        "[harness] scorecard preflight passed: "
        f"positive-path attached actions; failure-path-reproduced={failure_path_reproduced}"
    )
