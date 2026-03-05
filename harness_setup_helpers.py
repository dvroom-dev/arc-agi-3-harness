from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path


def parse_args_impl() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ARC-AGI-3 supervisor harness")
    parser.add_argument("--game-id", default="ls20", help="Game ID to load")
    parser.add_argument(
        "--game-ids",
        default=None,
        help=(
            "Optional comma/space-separated game IDs to run sequentially in one harness invocation. "
            "When set, this overrides --game-id."
        ),
    )
    parser.add_argument(
        "--max-turns", type=int, default=None,
        help="Maximum harness turns before stopping (default: unlimited)",
    )
    parser.add_argument(
        "--operation-mode", default="NORMAL",
        choices=["NORMAL", "ONLINE", "OFFLINE"],
        help="Arcade operation mode",
    )
    parser.add_argument(
        "--session-name", default=None,
        help="Session directory name (default: timestamp)",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Print colored game grid to terminal after each state change",
    )
    parser.add_argument(
        "--open-scorecard", action="store_true",
        help="Open a new scorecard at start and close at end (requires ONLINE mode)",
    )
    parser.add_argument(
        "--scorecard-id", default=None,
        help="Use an existing scorecard ID",
    )
    parser.add_argument(
        "--provider", default=None,
        choices=["claude", "codex", "mock"],
        help="LLM provider for super CLI (default: from super.yaml runtime_defaults)",
    )
    parser.add_argument(
        "--no-supervisor", action="store_true",
        help="Disable supervision (pass --no-supervisor to super CLI)",
    )
    parser.add_argument(
        "--explore-inputs", action="store_true",
        help=(
            "Opt-in: run one-time automated input exploration at the first level "
            "of a fresh game start."
        ),
    )
    parser.add_argument(
        "--max-game-over-resets", type=int, default=0,
        help=(
            "Maximum harness-driven automatic reset_level calls after GAME_OVER before stopping "
            "(default: 0, disabled; let agent/supervisor own recovery)."
        ),
    )
    parser.add_argument(
        "--arc-backend",
        default="api",
        choices=["api", "server"],
        help=(
            "ARC HTTP backend target: `api` uses https://three.arcprize.org; "
            "`server` uses a local ARC server (default http://127.0.0.1:8000)."
        ),
    )
    parser.add_argument(
        "--arc-base-url",
        default=None,
        help=(
            "Override ARC base URL for Arcade API calls. "
            "If unset, derives from --arc-backend."
        ),
    )
    parser.add_argument(
        "--scorecard-owner-check-id",
        default=None,
        help=(
            "Optional scorecard ID that must be readable before opening/reusing scorecards. "
            "Use this to fail fast if ARC_API_KEY points to the wrong account."
        ),
    )
    parser.add_argument(
        "--scorecard-session-preflight",
        action="store_true",
        help=(
            "Run a scored-session preflight before scored runs. "
            "This exercises both positive and historical failure paths for scorecard/session binding."
        ),
    )
    parser.add_argument(
        "--score-after-solve",
        action="store_true",
        help=(
            "Two-phase run: solve unscored first, then open a fresh scorecard and replay "
            "from level 1 in the same run filesystem."
        ),
    )
    parser.add_argument(
        "--score-after-solve-start-mode",
        default="recover",
        help=(
            "Starting mode for the scored replay phase when --score-after-solve is enabled "
            "(passed to `super new --start-mode`)."
        ),
    )
    return parser.parse_args()


def setup_run_dir_impl(
    run_dir: Path,
    agent_dir: Path,
    supervisor_dir: Path,
    log,
    *,
    level_completions_template: str,
    play_lib_template: str,
    model_lib_template: str,
    theory_template: str,
    model_template: str,
    play_template: str,
    game_id: str,
) -> None:
    """Set up an isolated run directory with split agent/supervisor dirs."""
    run_dir.mkdir(parents=True, exist_ok=True)
    agent_dir.mkdir(parents=True, exist_ok=True)
    supervisor_dir.mkdir(parents=True, exist_ok=True)

    supervisor_arc = supervisor_dir / "arc"
    supervisor_arc.mkdir(parents=True, exist_ok=True)

    lc = supervisor_arc / "level_completions.md"
    if not lc.exists():
        lc.write_text(level_completions_template)

    safe_game_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(game_id or "").strip()).strip("._")
    if not safe_game_id:
        safe_game_id = "game"
    game_dir = agent_dir / f"game_{safe_game_id}"
    game_dir.mkdir(parents=True, exist_ok=True)

    runtime_src = Path(__file__).resolve().parent / "arc_model_runtime"
    if not runtime_src.exists():
        raise RuntimeError(f"missing runtime package: {runtime_src}")
    runtime_root = agent_dir / "_runtime"
    runtime_dst = runtime_root / "arc_model_runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)
    if runtime_dst.exists():
        shutil.rmtree(runtime_dst)
    shutil.copytree(runtime_src, runtime_dst)

    # Keep a single canonical play_lib per game to avoid import/path collisions.
    play_lib_game = game_dir / "play_lib.py"
    if not play_lib_game.exists():
        play_lib_game.write_text(play_lib_template)

    model_lib_file = game_dir / "model_lib.py"
    if not model_lib_file.exists():
        model_lib_file.write_text(model_lib_template)

    theory_file = game_dir / "theory.md"
    if not theory_file.exists():
        theory_file.write_text(theory_template)

    model_file = game_dir / "model.py"
    if not model_file.exists():
        model_file.write_text(model_template)

    play_file = game_dir / "play.py"
    if not play_file.exists():
        play_file.write_text(play_template)


def setup_run_config_dir_impl(
    run_config_dir: Path,
    *,
    project_root: Path,
    project_venv_python: Path,
) -> tuple[Path, Path]:
    """Create run-local config/bin/tools so agent shell stays in run workspace."""
    run_config_dir.mkdir(parents=True, exist_ok=True)
    tools_dir = run_config_dir / "tools"
    bin_dir = run_config_dir / "bin"
    prompts_dir = run_config_dir / "prompts"
    tools_dir.mkdir(parents=True, exist_ok=True)
    bin_dir.mkdir(parents=True, exist_ok=True)
    prompts_dir.mkdir(parents=True, exist_ok=True)

    required_tools = [
        "arc_repl.py",
        "arc_repl_cli.py",
        "arc_repl_daemon.py",
    ]
    optional_tools = [
        "arc_repl_paths.py",
        "proc_utils.py",
        "arc_action_diffs.py",
        "arc_action_env.py",
        "arc_action_exec.py",
        "arc_action_state.py",
        "arc_repl_action_history.py",
        "arc_repl_diagnostics.py",
        "arc_repl_session_artifacts.py",
        "arc_repl_session_core.py",
        "arc_repl_session_exec.py",
        "arc_repl_session_grid.py",
    ]

    for filename in required_tools:
        src = project_root / "tools" / filename
        dst = tools_dir / filename
        shutil.copyfile(src, dst)

    for filename in optional_tools:
        src = project_root / "tools" / filename
        if not src.exists():
            continue
        dst = tools_dir / filename
        shutil.copyfile(src, dst)

    py = str(project_venv_python)
    arc_repl_wrapper = f"""#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR=\"$(cd \"$(dirname \"${{BASH_SOURCE[0]}}\")\" && pwd)\"
CONFIG_DIR=\"$(cd \"${{SCRIPT_DIR}}/..\" && pwd)\"
exec \"{py}\" \"${{CONFIG_DIR}}/tools/arc_repl_cli.py\" \"$@\"
"""
    arc_repl_path = bin_dir / "arc_repl"
    arc_repl_path.write_text(arc_repl_wrapper)
    arc_repl_path.chmod(0o755)

    src_prompts_dir = project_root / "prompts"
    if not src_prompts_dir.exists():
        raise RuntimeError(f"missing prompts directory: {src_prompts_dir}")
    for src in src_prompts_dir.rglob("*"):
        rel = src.relative_to(src_prompts_dir)
        dst = prompts_dir / rel
        if src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)

    return bin_dir, tools_dir


def assert_no_game_files_in_agent_dir_impl(agent_dir: Path) -> None:
    """Fail fast if game/environment source appears in the agent filesystem."""
    forbidden: list[Path] = []
    for path in agent_dir.rglob("*"):
        rel = path.relative_to(agent_dir)
        if "environment_files" in rel.parts:
            forbidden.append(rel)
            continue
        if path.name in {"game_state.py", "ls20.py"}:
            forbidden.append(rel)
            continue
        if path.suffix == ".zip" and "environment" in path.name.lower():
            forbidden.append(rel)
            continue
    if forbidden:
        preview = ", ".join(str(p) for p in sorted(set(forbidden))[:8])
        raise RuntimeError(
            "agent filesystem contains forbidden game/environment artifacts: "
            f"{preview}"
        )
