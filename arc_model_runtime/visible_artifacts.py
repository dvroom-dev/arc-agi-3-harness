from __future__ import annotations

import json
from pathlib import Path
from .io_utils import write_json_atomic, write_jsonl_atomic, write_text_atomic

ANALYSIS_LEVEL_STATUS_FILE = "analysis_level_status.json"
LEVEL_TRANSITION_FILE = "level_transition.json"


def visible_levels_completed_for_level(level: int) -> int:
    return max(0, int(level) - 1)


def _read_json_if_exists(path: Path) -> dict | list | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
    except Exception:
        return None
    return payload if isinstance(payload, (dict, list)) else None


def _coerce_capped_int(value: object, maximum: int) -> object:
    try:
        return min(int(value), int(maximum))
    except Exception:
        return value


def sanitize_visible_json_payload(payload: object, *, visible_level: int) -> object:
    visible_completed = visible_levels_completed_for_level(visible_level)
    if isinstance(payload, dict):
        out: dict[str, object] = {}
        for key, value in payload.items():
            if key in {"frontier_level", "source", "game_dir", "artifacts_dir", "state_file", "action_history_file"}:
                continue
            sanitized = sanitize_visible_json_payload(value, visible_level=visible_level)
            if key in {"current_level", "level_after", "compare_level", "last_compare_level"}:
                sanitized = _coerce_capped_int(sanitized, visible_level)
            elif key in {"level_before", "level"}:
                sanitized = _coerce_capped_int(sanitized, visible_level)
            elif key in {
                "levels_completed",
                "levels_before_action",
                "levels_completed_before",
                "levels_completed_after",
            }:
                sanitized = _coerce_capped_int(sanitized, visible_completed)
            elif key == "available_model_levels" and isinstance(sanitized, list):
                capped_levels: list[int] = []
                for item in sanitized:
                    try:
                        level_value = int(item)
                    except Exception:
                        continue
                    if level_value <= int(visible_level):
                        capped_levels.append(level_value)
                sanitized = capped_levels
            out[str(key)] = sanitized
        return out
    if isinstance(payload, list):
        return [sanitize_visible_json_payload(item, visible_level=visible_level) for item in payload]
    return payload


def _load_hex_rows(path: Path) -> list[str]:
    return [line.rstrip("\n").upper() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_hex_rows(path: Path, rows: list[str]) -> None:
    write_text_atomic(path, "\n".join(rows) + "\n")


def visible_level_status_payload(
    *,
    visible_level: int,
    frontier_hidden_by_pin: bool,
    pin_phase: str | None = None,
    boundary_redacted: bool = False,
    transition_redacted_paths: list[str] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "arc.analysis_level_status.v1",
        "visible_level": int(visible_level),
        "visible_levels_completed": visible_levels_completed_for_level(visible_level),
        "analysis_level_pinned": bool(frontier_hidden_by_pin),
        "frontier_hidden_by_pin": bool(frontier_hidden_by_pin),
        "boundary_redacted": bool(boundary_redacted),
        "next_allowed_operation": (
            "finalize_pinned_level" if frontier_hidden_by_pin else "continue_visible_level"
        ),
    }
    if pin_phase:
        payload["pin_phase"] = str(pin_phase)
    if transition_redacted_paths:
        payload["transition_redacted_paths"] = [str(path) for path in transition_redacted_paths]
    return payload


def level_transition_payload(
    *,
    visible_level: int,
    redacted: bool,
    source_turn_dir: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "arc.level_transition.v1",
        "visible_level": int(visible_level),
        "analysis_level_boundary_redacted": bool(redacted),
        "summary": (
            "A later frontier level exists, but level-transition details are hidden until the current analysis pin is released."
            if redacted
            else "A level transition occurred."
        ),
    }
    if source_turn_dir:
        payload["source_turn_dir"] = str(source_turn_dir)
    return payload


def _boundary_hidden(meta: dict, *, visible_level: int) -> bool:
    visible_completed = visible_levels_completed_for_level(visible_level)
    for key in ("current_level", "level_after"):
        try:
            if int(meta.get(key)) > int(visible_level):
                return True
        except Exception:
            pass
    for key in ("levels_completed", "levels_completed_after"):
        try:
            if int(meta.get(key)) > int(visible_completed):
                return True
        except Exception:
            pass
    return False


def sanitize_visible_level_tree(level_root: Path, *, visible_level: int) -> None:
    current_state_rows: list[str] | None = None
    boundary_hidden = False
    transition_redacted_paths: list[str] = []
    pin_phase: str | None = None
    pin_path = level_root.parent / ".analysis_level_pin.json"
    pin_payload = _read_json_if_exists(pin_path)
    if isinstance(pin_payload, dict):
        phase = str(pin_payload.get("phase") or "").strip()
        pin_phase = phase or None

    meta_paths = sorted(level_root.glob("turn_*/meta.json"))
    meta_paths.extend(sorted(level_root.glob("sequences/seq_*/actions/*/meta.json")))
    for meta_path in meta_paths:
        payload = _read_json_if_exists(meta_path)
        if not isinstance(payload, dict):
            continue
        if _boundary_hidden(payload, visible_level=visible_level):
            boundary_hidden = True
            step_dir = meta_path.parent
            before_path = step_dir / "before_state.hex"
            after_path = step_dir / "after_state.hex"
            rel_step_dir = str(step_dir.relative_to(level_root))
            if before_path.exists():
                before_rows = _load_hex_rows(before_path)
                if before_rows:
                    if after_path.exists():
                        _write_hex_rows(after_path, before_rows)
                    current_state_rows = before_rows
            if current_state_rows is None:
                raise RuntimeError(
                    "cross-level boundary redaction failed: missing pre-boundary state for "
                    f"{meta_path}"
                )
            payload["analysis_level_boundary_redacted"] = True
            transition_payload = level_transition_payload(
                visible_level=visible_level,
                redacted=True,
                source_turn_dir=rel_step_dir,
            )
            write_json_atomic(step_dir / LEVEL_TRANSITION_FILE, transition_payload)
            transition_redacted_paths.append(rel_step_dir)
        write_json_atomic(meta_path, sanitize_visible_json_payload(payload, visible_level=visible_level))

    for json_path in sorted(level_root.rglob("*.json")):
        if json_path.name == "meta.json" and json_path in meta_paths:
            continue
        if json_path.name in {ANALYSIS_LEVEL_STATUS_FILE, LEVEL_TRANSITION_FILE}:
            continue
        payload = _read_json_if_exists(json_path)
        if payload is None:
            continue
        write_json_atomic(json_path, sanitize_visible_json_payload(payload, visible_level=visible_level))

    for jsonl_path in sorted(level_root.rglob("*.jsonl")):
        rows: list[object] = []
        dirty = False
        for line in jsonl_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                row = json.loads(stripped)
            except Exception:
                rows.append(stripped)
                continue
            rows.append(sanitize_visible_json_payload(row, visible_level=visible_level))
            dirty = True
        if dirty:
            write_jsonl_atomic(jsonl_path, rows)

    if current_state_rows is not None:
        current_state_path = level_root / "current_state.hex"
        if current_state_path.exists():
            _write_hex_rows(current_state_path, current_state_rows)

        write_json_atomic(
            level_root / ANALYSIS_LEVEL_STATUS_FILE,
            visible_level_status_payload(
                visible_level=visible_level,
            frontier_hidden_by_pin=boundary_hidden,
            pin_phase=pin_phase,
            boundary_redacted=boundary_hidden,
            transition_redacted_paths=transition_redacted_paths or None,
        ),
    )
    if boundary_hidden:
        write_json_atomic(
            level_root / LEVEL_TRANSITION_FILE,
            level_transition_payload(visible_level=visible_level, redacted=True),
        )
