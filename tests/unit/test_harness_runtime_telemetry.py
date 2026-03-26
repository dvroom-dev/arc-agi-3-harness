from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from harness_runtime_telemetry import phase_scope_impl


def _make_runtime(tmp_path: Path):
    run_dir = tmp_path / "runs" / "telemetry-smoke"
    return SimpleNamespace(
        telemetry_dir=run_dir / "telemetry",
        phase_timings_path=run_dir / "telemetry" / "harness_phases.ndjson",
        session_name="telemetry-smoke",
        args=SimpleNamespace(game_id="ls20"),
        active_game_id="ls20-cb3b57cc",
        active_scorecard_id=None,
    )


def test_phase_scope_writes_success_entry(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)

    with phase_scope_impl(runtime, category="super", name="resume", metadata={"prompted": False}) as phase:
        phase["turn"] = 3

    lines = runtime.phase_timings_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["category"] == "super"
    assert entry["name"] == "resume"
    assert entry["ok"] is True
    assert entry["meta"]["turn"] == 3


def test_phase_scope_writes_failure_entry(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)

    try:
        with phase_scope_impl(runtime, category="tool", name="arc_repl"):
            raise RuntimeError("boom")
    except RuntimeError:
        pass

    entry = json.loads(runtime.phase_timings_path.read_text(encoding="utf-8").strip())
    assert entry["category"] == "tool"
    assert entry["name"] == "arc_repl"
    assert entry["ok"] is False
    assert "RuntimeError: boom" in entry["error"]


def test_phase_scope_writes_canonical_last_error_artifact(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)

    class DetailedError(RuntimeError):
        def __init__(self):
            super().__init__("super exited with code 1: real detail")
            self.detail = "real detail"
            self.process_name = "super"
            self.return_code = 1

    try:
        with phase_scope_impl(runtime, category="super", name="resume"):
            raise DetailedError()
    except DetailedError:
        pass

    payload = json.loads((runtime.telemetry_dir / "last_error.json").read_text(encoding="utf-8"))
    assert payload["category"] == "super"
    assert payload["name"] == "resume"
    assert payload["error"] == "DetailedError: super exited with code 1: real detail"
    assert payload["meta"]["detail"] == "real detail"
    assert payload["meta"]["process_name"] == "super"
    assert payload["meta"]["return_code"] == 1


def test_phase_scope_clears_canonical_last_error_after_later_success(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)

    try:
        with phase_scope_impl(runtime, category="wrapup", name="certify_or_block_transition"):
            raise RuntimeError("stale failure")
    except RuntimeError:
        pass

    assert (runtime.telemetry_dir / "last_error.json").exists()

    with phase_scope_impl(runtime, category="wrapup", name="certify_or_block_transition"):
        pass

    assert not (runtime.telemetry_dir / "last_error.json").exists()
