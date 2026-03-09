"""ARC-AGI-3 supervisor harness: drives the super CLI + game environment loop."""

from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

try:
    from game_state import COLOR_NAMES, render_grid_to_image
except Exception as exc:  # pragma: no cover - fail fast
    raise RuntimeError(
        "Failed to import required game_state helpers. "
        "This harness now requires working game-state rendering/state helpers."
    ) from exc

from harness_grid_helpers import (
    _parse_color_id,
    collect_palette_from_change_records,
    diff_change_records,
    find_click_targets,
    format_change_records,
    summarize_static_features,
)
from harness_history_helpers import (
    append_level_completion_record,
    completion_action_windows_by_level,
    extract_last_assistant_message,
    load_history_events,
    read_max_recorded_completion_level,
    write_prompt_file,
)
from harness_runner import run_main
from harness_setup_helpers import (
    assert_no_game_files_in_agent_dir_impl,
    parse_args_impl,
    seed_arc_environment_cache_impl,
    setup_run_config_dir_impl,
    setup_run_dir_impl,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent
CTXS = PROJECT_ROOT / ".ctxs"
PROJECT_VENV_PYTHON = PROJECT_ROOT / ".venv" / "bin" / "python"
ARC_ENV_CACHE_ROOT = Path("/tmp/arc-agi-env-cache")

LEVEL_COMPLETIONS_TEMPLATE = textwrap.dedent("""\
    # Level Completions

    Canonical record of completed levels and the exact action sequence
    for each completed level window.
""")

def _load_agent_workspace_template(name: str) -> str:
    path = PROJECT_ROOT / "templates" / "agent_workspace" / name
    if not path.exists():
        raise RuntimeError(f"Missing agent workspace template: {path}")
    return path.read_text()


THEORY_TEMPLATE = _load_agent_workspace_template("theory.md")
PLAY_TEMPLATE = _load_agent_workspace_template("play.py")
MODEL_TEMPLATE = _load_agent_workspace_template("model.py")
MODEL_LIB_TEMPLATE = _load_agent_workspace_template("model_lib.py")
PLAY_LIB_TEMPLATE = _load_agent_workspace_template("play_lib.py")
ARTIFACT_HELPERS_TEMPLATE = _load_agent_workspace_template("artifact_helpers.py")
INSPECT_SEQUENCE_TEMPLATE = _load_agent_workspace_template("inspect_sequence.py")
INSPECT_COMPONENTS_TEMPLATE = _load_agent_workspace_template("inspect_components.py")


def _drain_stderr(proc, prefix="[super] "):
    """Read proc.stderr line-by-line and print to our stderr. Runs in a thread."""
    assert proc.stderr is not None
    for line in proc.stderr:
        print(f"{prefix}{line}", end="", file=sys.stderr, flush=True)


def run_super(
    args: list[str],
    *,
    stream: bool = False,
    output_path: Path | None = None,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> str:
    """Run a super CLI command and return the last assistant message."""
    cmd = ["super"] + args

    if stream:
        for i in range(len(cmd) - 1):
            if cmd[i] == "--output":
                if output_path is None:
                    output_path = Path(cmd[i + 1])
                break

    print(f"[harness] running: {' '.join(cmd)}", file=sys.stderr, flush=True)

    run_cwd = str(cwd) if cwd else str(PROJECT_ROOT)
    if stream:
        return _run_super_streaming(cmd, output_path, cwd=run_cwd, env=env)
    return _run_super_batch(cmd, cwd=run_cwd, env=env)


def _run_super_batch(cmd: list[str], *, cwd: str = "", env: dict[str, str] | None = None) -> str:
    """Batch mode: capture stdout+stderr and print both to harness stderr."""
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=cwd or str(PROJECT_ROOT),
        env=env,
    )
    if result.stdout.strip():
        for line in result.stdout.strip().splitlines():
            print(f"[super][stdout] {line}", file=sys.stderr, flush=True)
    if result.stderr.strip():
        for line in result.stderr.strip().splitlines():
            print(f"[super][stderr] {line}", file=sys.stderr, flush=True)
    if result.returncode != 0:
        raise RuntimeError(
            "super exited with code "
            f"{result.returncode} (stdout/stderr captured in harness log)"
        )
    return result.stdout.strip()


def _fix_streamed_transcript(text: str) -> str:
    """Normalize streamed transcript text without mutating markdown structure."""
    return text


def _remove_stream_sync_path(path: Path) -> None:
    if not path.exists() and not path.is_symlink():
        return
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
        return
    for child in path.iterdir():
        _remove_stream_sync_path(child)
    path.rmdir()


def _read_stream_session_conversation_id(output_path: Path) -> str | None:
    try:
        text = output_path.read_text()
    except Exception:
        return None
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:80]:
        if line.strip() == "---":
            break
        match = re.match(r"^\s*conversation_id\s*:\s*(.+?)\s*$", line)
        if match:
            return match.group(1).strip().strip("\"'")
    return None


def _sync_live_stream_conversation_artifacts(output_path: Path, cwd: str) -> None:
    conversation_id = _read_stream_session_conversation_id(output_path)
    if not conversation_id:
        return

    run_dir = Path(cwd or PROJECT_ROOT)
    source_dir = run_dir / ".ai-supervisor" / "conversations" / conversation_id
    forks_src = source_dir / "forks"
    if not forks_src.exists():
        return

    export_root = output_path.parent / "forks"
    temp_root = output_path.parent / ".forks.tmp"
    _remove_stream_sync_path(temp_root)
    temp_root.mkdir(parents=True, exist_ok=True)

    index_src = source_dir / "index.json"
    if index_src.exists():
        (temp_root / "index.json").symlink_to(index_src)
    for fork_path in sorted(forks_src.glob("*.json")):
        (temp_root / fork_path.name).symlink_to(fork_path)

    _remove_stream_sync_path(export_root)
    temp_root.rename(export_root)


def _poll_live_stream_conversation_artifacts(
    stop_event: threading.Event,
    output_path: Path,
    cwd: str,
) -> None:
    while not stop_event.wait(0.25):
        _sync_live_stream_conversation_artifacts(output_path, cwd)


def _run_super_streaming(
    cmd: list[str],
    output_path: Path | None,
    *,
    cwd: str = "",
    env: dict[str, str] | None = None,
) -> str:
    """Streaming mode: tee stdout to stderr for display, capture transcript."""
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=cwd or str(PROJECT_ROOT),
        env=env,
    )

    stderr_thread = threading.Thread(target=_drain_stderr, args=(proc,), daemon=True)
    stderr_thread.start()
    artifact_stop_event = threading.Event()
    artifact_thread = None
    if output_path is not None:
        artifact_thread = threading.Thread(
            target=_poll_live_stream_conversation_artifacts,
            args=(artifact_stop_event, output_path, cwd or str(PROJECT_ROOT)),
            daemon=True,
        )
        artifact_thread.start()

    chunks: list[str] = []
    assert proc.stdout is not None
    while True:
        chunk = proc.stdout.read(256)
        if not chunk:
            break
        chunks.append(chunk)
        sys.stderr.write(chunk)
        sys.stderr.flush()

    proc.wait()
    artifact_stop_event.set()
    stderr_thread.join(timeout=2)
    if artifact_thread is not None:
        artifact_thread.join(timeout=1)

    transcript = _fix_streamed_transcript("".join(chunks))

    if proc.returncode != 0:
        raise RuntimeError(f"super exited with code {proc.returncode}")

    if output_path is not None:
        output_path.write_text(transcript)
        _sync_live_stream_conversation_artifacts(output_path, cwd or str(PROJECT_ROOT))

    return extract_last_assistant_message(transcript)


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _terminate_pid(pid: int, *, timeout_s: float = 1.5) -> bool:
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return True
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if not _pid_exists(pid):
            return True
        time.sleep(0.05)
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        return True
    time.sleep(0.05)
    return not _pid_exists(pid)


def _read_pid_cmdline(pid: int) -> str:
    cmdline_path = Path("/proc") / str(pid) / "cmdline"
    try:
        raw = cmdline_path.read_bytes()
    except Exception:
        return ""
    return raw.replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()


def _collect_active_run_ids(project_root: Path) -> set[str]:
    run_ids: set[str] = set()
    try:
        ps = subprocess.run(
            ["ps", "-eo", "args="],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return run_ids
    if ps.returncode != 0:
        return run_ids
    for line in ps.stdout.splitlines():
        if "harness.py" not in line and "run-config.ts" not in line:
            continue
        for match in re.finditer(r"/runs/([^/\s]+)/", line):
            run_ids.add(match.group(1))
        session_match = re.search(r"--session-name\s+([^\s]+)", line)
        if session_match:
            run_ids.add(session_match.group(1))
    return run_ids


def cleanup_orphan_repl_daemons(
    project_root: Path,
    *,
    preserve_run_ids: set[str] | None = None,
) -> dict[str, int]:
    """Best-effort cleanup for leaked arc_repl daemons from inactive runs."""
    preserve = set(preserve_run_ids or set())
    active_run_ids = _collect_active_run_ids(project_root).union(preserve)
    runs_root = project_root / "runs"
    if not runs_root.exists():
        return {"killed": 0, "stale_files_removed": 0, "skipped_active": 0}

    killed = 0
    stale_files_removed = 0
    skipped_active = 0

    for pid_file in runs_root.glob("*/supervisor/arc/repl-sessions/*/daemon.pid"):
        try:
            run_id = pid_file.relative_to(runs_root).parts[0]
        except Exception:
            continue
        if run_id in active_run_ids:
            skipped_active += 1
            continue
        try:
            pid_raw = pid_file.read_text().strip()
            pid = int(pid_raw)
        except Exception:
            try:
                pid_file.unlink()
                stale_files_removed += 1
            except Exception:
                pass
            continue

        cmdline = _read_pid_cmdline(pid)
        if not cmdline:
            try:
                pid_file.unlink()
                stale_files_removed += 1
            except Exception:
                pass
            continue
        if "arc_repl.py" not in cmdline or "--daemon" not in cmdline:
            continue
        if _terminate_pid(pid):
            killed += 1
            try:
                pid_file.unlink()
            except Exception:
                pass
    return {
        "killed": killed,
        "stale_files_removed": stale_files_removed,
        "skipped_active": skipped_active,
    }


def parse_args():
    return parse_args_impl()


def setup_run_dir(
    run_dir: Path,
    agent_dir: Path,
    supervisor_dir: Path,
    log,
    *,
    game_id: str = "game",
) -> None:
    setup_run_dir_impl(
        run_dir,
        agent_dir,
        supervisor_dir,
        log,
        level_completions_template=LEVEL_COMPLETIONS_TEMPLATE,
        play_lib_template=PLAY_LIB_TEMPLATE,
        model_lib_template=MODEL_LIB_TEMPLATE,
        theory_template=THEORY_TEMPLATE,
        model_template=MODEL_TEMPLATE,
        play_template=PLAY_TEMPLATE,
        artifact_helpers_template=ARTIFACT_HELPERS_TEMPLATE,
        inspect_sequence_template=INSPECT_SEQUENCE_TEMPLATE,
        inspect_components_template=INSPECT_COMPONENTS_TEMPLATE,
        game_id=game_id,
    )


def setup_run_config_dir(run_config_dir: Path) -> tuple[Path, Path]:
    return setup_run_config_dir_impl(
        run_config_dir,
        project_root=PROJECT_ROOT,
        project_venv_python=PROJECT_VENV_PYTHON,
    )


def seed_arc_environment_cache(
    arc_env_dir: Path,
    *,
    requested_game_id: str,
) -> Path:
    return seed_arc_environment_cache_impl(
        arc_env_dir,
        requested_game_id=requested_game_id,
        cache_root=ARC_ENV_CACHE_ROOT,
    )


def assert_no_game_files_in_agent_dir(agent_dir: Path) -> None:
    assert_no_game_files_in_agent_dir_impl(agent_dir)


def main() -> None:
    def _handle_termination(signum, _frame):
        signame = signal.Signals(signum).name
        print(
            f"[harness] received signal {signame}; terminating",
            file=sys.stderr,
            flush=True,
        )
        raise SystemExit(128 + signum)

    for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(sig, _handle_termination)
    run_main(sys.modules[__name__])


if __name__ == "__main__":
    main()
