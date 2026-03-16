from __future__ import annotations

import argparse
import json
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
        "--continue-run",
        action="store_true",
        help=(
            "Continue an existing run/session instead of starting a fresh `super new`. "
            "Requires --session-name pointing at an existing run id."
        ),
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
    components_template: str,
    play_template: str,
    artifact_helpers_template: str,
    inspect_sequence_template: str,
    inspect_components_template: str,
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

    components_file = game_dir / "components.py"
    if not components_file.exists():
        components_file.write_text(components_template)

    play_file = game_dir / "play.py"
    if not play_file.exists():
        play_file.write_text(play_template)

    artifact_helpers_file = game_dir / "artifact_helpers.py"
    if not artifact_helpers_file.exists():
        artifact_helpers_file.write_text(artifact_helpers_template)

    inspect_sequence_file = game_dir / "inspect_sequence.py"
    if not inspect_sequence_file.exists():
        inspect_sequence_file.write_text(inspect_sequence_template)

    inspect_components_file = game_dir / "inspect_components.py"
    if not inspect_components_file.exists():
        inspect_components_file.write_text(inspect_components_template)

    current_compare_md = game_dir / "current_compare.md"
    if not current_compare_md.exists():
        current_compare_md.write_text(
            "# Current Compare\n\n"
            "No sequence comparison has been recorded yet for this run.\n"
        )

    current_compare_json = game_dir / "current_compare.json"
    if not current_compare_json.exists():
        current_compare_json.write_text(
            json.dumps(
                {
                    "schema_version": "arc.compare.current.v1",
                    "status": "no_sequences_yet",
                    "all_match": None,
                    "summary": "No sequence comparison has been recorded yet for this run.",
                },
                indent=2,
            )
            + "\n"
        )


def _game_id_candidates(game_id: str) -> list[str]:
    normalized = str(game_id or "").strip()
    if not normalized:
        return []
    out = [normalized]
    if re.fullmatch(r".+-[0-9a-f]{8}", normalized):
        base = normalized.rsplit("-", 1)[0]
        if base and base not in out:
            out.append(base)
    return out


def _metadata_matches_game_id(metadata_game_id: str, requested_game_id: str) -> bool:
    metadata_value = str(metadata_game_id or "").strip()
    if not metadata_value:
        return False
    for candidate in _game_id_candidates(requested_game_id):
        if metadata_value == candidate or metadata_value.startswith(f"{candidate}-"):
            return True
    return False


def seed_arc_environment_cache_impl(
    arc_env_dir: Path,
    *,
    requested_game_id: str,
    cache_root: Path,
) -> Path:
    """Populate a per-run OFFLINE cache from an existing cached environment."""
    arc_env_dir.mkdir(parents=True, exist_ok=True)
    metadata_candidates: list[tuple[float, Path, dict]] = []
    resolved_dest = arc_env_dir.resolve()

    for metadata_path in cache_root.rglob("metadata.json"):
        try:
            if resolved_dest in metadata_path.resolve().parents:
                continue
            payload = json.loads(metadata_path.read_text())
        except Exception:
            continue
        if not _metadata_matches_game_id(payload.get("game_id", ""), requested_game_id):
            continue
        try:
            parent_mtime = metadata_path.parent.stat().st_mtime
        except Exception:
            parent_mtime = metadata_path.stat().st_mtime
        metadata_candidates.append((parent_mtime, metadata_path, payload))

    if not metadata_candidates:
        raise RuntimeError(
            "OFFLINE mode could not find a cached environment for "
            f"{requested_game_id!r} under {cache_root}"
        )

    metadata_candidates.sort(key=lambda item: (item[0], str(item[1])))
    _mtime, selected_metadata_path, _payload = metadata_candidates[-1]
    selected_variant_dir = selected_metadata_path.parent
    selected_game_dir = selected_variant_dir.parent
    destination_game_dir = arc_env_dir / selected_game_dir.name

    if destination_game_dir.exists():
        shutil.rmtree(destination_game_dir)
    shutil.copytree(selected_game_dir, destination_game_dir)

    for copied_metadata_path in destination_game_dir.rglob("metadata.json"):
        try:
            copied_payload = json.loads(copied_metadata_path.read_text())
        except Exception:
            continue
        copied_payload["local_dir"] = str(copied_metadata_path.parent)
        copied_metadata_path.write_text(json.dumps(copied_payload, indent=2) + "\n")

    return destination_game_dir


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
        "arc_level.py",
    ]
    optional_tools = [
        "arc_repl_exec_output.py",
        "arc_repl_paths.py",
        "proc_utils.py",
        "arc_repl_diffs.py",
        "arc_repl_env.py",
        "arc_repl_exec.py",
        "arc_repl_state.py",
        "arc_repl_action_history.py",
        "arc_repl_daemon_client.py",
        "arc_repl_diagnostics.py",
        "arc_repl_intercepts.py",
        "arc_repl_compare_intercepts.py",
        "arc_repl_session_artifacts.py",
        "arc_repl_session_compat.py",
        "arc_repl_session_core.py",
        "arc_repl_session_exec.py",
        "arc_repl_session_grid.py",
        "arc_repl_session_sequences.py",
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

    runtime_src = project_root / "arc_model_runtime"
    runtime_dst = tools_dir / "arc_model_runtime"
    if not runtime_src.exists():
        raise RuntimeError(f"missing runtime package: {runtime_src}")
    if runtime_dst.exists():
        shutil.rmtree(runtime_dst)
    shutil.copytree(runtime_src, runtime_dst)

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

    arc_level_wrapper = f"""#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR=\"$(cd \"$(dirname \"${{BASH_SOURCE[0]}}\")\" && pwd)\"
CONFIG_DIR=\"$(cd \"${{SCRIPT_DIR}}/..\" && pwd)\"
exec \"{py}\" \"${{CONFIG_DIR}}/tools/arc_level.py\" \"$@\"
"""
    arc_level_path = bin_dir / "arc_level"
    arc_level_path.write_text(arc_level_wrapper)
    arc_level_path.chmod(0o755)

    switch_mode_wrapper = """#!/usr/bin/env bash
set -euo pipefail
printf '{"ok":true,"tool":"switch_mode","argv":'
python3 - <<'PY' "$@"
import json
import sys
print(json.dumps(sys.argv[1:]))
PY
printf '}\n'
"""
    switch_mode_path = bin_dir / "switch_mode"
    switch_mode_path.write_text(switch_mode_wrapper)
    switch_mode_path.chmod(0o755)

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
    """Fail fast if agent publication shape leaks env internals or unexpected roots."""
    forbidden: list[Path] = []
    allowed_root = re.compile(r"^game_[A-Za-z0-9_.-]+$")
    for path in agent_dir.rglob("*"):
        rel = path.relative_to(agent_dir)
        if path.is_symlink():
            forbidden.append(rel)
            continue
        if len(rel.parts) == 1 and not allowed_root.fullmatch(rel.name):
            forbidden.append(rel)
            continue
        if "environment_files" in rel.parts:
            forbidden.append(rel)
            continue
        lower_name = path.name.lower()
        if lower_name.endswith((".zip", ".tar", ".tgz", ".tar.gz")):
            forbidden.append(rel)
            continue
    if forbidden:
        preview = ", ".join(str(p) for p in sorted(set(forbidden))[:8])
        raise RuntimeError(
            "agent filesystem violates the run publication model: "
            f"{preview}"
        )


def assert_existing_run_agent_dir_is_safe_impl(agent_dir: Path) -> None:
    """Allow persisted run artifacts while still blocking leaked internals/escaping links."""
    forbidden: list[Path] = []
    allowed_root = re.compile(r"^game_[A-Za-z0-9_.-]+$")
    resolved_agent_dir = agent_dir.resolve()
    for path in agent_dir.rglob("*"):
        rel = path.relative_to(agent_dir)
        if len(rel.parts) == 1 and not allowed_root.fullmatch(rel.name):
            forbidden.append(rel)
            continue
        if "environment_files" in rel.parts:
            forbidden.append(rel)
            continue
        lower_name = path.name.lower()
        if lower_name.endswith((".zip", ".tar", ".tgz", ".tar.gz")):
            forbidden.append(rel)
            continue
        if path.is_symlink():
            try:
                resolved_target = path.resolve(strict=True)
            except FileNotFoundError:
                forbidden.append(rel)
                continue
            try:
                resolved_target.relative_to(resolved_agent_dir)
            except ValueError:
                forbidden.append(rel)
                continue
    if forbidden:
        preview = ", ".join(str(p) for p in sorted(set(forbidden))[:8])
        raise RuntimeError(
            "agent filesystem violates the run publication model: "
            f"{preview}"
        )
