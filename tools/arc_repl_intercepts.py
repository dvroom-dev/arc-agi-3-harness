from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import re
import subprocess
import sys
from pathlib import Path

IDLE_KEEPALIVE_INTERCEPT_MARKER = "__ARC_INTERCEPT_IDLE_KEEPALIVE__"
LEVEL_COMPLETE_MODEL_MISMATCH_MARKER = "__ARC_INTERCEPT_LEVEL_COMPLETE_MODEL_MISMATCH__"
RESET_LEVEL_INTERCEPT_MARKER = "__ARC_INTERCEPT_RESET_LEVEL__"
COMPARE_RESULTS_BEGIN_MARKER = "__ARC_COMPARE_RESULTS_BEGIN__"
COMPARE_RESULTS_END_MARKER = "__ARC_COMPARE_RESULTS_END__"
IDLE_KEEPALIVE_FLAG_REL = "intercepts/idle_keepalive.flag"
IDLE_KEEPALIVE_TRIGGER_SECONDS = 12 * 60


def idle_keepalive_flag_path(cwd: Path, arc_state_dir: Path) -> Path:
    arc_state_dir.mkdir(parents=True, exist_ok=True)
    return arc_state_dir / IDLE_KEEPALIVE_FLAG_REL


def read_idle_keepalive_marker(cwd: Path, arc_state_dir: Path) -> str | None:
    path = idle_keepalive_flag_path(cwd, arc_state_dir)
    if not path.exists():
        return None
    try:
        payload = path.read_text(encoding="utf-8").strip()
    except Exception:
        payload = ""
    return payload or IDLE_KEEPALIVE_INTERCEPT_MARKER


def clear_idle_keepalive_marker(cwd: Path, arc_state_dir: Path) -> None:
    path = idle_keepalive_flag_path(cwd, arc_state_dir)
    if not path.exists():
        return
    try:
        path.unlink()
    except Exception:
        pass


def _idle_keepalive_enabled_from_env() -> bool:
    if str(os.getenv("ARC_OPERATION_MODE", "") or "").strip().upper() != "ONLINE":
        return False
    backend = str(os.getenv("ARC_BACKEND", "") or "").strip().lower()
    if backend:
        return backend == "api"
    base_url = str(os.getenv("ARC_BASE_URL", "") or "").strip().lower()
    if not base_url:
        return False
    return "three.arcprize.org" in base_url


def _parse_iso8601_utc(value: object) -> datetime | None:
    s = str(value or "").strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _idle_seconds_from_action_history(action_history_path: Path, *, now_utc: datetime) -> int | None:
    if not action_history_path.exists():
        return None
    try:
        payload = json.loads(action_history_path.read_text())
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    records = payload.get("records")
    if not isinstance(records, list) or not records:
        return None
    for rec in reversed(records):
        if not isinstance(rec, dict):
            continue
        ts = _parse_iso8601_utc(rec.get("recorded_at_utc"))
        if ts is None:
            continue
        return max(0, int((now_utc - ts).total_seconds()))
    return None


def _current_level_from_result(result: object) -> int | None:
    if not isinstance(result, dict):
        return None
    try:
        return int(result.get("current_level"))
    except Exception:
        return None


def idle_keepalive_marker_for_call(
    *,
    cwd: Path,
    arc_state_dir: Path,
    action: str,
    result: object,
) -> str | None:
    if not _idle_keepalive_enabled_from_env():
        return None

    existing = read_idle_keepalive_marker(cwd, arc_state_dir)
    if existing:
        return existing

    if result_has_real_game_action(action, result):
        return None

    history_path: Path | None = None
    if isinstance(result, dict):
        candidate = str(result.get("action_history_file", "") or "").strip()
        if candidate:
            history_path = Path(candidate)
    if history_path is None:
        history_path = arc_state_dir / "action-history.json"

    now_utc = datetime.now(timezone.utc)
    idle_seconds = _idle_seconds_from_action_history(history_path, now_utc=now_utc)
    if idle_seconds is None or idle_seconds < IDLE_KEEPALIVE_TRIGGER_SECONDS:
        return None

    level = _current_level_from_result(result)
    level_txt = str(level) if level is not None else "NA"
    queued_at_unix = int(now_utc.timestamp())
    payload = (
        f"{IDLE_KEEPALIVE_INTERCEPT_MARKER} "
        f"idle_seconds={int(idle_seconds)} "
        f"level={level_txt} "
        f"source=tool "
        f"queued_at_unix={queued_at_unix}"
    ).strip()
    flag_path = idle_keepalive_flag_path(cwd, arc_state_dir)
    flag_path.parent.mkdir(parents=True, exist_ok=True)
    flag_path.write_text(payload + "\n", encoding="utf-8")
    return payload


def result_has_real_game_action(action: str, result: object) -> bool:
    if not isinstance(result, dict):
        return False
    action_name = str(action or "").strip().lower()
    if action_name == "reset_level":
        return bool(result.get("ok")) and not bool(result.get("reset_noop", False))
    if action_name == "exec":
        try:
            return int(result.get("steps_executed", 0) or 0) > 0
        except Exception:
            return False
    return False


def latest_sequence_id_for_level(level_dir: Path) -> str | None:
    seq_root = level_dir / "sequences"
    if not seq_root.exists():
        return None
    seq_files = sorted(seq_root.glob("seq_*.json"))
    if not seq_files:
        return None
    completion_candidate: str | None = None
    fallback_candidate: str | None = None
    for path in reversed(seq_files):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        end_reason = str(payload.get("end_reason", "")).strip().lower()
        if end_reason == "reset_level":
            continue
        actions = list(payload.get("actions", []) or [])
        if not actions:
            continue
        has_regression = False
        has_completion_transition = False
        for action in actions:
            if not isinstance(action, dict):
                continue
            try:
                before = int(action.get("levels_completed_before", 0) or 0)
                after = int(action.get("levels_completed_after", before) or before)
            except Exception:
                continue
            if after < before:
                has_regression = True
                break
            if after > before:
                has_completion_transition = True
        if has_regression:
            continue
        seq_id = str(payload.get("sequence_id", path.stem)).strip() or path.stem
        if has_completion_transition:
            completion_candidate = seq_id
            break
        if fallback_candidate is None:
            fallback_candidate = seq_id
    return completion_candidate or fallback_candidate


def _safe_slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip()).strip("._") or "game"


def _artifacts_game_dir(*, cwd: Path, game_id: str) -> Path:
    state_dir = str(os.getenv("ARC_STATE_DIR", "") or "").strip()
    if not state_dir:
        return cwd
    return Path(state_dir).expanduser() / "game_artifacts" / f"game_{_safe_slug(game_id)}"


def run_level_completion_compare(cwd: Path, result: object) -> str | None:
    if not isinstance(result, dict):
        return None
    if not bool(result.get("ok")):
        return None
    if str(result.get("state", "")).strip().upper() == "WIN":
        return None
    try:
        levels_gained = int(result.get("levels_gained_in_call", 0) or 0)
    except Exception:
        levels_gained = 0
    if levels_gained <= 0:
        return None
    try:
        completed_level = int(result.get("levels_completed", 0) or 0)
    except Exception:
        completed_level = 0
    if completed_level <= 0:
        return None

    model_py = cwd / "model.py"
    if not model_py.exists():
        return None
    game_id = str(result.get("game_id", "") or os.getenv("ARC_ACTIVE_GAME_ID", "")).strip() or "game"
    artifacts_dir = _artifacts_game_dir(cwd=cwd, game_id=game_id)
    level_dir = artifacts_dir / f"level_{completed_level}"
    if not level_dir.exists():
        return None
    sequence_id = latest_sequence_id_for_level(level_dir)
    if not sequence_id:
        return None

    cmd = [
        sys.executable,
        str(model_py),
        "compare_sequences",
        "--game-id",
        game_id,
        "--level",
        str(completed_level),
        "--sequence",
        sequence_id,
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        text=True,
        capture_output=True,
    )
    compare_stdout = str(proc.stdout or "")
    compare_stderr = str(proc.stderr or "")
    parsed_payload: dict | None = None
    try:
        parsed = json.loads(compare_stdout) if compare_stdout.strip() else None
        if isinstance(parsed, dict):
            parsed_payload = parsed
    except Exception:
        parsed_payload = None

    compare_ok = bool(parsed_payload.get("ok")) if isinstance(parsed_payload, dict) else False
    all_match = bool(parsed_payload.get("all_match")) if isinstance(parsed_payload, dict) else False
    compared_sequences = 0
    if isinstance(parsed_payload, dict):
        try:
            compared_sequences = int(parsed_payload.get("compared_sequences", 0) or 0)
        except Exception:
            compared_sequences = 0
    mismatch = (proc.returncode != 0) or (not compare_ok) or (not all_match) or (compared_sequences <= 0)
    if not mismatch:
        return None

    compare_file = level_dir / "compare_results.md"
    compare_file.parent.mkdir(parents=True, exist_ok=True)
    report_lines = [
        f"# Compare Results (Level {completed_level})",
        "",
        f"- sequence_id: {sequence_id}",
        f"- command: {' '.join(cmd)}",
        f"- return_code: {int(proc.returncode)}",
        f"- compare_ok: {str(compare_ok).lower()}",
        f"- all_match: {str(all_match).lower()}",
        f"- compared_sequences: {int(compared_sequences)}",
        "",
        "## stdout",
        "```text",
        compare_stdout.rstrip(),
        "```",
        "",
        "## stderr",
        "```text",
        compare_stderr.rstrip(),
        "```",
    ]
    compare_text = "\n".join(report_lines).rstrip() + "\n"
    compare_file.write_text(compare_text, encoding="utf-8")
    try:
        compare_rel = str(compare_file.relative_to(artifacts_dir))
    except Exception:
        compare_rel = str(compare_file)
    return (
        f"# {LEVEL_COMPLETE_MODEL_MISMATCH_MARKER} level={completed_level} "
        f"sequence={sequence_id} compare_file={compare_rel}\n"
        f"# {COMPARE_RESULTS_BEGIN_MARKER}\n"
        f"{compare_text}"
        f"# {COMPARE_RESULTS_END_MARKER}\n"
    )


def reset_level_intercept_line(action: str, result: object) -> str | None:
    if str(action or "").strip().lower() != "reset_level":
        return None
    if not isinstance(result, dict):
        return f"{RESET_LEVEL_INTERCEPT_MARKER} action=reset_level ok=false"
    ok = str(bool(result.get("ok"))).lower()
    reset_noop = str(bool(result.get("reset_noop", False))).lower()
    current_level = result.get("current_level")
    levels_completed = result.get("levels_completed")
    return (
        f"{RESET_LEVEL_INTERCEPT_MARKER} action=reset_level "
        f"ok={ok} reset_noop={reset_noop} "
        f"current_level={current_level} levels_completed={levels_completed}"
    )
