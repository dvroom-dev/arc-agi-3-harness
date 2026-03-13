from __future__ import annotations

import json
from pathlib import Path


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
            if key == "changes" and isinstance(value, list):
                out["changes_redacted"] = True
                out["changed_pixels"] = out.get("changed_pixels", len(value))
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


def _write_json_atomic(path: Path, payload: object) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _write_jsonl_atomic(path: Path, rows: list[object]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    text = "".join(json.dumps(row, ensure_ascii=True) + "\n" for row in rows)
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _load_hex_rows(path: Path) -> list[str]:
    return [line.rstrip("\n").upper() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_hex_rows(path: Path, rows: list[str]) -> None:
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def _dot_diff_rows(rows: list[str]) -> list[str]:
    return ["." * len(row) for row in rows]


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

    meta_paths = sorted(level_root.glob("turn_*/meta.json"))
    meta_paths.extend(sorted(level_root.glob("sequences/seq_*/actions/*/meta.json")))
    for meta_path in meta_paths:
        payload = _read_json_if_exists(meta_path)
        if not isinstance(payload, dict):
            continue
        if _boundary_hidden(payload, visible_level=visible_level):
            step_dir = meta_path.parent
            before_path = step_dir / "before_state.hex"
            after_path = step_dir / "after_state.hex"
            diff_path = step_dir / "diff.hex"
            if before_path.exists():
                before_rows = _load_hex_rows(before_path)
                if before_rows:
                    if after_path.exists():
                        _write_hex_rows(after_path, before_rows)
                    if diff_path.exists():
                        _write_hex_rows(diff_path, _dot_diff_rows(before_rows))
                    current_state_rows = before_rows
            payload["analysis_level_boundary_redacted"] = True
        _write_json_atomic(meta_path, sanitize_visible_json_payload(payload, visible_level=visible_level))

    for json_path in sorted(level_root.rglob("*.json")):
        if json_path.name == "meta.json" and json_path in meta_paths:
            continue
        payload = _read_json_if_exists(json_path)
        if payload is None:
            continue
        _write_json_atomic(json_path, sanitize_visible_json_payload(payload, visible_level=visible_level))

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
            _write_jsonl_atomic(jsonl_path, rows)

    if current_state_rows is not None:
        current_state_path = level_root / "current_state.hex"
        if current_state_path.exists():
            _write_hex_rows(current_state_path, current_state_rows)
