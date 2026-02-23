#!/usr/bin/env python3
"""Score ARC harness runs using ARC-AGI baseline actions.

This script computes per-level action counts from turn traces and then applies
the same scoring math used by ARC-AGI's EnvironmentScoreCalculator:
score(level) = min((baseline_actions / actions_taken) * 100, 100), else 0.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from arc_agi import Arcade, EnvironmentScoreCalculator, OperationMode


STEP_HEADER_RE = re.compile(r"^### Step \d+: .* levels=(\d+)/(\d+)\s*$")


@dataclass
class RunScore:
    run_dir: Path
    game_id: str
    state: str
    levels_completed: int
    win_levels: int
    total_actions: int
    level_actions: list[int]
    baseline_actions: list[int]
    level_scores: list[float]
    score: float


def _iter_trace_paths(run_dir: Path) -> list[Path]:
    traces_dir = run_dir / "supervisor" / "arc" / "turn-traces"
    if not traces_dir.is_dir():
        return []

    def key(path: Path) -> tuple[int, str]:
        m = re.search(r"turn_(\d+)_trace\.md$", path.name)
        return (int(m.group(1)) if m else 10**9, path.name)

    return sorted(traces_dir.glob("turn_*_trace.md"), key=key)


def _read_state(run_dir: Path) -> dict:
    state_path = run_dir / "supervisor" / "arc" / "state.json"
    if not state_path.is_file():
        raise RuntimeError(f"missing state file: {state_path}")
    return json.loads(state_path.read_text())


def _extract_step_levels(trace_paths: Iterable[Path]) -> list[int]:
    out: list[int] = []
    for trace_path in trace_paths:
        for line in trace_path.read_text().splitlines():
            m = STEP_HEADER_RE.match(line)
            if m:
                out.append(int(m.group(1)))
    return out


def _actions_by_completed_level(step_levels: list[int]) -> tuple[list[int], int]:
    """Return (completed_level_actions, partial_next_level_actions)."""
    completed_actions: list[int] = []
    prev_completed = 0
    cur_actions = 0
    for lv_done in step_levels:
        cur_actions += 1
        if lv_done > prev_completed:
            gains = lv_done - prev_completed
            for _ in range(gains):
                completed_actions.append(cur_actions)
                cur_actions = 0
                prev_completed += 1
    return completed_actions, cur_actions


def _load_baselines(
    *,
    game_id: str,
    metadata_roots: list[Path],
) -> list[int]:
    for root in metadata_roots:
        if not root.exists():
            continue
        for p in root.rglob("metadata.json"):
            try:
                data = json.loads(p.read_text())
            except Exception:
                continue
            if data.get("game_id") == game_id:
                baselines = data.get("baseline_actions") or []
                return [int(v) for v in baselines]
    # Fallback to API metadata via Arcade when local cache is missing.
    api_key = os.getenv("ARC_API_KEY", "")
    if api_key:
        arcade = Arcade(
            arc_api_key=api_key,
            operation_mode=OperationMode.ONLINE,
            environments_dir="/tmp/arc-agi-empty",
        )
        for env in arcade.get_environments():
            if env.game_id == game_id and env.baseline_actions:
                return [int(v) for v in env.baseline_actions]
    raise RuntimeError(
        f"could not find baseline_actions for {game_id}; "
        "add metadata roots via --metadata-root"
    )


def _score_run(run_dir: Path, metadata_roots: list[Path]) -> RunScore:
    state = _read_state(run_dir)
    game_id = str(state.get("game_id") or "")
    if not game_id:
        raise RuntimeError(f"state.json missing game_id: {run_dir}")

    trace_paths = _iter_trace_paths(run_dir)
    step_levels = _extract_step_levels(trace_paths)
    total_actions = len(step_levels)
    completed_level_actions, partial_actions = _actions_by_completed_level(step_levels)
    baselines = _load_baselines(game_id=game_id, metadata_roots=metadata_roots)

    calc = EnvironmentScoreCalculator(
        id=game_id,
        state=state.get("state"),
    )
    prev_total = sum(completed_level_actions)
    for idx, baseline in enumerate(baselines):
        if idx < len(completed_level_actions):
            actions_taken = completed_level_actions[idx]
            completed = True
        elif idx == len(completed_level_actions):
            actions_taken = max(0, total_actions - prev_total)
            completed = False
            prev_total = total_actions
        else:
            actions_taken = 0
            completed = False
        calc.add_level(
            completed=completed,
            actions_taken=actions_taken,
            baseline_actions=baseline,
        )

    score_obj = calc.to_score()
    level_scores = score_obj.level_scores or []
    return RunScore(
        run_dir=run_dir,
        game_id=game_id,
        state=str(state.get("state") or ""),
        levels_completed=int(state.get("levels_completed") or 0),
        win_levels=int(state.get("win_levels") or 0),
        total_actions=total_actions,
        level_actions=score_obj.level_actions or [],
        baseline_actions=score_obj.level_baseline_actions or [],
        level_scores=level_scores,
        score=float(score_obj.score),
    )


def _find_game_run_dirs(prefix: str) -> list[Path]:
    runs_dir = Path("runs")
    return sorted(runs_dir.glob(f"{prefix}-[0-9][0-9]-*"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-dir",
        action="append",
        default=[],
        help="Game run directory (repeatable), e.g. runs/run-...-01-ls20",
    )
    parser.add_argument(
        "--run-prefix",
        default=None,
        help="Run prefix to auto-pick game run dirs, e.g. run-api-multi-live-20260222-1806",
    )
    parser.add_argument(
        "--metadata-root",
        action="append",
        default=["/tmp/arc-agi-env-cache"],
        help="Root containing game metadata.json files (repeatable).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON output instead of text.",
    )
    args = parser.parse_args()

    run_dirs: list[Path] = [Path(p) for p in args.run_dir]
    if args.run_prefix:
        run_dirs.extend(_find_game_run_dirs(args.run_prefix))
    run_dirs = [p for p in run_dirs if p.exists()]

    if not run_dirs:
        print("no run dirs found", file=sys.stderr)
        return 2

    metadata_roots = [Path(p) for p in args.metadata_root]
    results: list[RunScore] = []
    for run_dir in run_dirs:
        results.append(_score_run(run_dir, metadata_roots))

    if args.json:
        payload = {
            "runs": [
                {
                    "run_dir": str(r.run_dir),
                    "game_id": r.game_id,
                    "state": r.state,
                    "levels_completed": r.levels_completed,
                    "win_levels": r.win_levels,
                    "total_actions": r.total_actions,
                    "level_actions": r.level_actions,
                    "baseline_actions": r.baseline_actions,
                    "level_scores": r.level_scores,
                    "score": r.score,
                }
                for r in results
            ]
        }
        print(json.dumps(payload, indent=2))
        return 0

    for r in results:
        print(f"{r.run_dir}")
        print(f"  game_id: {r.game_id}")
        print(f"  state: {r.state} ({r.levels_completed}/{r.win_levels})")
        print(f"  total_actions: {r.total_actions}")
        print(f"  baseline_actions: {r.baseline_actions}")
        print(f"  level_actions:    {r.level_actions}")
        print(f"  level_scores:     {[round(x, 2) for x in r.level_scores]}")
        print(f"  score: {r.score:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
