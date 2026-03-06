from __future__ import annotations

import re


def resolve_arc_base_url(args) -> str:
    if args.arc_base_url and str(args.arc_base_url).strip():
        return str(args.arc_base_url).strip()
    if args.arc_backend == "server":
        return "http://127.0.0.1:8000"
    return "https://three.arcprize.org"


def resolve_game_ids(args) -> list[str]:
    raw = str(getattr(args, "game_ids", "") or "").strip()
    if not raw:
        gid = str(args.game_id or "").strip()
        if not gid:
            raise RuntimeError("No game ID provided.")
        return [gid]
    tokens = [t.strip() for t in re.split(r"[,\s]+", raw) if t.strip()]
    if not tokens:
        raise RuntimeError("Failed to parse --game-ids (expected comma/space-separated IDs).")
    unique: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        if token in seen:
            continue
        seen.add(token)
        unique.append(token)
    return unique


def session_name_for_game(session_base: str, game_id: str, index: int) -> str:
    safe_game = re.sub(r"[^A-Za-z0-9_.-]+", "-", game_id).strip("-")
    if not safe_game:
        safe_game = f"game-{index:02d}"
    return f"{session_base}-{index:02d}-{safe_game}"
