from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

try:
    from arc_repl_session_grid import _same_game_lineage
except Exception:
    from tools.arc_repl_session_grid import _same_game_lineage


class ActionHistoryStore:
    def __init__(
        self,
        *,
        path: Path,
        game_id: str,
        make_id_candidates,
    ) -> None:
        self.path = path
        self.game_id = str(game_id).strip()
        self.make_id_candidates = make_id_candidates
        self.records = self._load_records()
        self.next_action_index = (
            max((int(r.get("action_index", 0)) for r in self.records), default=0) + 1
        )

    def _load_records(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text())
        except Exception as exc:
            raise RuntimeError(
                f"failed to parse action history file {self.path}: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise RuntimeError(
                f"invalid action history file {self.path}: expected JSON object"
            )
        history_game_id = str(payload.get("game_id", "")).strip()
        if history_game_id and not _same_game_lineage(
            self.game_id,
            history_game_id,
            self.make_id_candidates,
        ):
            return []
        records = payload.get("records", [])
        if not isinstance(records, list):
            raise RuntimeError(
                f"invalid action history file {self.path}: records must be a list"
            )
        out: list[dict] = []
        for rec in records:
            if isinstance(rec, dict):
                out.append(rec)
        return out

    def _save(self) -> None:
        payload = {
            "schema_version": "arc_repl.action_history.v1",
            "game_id": self.game_id,
            "records": self.records,
            "next_action_index": self.next_action_index,
        }
        self.path.write_text(json.dumps(payload, indent=2))

    def append(
        self,
        *,
        call_action: str,
        action_name: str,
        action_data: Any,
        source: str | None,
        tool_turn: int,
        step_in_call: int,
        state_before: dict,
        state_after: dict,
        diff_payload: dict,
        frame_sequence_rows: list[list[str]] | None = None,
    ) -> None:
        state_before_name = str(state_before.get("state", "")).strip().upper()
        state_after_name = str(state_after.get("state", "")).strip().upper()
        level_complete_before = bool(state_before.get("level_complete", False)) or state_before_name == "WIN"
        level_complete_after = (
            bool(state_after.get("level_complete", False))
            or state_after_name == "WIN"
            or int(state_before["levels_completed"]) < int(state_after["levels_completed"])
        )
        game_over_before = state_before_name == "GAME_OVER"
        game_over_after = state_after_name == "GAME_OVER"
        levels_changed = int(state_before["levels_completed"]) != int(
            state_after["levels_completed"]
        )
        if levels_changed:
            final_diff_payload: dict[str, Any] = {
                "suppressed_cross_level_diff": True,
                "reason": "level_transition",
                "changes": [],
                "changed_pixels": None,
                "bbox": None,
                "before": None,
                "after": None,
            }
        else:
            final_diff_payload = deepcopy(diff_payload)
        record = {
            "action_index": int(self.next_action_index),
            "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
            "tool_turn": int(tool_turn),
            "call_action": str(call_action),
            "step_in_call": int(step_in_call),
            "action_name": str(action_name),
            "action_data": action_data if isinstance(action_data, dict) else action_data,
            "source": source or None,
            "level_before": int(state_before["current_level"]),
            "level_after": int(state_after["current_level"]),
            "levels_completed_before": int(state_before["levels_completed"]),
            "levels_completed_after": int(state_after["levels_completed"]),
            "level_complete_before": bool(level_complete_before),
            "level_complete_after": bool(level_complete_after),
            "game_over_before": bool(game_over_before),
            "game_over_after": bool(game_over_after),
            "state_before": deepcopy(state_before),
            "state_after": deepcopy(state_after),
            "diff": final_diff_payload,
        }
        if isinstance(frame_sequence_rows, list):
            record["frame_sequence_rows"] = deepcopy(frame_sequence_rows)
        self.records.append(record)
        self.next_action_index += 1
        self._save()

    def get_record(self, action_index: int) -> dict | None:
        try:
            target = int(action_index)
        except Exception:
            raise RuntimeError(f"action_index must be int, got {action_index!r}")
        for rec in self.records:
            try:
                if int(rec.get("action_index", -1)) == target:
                    return deepcopy(rec)
            except Exception:
                continue
        return None

    def get_history(
        self,
        *,
        level: int | None = None,
        action_name: str | None = None,
        since: int | None = None,
        until: int | None = None,
        last: int | None = None,
    ) -> list[dict]:
        items = self.records
        if level is not None:
            lvl = int(level)
            items = [
                r
                for r in items
                if int(r.get("level_before", -1)) == lvl
                or int(r.get("level_after", -1)) == lvl
            ]
        if action_name:
            needle = str(action_name).strip().upper()
            items = [
                r
                for r in items
                if str(r.get("action_name", "")).strip().upper() == needle
            ]
        if since is not None:
            s = int(since)
            items = [r for r in items if int(r.get("action_index", 0)) >= s]
        if until is not None:
            u = int(until)
            items = [r for r in items if int(r.get("action_index", 0)) <= u]
        if last is not None:
            n = max(0, int(last))
            if n:
                items = items[-n:]
            else:
                items = []
        return deepcopy(items)
