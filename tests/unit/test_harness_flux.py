from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from harness_flux import _render_flux_config, _write_initial_seed_bundle


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


def test_flux_yaml_template_exists() -> None:
    assert Path("flux.yaml").exists()
