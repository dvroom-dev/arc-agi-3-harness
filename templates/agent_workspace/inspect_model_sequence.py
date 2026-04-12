#!/usr/bin/env python3
"""Replay one model sequence step and dump game-vs-model state at the divergence."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

import numpy as np

import artifact_helpers

CONFIG_DIR = Path(str(os.getenv("ARC_CONFIG_DIR", "") or "")).expanduser()
if not str(CONFIG_DIR).strip():
    raise RuntimeError("ARC_CONFIG_DIR is required for model runtime imports.")
RUNTIME_PARENT = CONFIG_DIR / "tools"
if not RUNTIME_PARENT.exists():
    raise RuntimeError(f"model runtime path missing: {RUNTIME_PARENT}")
if str(RUNTIME_PARENT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_PARENT))

from arc_model_runtime.session import ModelSession
from arc_model_runtime.utils import action_from_name, diff_payload, read_hex_grid
from model import Hooks


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-dir", default=".", help="Game workspace root (default: current dir)")
    parser.add_argument("--game-id", required=True, help="Model game id, for example ls20-9607627b")
    parser.add_argument("--current-mismatch", action="store_true", help="Inspect the first mismatching compare step")
    parser.add_argument("--level", type=int, help="Explicit level number")
    parser.add_argument("--sequence", help="Sequence id such as seq_0001")
    parser.add_argument("--step", type=int, help="Local step number within the sequence")
    parser.add_argument(
        "--value",
        action="append",
        default=[],
        help="Hex value to track in frame summaries. May be repeated; defaults to C and 9.",
    )
    return parser.parse_args()


def _parse_values(values: list[str]) -> list[int]:
    chosen = values or ["C", "9"]
    out: list[int] = []
    for value in chosen:
        token = str(value).strip()
        if not token:
            continue
        out.append(int(token, 16))
    return out


def _tracked_value_summary(grid: np.ndarray, tracked_values: list[int]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for value in tracked_values:
        rows, cols = np.where(grid == int(value))
        key = format(int(value), "X")
        if len(rows) == 0:
            summary[key] = {"count": 0, "bbox": None}
            continue
        summary[key] = {
            "count": int(len(rows)),
            "bbox": [
                int(rows.min()),
                int(cols.min()),
                int(rows.max()),
                int(cols.max()),
            ],
        }
    return summary


def _scalar_env_snapshot(env: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    skip = {
        "grid",
        "hooks",
        "game_dir",
        "_level_initial_states",
        "available_model_levels",
        "action_space",
        "last_step_frames",
    }
    for key, value in vars(env).items():
        if key in skip:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            out[key] = value
            continue
        if isinstance(value, (list, tuple)) and len(value) <= 12:
            if all(isinstance(item, (str, int, float, bool)) or item is None for item in value):
                out[key] = list(value)
    return out


def _resolve_target(args: argparse.Namespace, game_dir: Path) -> tuple[int, str, int, dict[str, Any] | None]:
    if args.current_mismatch:
        compare_payload = artifact_helpers.load_current_compare(game_dir)
        mismatch = artifact_helpers.first_mismatch_report(compare_payload)
        if not mismatch:
            raise SystemExit("current_compare.json has no mismatched report")
        level = int(mismatch.get("level") or compare_payload.get("level") or 0)
        sequence_id = str(mismatch.get("sequence_id") or "").strip()
        step = int(mismatch.get("divergence_step") or 0)
        if level <= 0 or not sequence_id or step <= 0:
            raise SystemExit("current mismatch is missing level, sequence_id, or divergence_step")
        return level, sequence_id, step, mismatch
    if args.level is None or not args.sequence or args.step is None:
        raise SystemExit("--game-id plus either --current-mismatch or all of --level --sequence --step are required")
    return int(args.level), str(args.sequence), int(args.step), None


def _replay_sequence_step(
    *,
    session: ModelSession,
    level: int,
    sequence_payload: dict[str, Any],
    target_step: int,
    tracked_values: list[int],
) -> dict[str, Any]:
    actions = list(sequence_payload.get("actions", []) or [])
    if not actions:
        raise RuntimeError("sequence has no actions")
    session.do_set_level(int(level))
    step_summaries: list[dict[str, Any]] = []
    selected: dict[str, Any] | None = None

    for action in actions:
        if not isinstance(action, dict):
            continue
        local_step = int(action.get("local_step", 0) or 0)
        if local_step <= 0:
            continue
        before_grid = np.array(session.env.grid, dtype=np.int8, copy=True)
        before_env = _scalar_env_snapshot(session.env)
        action_name = str(action.get("action_name", "")).strip()
        action_data = action.get("action_data", {}) if isinstance(action.get("action_data"), dict) else {}

        session.env.level_complete = False
        session.env.last_step_level_complete = False
        session.env.game_over = False
        session.env.last_step_game_over = False
        session.env.last_step_frames = []
        session.env.hooks.apply_action(session.env, action_from_name(action_name), data=action_data, reasoning=None)
        if not session.env.last_step_frames:
            session.env.last_step_frames = [np.array(session.env.grid, dtype=np.int8, copy=True)]

        model_frames = [np.array(frame, dtype=np.int8, copy=True) for frame in session.env.last_step_frames]
        after_grid = np.array(session.env.grid, dtype=np.int8, copy=True)
        after_env = _scalar_env_snapshot(session.env)
        step_summary = {
            "local_step": local_step,
            "action_index": int(action.get("action_index", 0) or 0),
            "action_name": action_name,
            "frame_count_model": int(len(model_frames)),
            "before_values": _tracked_value_summary(before_grid, tracked_values),
            "after_values": _tracked_value_summary(after_grid, tracked_values),
            "state_diff_changed_pixels": int(diff_payload(before_grid, after_grid).get("changed_pixels", 0) or 0),
            "env_after": after_env,
        }
        step_summaries.append(step_summary)
        if local_step == target_step:
            selected = {
                "action": action,
                "before_grid": before_grid,
                "after_grid": after_grid,
                "before_env": before_env,
                "after_env": after_env,
                "model_frames": model_frames,
                "step_summary": step_summary,
            }
            break

    if selected is None:
        raise RuntimeError(f"target step {target_step} not found in sequence replay")

    return {
        "steps_replayed": step_summaries,
        "selected": selected,
    }


def main() -> int:
    args = parse_args()
    game_dir = Path(args.game_dir).resolve()
    tracked_values = _parse_values(list(args.value or []))
    level, sequence_id, target_step, mismatch = _resolve_target(args, game_dir)
    sequence_payload = artifact_helpers.load_sequence(game_dir, level, sequence_id)
    step = artifact_helpers.select_sequence_step(sequence_payload, local_step=target_step)
    files = step.get("files") if isinstance(step.get("files"), dict) else {}
    level_root = artifact_helpers.level_dir(game_dir, level)
    before_path = level_root / str(files.get("before_state_hex", ""))
    after_path = level_root / str(files.get("after_state_hex", ""))
    game_before = read_hex_grid(before_path)
    game_after = read_hex_grid(after_path)
    frame_paths = files.get("frame_sequence_hex", []) if isinstance(files.get("frame_sequence_hex"), list) else []
    game_frames = [read_hex_grid(level_root / str(rel)) for rel in frame_paths if (level_root / str(rel)).exists()]

    session = ModelSession(game_id=args.game_id, game_dir=game_dir, hooks=Hooks())
    replay = _replay_sequence_step(
        session=session,
        level=level,
        sequence_payload=sequence_payload,
        target_step=target_step,
        tracked_values=tracked_values,
    )
    selected = replay["selected"]
    model_frames = selected["model_frames"]

    payload = {
        "level": int(level),
        "sequence_id": sequence_id,
        "target_step": int(target_step),
        "replay_mode": "cumulative_sequence_replay",
        "transient_step_state_reset": True,
        "compare_frame_count_semantics": {
            "completion_boundary_excludes_terminal_post_level_change_frame": True,
            "game_frame_files_present_does_not_imply_compare_counts_all_of_them": True,
        },
        "tracked_values": [format(value, "X") for value in tracked_values],
        "mismatch_report": {
            "divergence_reason": mismatch.get("divergence_reason") if isinstance(mismatch, dict) else None,
            "state_diff_changed_pixels": (mismatch.get("state_diff") or {}).get("changed_pixels") if isinstance(mismatch, dict) else None,
            "game_step_diff_changed_pixels": (mismatch.get("game_step_diff") or {}).get("changed_pixels") if isinstance(mismatch, dict) else None,
            "model_step_diff_changed_pixels": (mismatch.get("model_step_diff") or {}).get("changed_pixels") if isinstance(mismatch, dict) else None,
        },
        "game": {
            "before_state_hex": artifact_helpers.display_path(game_dir, before_path),
            "after_state_hex": artifact_helpers.display_path(game_dir, after_path),
            "frame_count": int(len(game_frames)),
            "before_values": _tracked_value_summary(game_before, tracked_values),
            "after_values": _tracked_value_summary(game_after, tracked_values),
            "state_diff": diff_payload(game_before, game_after),
            "frames": [
                {
                    "frame_index": idx + 1,
                    "values": _tracked_value_summary(frame, tracked_values),
                }
                for idx, frame in enumerate(game_frames)
            ],
        },
        "model": {
            "frame_count": int(len(model_frames)),
            "before_values": _tracked_value_summary(selected["before_grid"], tracked_values),
            "after_values": _tracked_value_summary(selected["after_grid"], tracked_values),
            "state_diff": diff_payload(selected["before_grid"], selected["after_grid"]),
            "env_before": selected["before_env"],
            "env_after": selected["after_env"],
            "frames": [
                {
                    "frame_index": idx + 1,
                    "values": _tracked_value_summary(frame, tracked_values),
                }
                for idx, frame in enumerate(model_frames)
            ],
        },
        "steps_replayed": replay["steps_replayed"],
    }
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
