from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def build_scorecard_client(
    *,
    operation_mode_name: str,
    arc_base_url: str,
    environments_dir: Path,
):
    import arc_agi
    from arc_agi import OperationMode

    mode = OperationMode[operation_mode_name]
    return arc_agi.Arcade(
        operation_mode=mode,
        arc_base_url=arc_base_url,
        environments_dir=str(environments_dir),
    )


def open_shared_scorecard(
    *,
    args,
    game_ids: list[str],
    operation_mode_name: str,
    arc_base_url: str,
    session_base: str,
) -> tuple[Any, str, str, str]:
    if operation_mode_name != "ONLINE":
        raise RuntimeError(
            "Scorecards require ONLINE mode. Re-run with --operation-mode ONLINE."
        )
    environments_dir = Path("/tmp/arc-agi-env-cache") / f"{session_base}-scorecard"
    environments_dir.mkdir(parents=True, exist_ok=True)
    client = build_scorecard_client(
        operation_mode_name=operation_mode_name,
        arc_base_url=arc_base_url,
        environments_dir=environments_dir,
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
    # Fail fast: ensure the created scorecard is immediately retrievable
    # with the same credentials before starting expensive multi-game runs.
    client.get_scorecard(scorecard_id)
    api_url = f"{arc_base_url.rstrip('/')}/api/scorecard/{scorecard_id}"
    web_url = f"{arc_base_url.rstrip('/')}/scorecards/{scorecard_id}"
    return client, scorecard_id, api_url, web_url


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
    environments_dir = Path("/tmp/arc-agi-env-cache") / f"{session_base}-owner-check"
    environments_dir.mkdir(parents=True, exist_ok=True)
    client = build_scorecard_client(
        operation_mode_name=operation_mode_name,
        arc_base_url=arc_base_url,
        environments_dir=environments_dir,
    )
    try:
        client.get_scorecard(owner_check_id)
    except Exception as exc:
        raise RuntimeError(
            "Scorecard owner check failed: this ARC_API_KEY cannot read "
            f"--scorecard-owner-check-id={owner_check_id}. "
            "Refusing to run scored harness job to avoid publishing to the wrong account."
        ) from exc
