from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

IDLE_KEEPALIVE_INTERCEPT_MARKER = "__ARC_INTERCEPT_IDLE_KEEPALIVE__"
LEVEL_COMPLETE_MODEL_MISMATCH_MARKER = "__ARC_INTERCEPT_LEVEL_COMPLETE_MODEL_MISMATCH__"
RESET_LEVEL_INTERCEPT_MARKER = "__ARC_INTERCEPT_RESET_LEVEL__"
COMPARE_RESULTS_BEGIN_MARKER = "__ARC_COMPARE_RESULTS_BEGIN__"
COMPARE_RESULTS_END_MARKER = "__ARC_COMPARE_RESULTS_END__"
IDLE_KEEPALIVE_FLAG_REL = "intercepts/idle_keepalive.flag"


def idle_keepalive_flag_path(cwd: Path, arc_state_dir: Path) -> Path:
    arc_state_dir.mkdir(parents=True, exist_ok=True)
    return arc_state_dir / IDLE_KEEPALIVE_FLAG_REL


def consume_idle_keepalive_marker(cwd: Path, arc_state_dir: Path) -> str | None:
    path = idle_keepalive_flag_path(cwd, arc_state_dir)
    if not path.exists():
        return None
    try:
        payload = path.read_text(encoding="utf-8").strip()
    except Exception:
        payload = ""
    try:
        path.unlink()
    except Exception:
        pass
    return payload or IDLE_KEEPALIVE_INTERCEPT_MARKER


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
    return seq_files[-1].stem


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
    level_dir = cwd / f"level_{completed_level}"
    if not level_dir.exists():
        return None
    sequence_id = latest_sequence_id_for_level(level_dir)
    if not sequence_id:
        return None

    game_id = str(result.get("game_id", "") or os.getenv("ARC_ACTIVE_GAME_ID", "")).strip() or "game"
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
    mismatch = (proc.returncode != 0) or (not compare_ok) or (not all_match)
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
        compare_rel = str(compare_file.relative_to(cwd))
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
