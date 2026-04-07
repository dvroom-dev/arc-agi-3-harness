from __future__ import annotations

import json
import re
import shutil
from copy import deepcopy
from pathlib import Path
from typing import Callable


def _canonical_sequence_surface_root(instance_dir: Path) -> Path | None:
    state_dir = instance_dir / "supervisor" / "arc"
    game_artifacts_root = state_dir / "game_artifacts"
    if not game_artifacts_root.exists() or not game_artifacts_root.is_dir():
        return None
    game_roots = [path for path in game_artifacts_root.iterdir() if path.is_dir()]
    if not game_roots:
        return None
    if len(game_roots) == 1:
        return game_roots[0]
    return max(
        game_roots,
        key=lambda path: len(list(path.glob("level_*/sequences/seq_*.json"))),
    )


def _preferred_sequence_surface_root(instance_dir: Path, solver_dir_name: str) -> Path | None:
    canonical_root = _canonical_sequence_surface_root(instance_dir)
    if canonical_root is not None:
        return canonical_root
    solver_dir = instance_dir / "agent" / solver_dir_name
    return solver_dir if solver_dir.exists() else None


def _instance_sequence_richness(instance_dir: Path, solver_dir_name: str) -> tuple[int, int]:
    solver_dir = _preferred_sequence_surface_root(instance_dir, solver_dir_name)
    sequence_dirs = 0
    sequence_files = 0
    if solver_dir and solver_dir.exists():
        for level_dir in solver_dir.glob("level_*"):
            seq_dir = level_dir / "sequences"
            if level_dir.is_dir() and seq_dir.exists() and seq_dir.is_dir():
                sequence_dirs += 1
                sequence_files += len(list(seq_dir.glob("seq_*.json")))
    return sequence_dirs, sequence_files


def _active_flux_instance_dir(workspace_root: Path, safe_instance_name: Callable[[str], str]) -> Path | None:
    try:
        instance_id = str((((json.loads((workspace_root / "flux" / "state.json").read_text()).get("active") or {}).get("solver") or {}).get("instanceId")) or "").strip()
        instance_dir = workspace_root / "flux_instances" / safe_instance_name(instance_id)
        return instance_dir if instance_id and instance_dir.exists() else None
    except Exception:
        return None


def _selected_flux_instances(workspace_root: str, solver_dir_name: str, safe_instance_name: Callable[[str], str]) -> tuple[Path | None, Path, list[Path]] | None:
    attempts_root = Path(workspace_root) / "flux_instances"
    attempts = [path for path in attempts_root.iterdir() if path.is_dir()] if attempts_root.exists() else []
    if not attempts:
        return None
    active = _active_flux_instance_dir(Path(workspace_root), safe_instance_name)
    latest = max(attempts, key=lambda path: path.stat().st_mtime)
    ordered = sorted(
        attempts,
        key=lambda path: (_instance_sequence_richness(path, solver_dir_name), path.stat().st_mtime),
        reverse=True,
    )
    return active if active in attempts else None, latest, ordered


def _current_level_for_surface(level_dir: Path) -> int | None:
    try:
        if level_dir.name == "level_current":
            payload = json.loads((level_dir / "meta.json").read_text())
            return int(payload.get("level", 0) or 0) or None
        if re.fullmatch(r"level_\d+", level_dir.name):
            return int(level_dir.name.split("_", 1)[1])
    except Exception:
        return None
    return None


def _iter_sequence_surfaces(solver_dir: Path) -> list[tuple[int, Path]]:
    surfaces: list[tuple[int, Path]] = []
    for candidate in sorted(solver_dir.glob("level_*")):
        if not candidate.is_dir():
            continue
        seq_root = candidate / "sequences"
        if not seq_root.exists() or not any(seq_root.glob("seq_*.json")):
            continue
        level_num = _current_level_for_surface(candidate)
        if level_num is None:
            continue
        surfaces.append((level_num, candidate))
    level_current = solver_dir / "level_current"
    seq_root = level_current / "sequences"
    if level_current.exists() and seq_root.exists() and any(seq_root.glob("seq_*.json")):
        level_num = _current_level_for_surface(level_current)
        if level_num is not None and not any(existing_level == level_num and existing_dir == level_current for existing_level, existing_dir in surfaces):
            surfaces.append((level_num, level_current))
    return sorted(surfaces, key=lambda item: (item[0], item[1].name))


def _sequence_fingerprint(payload: dict) -> str:
    reduced = {
        "level": int(payload.get("level", 0) or 0),
        "end_reason": str(payload.get("end_reason", "") or ""),
        "action_count": int(payload.get("action_count", 0) or 0),
        "actions": [
            {
                "local_step": int(action.get("local_step", 0) or 0),
                "action_name": str(action.get("action_name", "") or ""),
                "state_before": str(action.get("state_before", "") or ""),
                "state_after": str(action.get("state_after", "") or ""),
                "level_before": int(action.get("level_before", 0) or 0),
                "level_after": int(action.get("level_after", 0) or 0),
                "levels_completed_before": int(action.get("levels_completed_before", 0) or 0),
                "levels_completed_after": int(action.get("levels_completed_after", 0) or 0),
                "level_complete_after": bool(action.get("level_complete_after", False)),
                "game_over_after": bool(action.get("game_over_after", False)),
            }
            for action in (payload.get("actions") if isinstance(payload.get("actions"), list) else [])
            if isinstance(action, dict)
        ],
    }
    return json.dumps(reduced, sort_keys=True)


def _rewrite_sequence_payload(payload: dict, *, old_sequence_id: str, new_sequence_id: str, new_sequence_number: int) -> dict:
    rewritten = deepcopy(payload)
    rewritten["sequence_id"] = new_sequence_id
    rewritten["sequence_number"] = new_sequence_number
    for action in rewritten.get("actions", []) if isinstance(rewritten.get("actions"), list) else []:
        if not isinstance(action, dict):
            continue
        files = action.get("files")
        if not isinstance(files, dict):
            continue
        for key, value in list(files.items()):
            if isinstance(value, str):
                files[key] = value.replace(f"sequences/{old_sequence_id}/", f"sequences/{new_sequence_id}/")
            elif isinstance(value, list):
                files[key] = [
                    item.replace(f"sequences/{old_sequence_id}/", f"sequences/{new_sequence_id}/")
                    if isinstance(item, str) else item
                    for item in value
                ]
    return rewritten


def _merge_sequences_into_level(model_level_dir: Path, source_level_dir: Path) -> int:
    source_seq_root = source_level_dir / "sequences"
    if not source_seq_root.exists():
        return 0
    model_level_dir.mkdir(parents=True, exist_ok=True)
    target_seq_root = model_level_dir / "sequences"
    target_seq_root.mkdir(parents=True, exist_ok=True)

    existing_fingerprints: dict[str, str] = {}
    existing_numbers: list[int] = []
    for sequence_path in sorted(target_seq_root.glob("seq_*.json")):
        try:
            payload = json.loads(sequence_path.read_text())
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        existing_fingerprints[_sequence_fingerprint(payload)] = str(payload.get("sequence_id") or sequence_path.stem)
        try:
            existing_numbers.append(int(payload.get("sequence_number", 0) or 0))
        except Exception:
            continue
    next_number = max(existing_numbers, default=0) + 1
    merged = 0

    for sequence_path in sorted(source_seq_root.glob("seq_*.json")):
        try:
            payload = json.loads(sequence_path.read_text())
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        fingerprint = _sequence_fingerprint(payload)
        if fingerprint in existing_fingerprints:
            continue
        old_sequence_id = str(payload.get("sequence_id") or sequence_path.stem)
        new_sequence_id = f"seq_{next_number:04d}"
        next_number += 1
        rewritten = _rewrite_sequence_payload(
            payload,
            old_sequence_id=old_sequence_id,
            new_sequence_id=new_sequence_id,
            new_sequence_number=next_number - 1,
        )
        (target_seq_root / f"{new_sequence_id}.json").write_text(json.dumps(rewritten, indent=2) + "\n", encoding="utf-8")
        source_sequence_dir = source_seq_root / old_sequence_id
        if source_sequence_dir.exists() and source_sequence_dir.is_dir():
            shutil.copytree(source_sequence_dir, target_seq_root / new_sequence_id, dirs_exist_ok=True)
        existing_fingerprints[fingerprint] = new_sequence_id
        merged += 1
    return merged


def sync_latest_attempt_to_model_workspace_impl(
    workspace_root: str,
    meta: dict,
    *,
    sync_solver_artifacts_to_model_workspace: Callable[..., list[str]],
    safe_instance_name: Callable[[str], str],
) -> list[str]:
    solver_dir_name = Path(str(meta.get("solver_template_dir") or meta.get("model_workspace_dir") or "game_ls20")).name
    selected = _selected_flux_instances(workspace_root, solver_dir_name, safe_instance_name)
    if not selected:
        return []
    active, latest, ordered = selected
    primary = active or latest
    solver_dir = primary / "agent" / solver_dir_name
    state_dir = primary / "supervisor" / "arc"
    if not solver_dir.exists():
        return []
    synced = sync_solver_artifacts_to_model_workspace(meta, solver_dir, state_dir=state_dir)
    model_workspace = Path(str(meta["model_workspace_dir"]))
    for attempt in ordered:
        sequence_surface_root = _preferred_sequence_surface_root(attempt, solver_dir_name)
        if sequence_surface_root is None or not sequence_surface_root.exists():
            continue
        for level_num, source_level_dir in _iter_sequence_surfaces(sequence_surface_root):
            target_level_dir = model_workspace / f"level_{level_num}"
            if not target_level_dir.exists():
                shutil.copytree(source_level_dir, target_level_dir, dirs_exist_ok=True)
                synced.append(str(target_level_dir))
                continue
            merged = _merge_sequences_into_level(target_level_dir, source_level_dir)
            if merged > 0:
                synced.append(str(target_level_dir / "sequences"))
    return synced


def latest_flux_instance_state_dir_impl(workspace_root: str, meta: dict, *, safe_instance_name: Callable[[str], str]) -> Path | None:
    solver_dir_name = Path(str(meta.get("solver_template_dir") or meta.get("model_workspace_dir") or "game_ls20")).name
    selected = _selected_flux_instances(workspace_root, solver_dir_name, safe_instance_name)
    if not selected:
        return None
    active, latest, ordered = selected
    if active:
        active_state = active / "supervisor" / "arc"
        return active_state if active_state.exists() else None
    richest = ordered[0]
    chosen = richest if _instance_sequence_richness(richest, solver_dir_name) > _instance_sequence_richness(latest, solver_dir_name) else latest
    state_dir = chosen / "supervisor" / "arc"
    return state_dir if state_dir.exists() else None
