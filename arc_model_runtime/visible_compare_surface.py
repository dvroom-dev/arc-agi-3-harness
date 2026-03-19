from __future__ import annotations

import json
import shutil
from pathlib import Path


def overlay_latest_compare_artifacts(
    *,
    game_dir: Path,
    temp_level_current: Path,
    visible_level: int,
) -> None:
    current_compare_path = game_dir / "current_compare.json"
    current_compare_md_path = game_dir / "current_compare.md"
    try:
        current_compare = json.loads(current_compare_path.read_text())
    except Exception:
        return
    if not isinstance(current_compare, dict):
        return
    try:
        compare_level = int(current_compare.get("level"))
    except Exception:
        return
    if compare_level != int(visible_level):
        return

    temp_compare_dir = temp_level_current / "sequence_compare"
    temp_compare_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(current_compare_path, temp_compare_dir / "current_compare.json")
    if current_compare_md_path.exists():
        shutil.copy2(current_compare_md_path, temp_compare_dir / "current_compare.md")

    reports = current_compare.get("reports")
    if not isinstance(reports, list):
        return
    for stale_report in temp_compare_dir.glob("seq_*.md"):
        stale_report.unlink(missing_ok=True)
    source_dirs = [
        game_dir / "level_current" / "sequence_compare",
        game_dir / f"level_{int(visible_level)}" / "sequence_compare",
    ]
    for report in reports:
        if not isinstance(report, dict):
            continue
        sequence_id = str(report.get("sequence_id") or "").strip()
        if not sequence_id:
            continue
        for source_dir in source_dirs:
            candidate = source_dir / f"{sequence_id}.md"
            if candidate.exists():
                shutil.copy2(candidate, temp_compare_dir / f"{sequence_id}.md")
                break


def compare_placeholder_payload(*, visible_level: int) -> tuple[str, str]:
    summary = f"No sequence comparison has been recorded yet for visible level {int(visible_level)}."
    payload = {
        "schema_version": "arc.compare.current.v1",
        "status": "no_sequences_yet",
        "level": int(visible_level),
        "all_match": None,
        "compared_sequences": 0,
        "diverged_sequences": 0,
        "summary": summary,
    }
    json_text = json.dumps(payload, indent=2) + "\n"
    md_text = (
        f"# Current Compare (Level {int(visible_level)})\n\n"
        "- status: no_sequences_yet\n"
        f"- summary: {summary}\n"
    )
    return json_text, md_text


def sync_workspace_compare_surface(
    *,
    game_dir: Path,
    temp_level_current: Path,
    visible_level: int,
) -> None:
    root_compare_json = game_dir / "current_compare.json"
    root_compare_md = game_dir / "current_compare.md"
    temp_compare_dir = temp_level_current / "sequence_compare"
    temp_compare_json = temp_compare_dir / "current_compare.json"
    temp_compare_md = temp_compare_dir / "current_compare.md"

    compare_matches_visible = False
    if temp_compare_json.exists():
        try:
            payload = json.loads(temp_compare_json.read_text())
        except Exception:
            payload = None
        if isinstance(payload, dict):
            try:
                compare_matches_visible = int(payload.get("level")) == int(visible_level)
            except Exception:
                compare_matches_visible = False

    if compare_matches_visible:
        shutil.copy2(temp_compare_json, root_compare_json)
        if temp_compare_md.exists():
            shutil.copy2(temp_compare_md, root_compare_md)
        else:
            root_compare_md.unlink(missing_ok=True)
        return

    json_text, md_text = compare_placeholder_payload(visible_level=int(visible_level))
    temp_compare_dir.mkdir(parents=True, exist_ok=True)
    for stale_report in temp_compare_dir.glob("seq_*.md"):
        stale_report.unlink(missing_ok=True)
    temp_compare_json.write_text(json_text, encoding="utf-8")
    temp_compare_md.write_text(md_text, encoding="utf-8")
    root_compare_json.write_text(json_text, encoding="utf-8")
    root_compare_md.write_text(md_text, encoding="utf-8")
