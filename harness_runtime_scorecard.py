from __future__ import annotations

import json
from datetime import datetime, timezone

from harness_scorecard_helpers import export_scorecard_cookies_json


def open_scorecard_now_impl(rt) -> str:
    """Open and bind a new scorecard for the active game mid-run."""
    if rt.active_scorecard_id:
        return rt.active_scorecard_id
    if rt.operation_mode_name != "ONLINE":
        raise RuntimeError("score-after-solve requires ONLINE mode for scorecards.")
    if not rt.arc_api_key:
        raise RuntimeError("ARC_API_KEY is required to open a scorecard.")

    rt.scorecard_client = rt._build_scorecard_client()
    tags = [
        "arc-agi-harness",
        "tool-driven",
        f"game:{rt.args.game_id}",
        "score-after-solve",
    ]
    opaque = {
        "session_name": rt.session_name,
        "game_id": str(rt.args.game_id),
        "phase": "score-after-solve-replay",
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    rt.active_scorecard_id = str(rt.scorecard_client.open_scorecard(tags=tags, opaque=opaque))
    rt.scorecard_created_here = True
    rt.scorecard_cookies_json = export_scorecard_cookies_json(rt.scorecard_client)
    rt.scorecard_api_url = f"{rt.arc_base_url.rstrip('/')}/api/scorecard/{rt.active_scorecard_id}"
    rt.scorecard_web_url = f"{rt.arc_base_url.rstrip('/')}/scorecards/{rt.active_scorecard_id}"

    rt.super_env["ARC_SCORECARD_ID"] = rt.active_scorecard_id
    if rt.scorecard_cookies_json:
        rt.super_env["ARC_SCORECARD_COOKIES"] = rt.scorecard_cookies_json
    else:
        rt.super_env.pop("ARC_SCORECARD_COOKIES", None)

    rt.scorecard_meta_path.write_text(
        json.dumps(
            {
                "scorecard_id": rt.active_scorecard_id,
                "api_url": rt.scorecard_api_url,
                "web_url": rt.scorecard_web_url,
                "created_here": True,
                "opened_mid_run": True,
                "operation_mode": rt.operation_mode_name,
                "arc_base_url": rt.arc_base_url,
                "api_key_prefix": rt.arc_api_key_prefix,
                "scorecard_cookies_present": bool(rt.scorecard_cookies_json),
            },
            indent=2,
        )
        + "\n"
    )
    return rt.active_scorecard_id
