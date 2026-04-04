from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import harness_flux
from harness_flux import _launch_flux, _read_flux_state_status, _render_flux_config, _write_initial_seed_bundle


def test_write_initial_seed_bundle_creates_empty_bundle(tmp_path: Path) -> None:
    bundle_path = _write_initial_seed_bundle(tmp_path)
    payload = json.loads(bundle_path.read_text())
    assert payload["version"] == 1
    assert payload["syntheticMessages"] == []
    assert payload["replayPlan"] == []


def test_render_flux_config_includes_durable_workspace() -> None:
    runtime = SimpleNamespace(
        args=SimpleNamespace(provider=None),
        run_dir=Path("/tmp/flux-run"),
        active_agent_dir=lambda: Path("/tmp/flux-run/agent/game_ls20"),
    )
    text = _render_flux_config(runtime)
    assert "working_directory: agent/game_ls20" in text
    assert "output_schema: model_update_v1" in text
    assert "check_model.py" in text
    assert "rehearse_seed_on_model.py" in text
    assert "replay_seed_on_real_game.py" in text
    assert "output_schema: bootstrap_seed_decision_v1" in text
    assert "runtime_defaults:\n  provider: codex" in text
    assert "modeler:\n  prompt_file:" in text
    assert "  provider: codex" in text


def test_render_flux_config_keeps_mock_provider_coherent() -> None:
    runtime = SimpleNamespace(
        args=SimpleNamespace(provider="mock"),
        run_dir=Path("/tmp/flux-run"),
        active_agent_dir=lambda: Path("/tmp/flux-run/agent/game_ls20"),
    )
    text = _render_flux_config(runtime)
    assert "runtime_defaults:\n  provider: mock" in text
    assert "modeler:\n  prompt_file:" in text
    assert "  provider: mock" in text


def test_flux_yaml_template_exists() -> None:
    assert Path("flux.yaml").exists()


def test_read_flux_state_status_parses_stop_state(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"status": "stopped", "stopRequested": True}), encoding="utf-8")
    status, stop_requested = _read_flux_state_status(state_path)
    assert status == "stopped"
    assert stop_requested is True


def test_read_flux_state_status_handles_bad_json(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text("{bad", encoding="utf-8")
    status, stop_requested = _read_flux_state_status(state_path)
    assert status is None
    assert stop_requested is False


def test_launch_flux_reaps_stopped_child_even_with_partial_stdout(tmp_path: Path, monkeypatch) -> None:
    run_dir = tmp_path / "run"
    (run_dir / "flux" / "logs").mkdir(parents=True, exist_ok=True)
    state_path = run_dir / "flux" / "state.json"
    state_path.write_text(json.dumps({"status": "running", "stopRequested": False}), encoding="utf-8")

    child_script = tmp_path / "child.py"
    child_script.write_text(
        "import signal\n"
        "import sys\n"
        "import time\n"
        "signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))\n"
        "sys.stdout.write('partial-without-newline')\n"
        "sys.stdout.flush()\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )

    real_popen = subprocess.Popen

    def fake_popen(*_args, **kwargs):
        return real_popen([sys.executable, str(child_script)], **kwargs)

    monkeypatch.setattr(harness_flux.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(harness_flux, "FLUX_STOP_TERMINATE_GRACE_SECONDS", 0.1)
    monkeypatch.setattr(harness_flux, "FLUX_STOP_KILL_GRACE_SECONDS", 0.1)

    def mark_stopped() -> None:
        time.sleep(0.05)
        state_path.write_text(json.dumps({"status": "stopped", "stopRequested": True}), encoding="utf-8")

    stopper = threading.Thread(target=mark_stopped, daemon=True)
    stopper.start()

    runtime = SimpleNamespace(
        run_dir=run_dir,
        super_env={},
        log=lambda _message: None,
    )
    started_at = time.monotonic()
    rc = _launch_flux(runtime, run_dir / "flux.yaml")
    elapsed = time.monotonic() - started_at

    assert elapsed < 3
    assert rc == 0
    launcher_log = (run_dir / "flux" / "logs" / "launcher.log").read_text(encoding="utf-8")
    assert "sending SIGTERM" in launcher_log
    assert "partial-without-newline" in launcher_log
