from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import harness_runtime_images


def test_level_start_prompt_images_renders_once_per_level(tmp_path: Path) -> None:
    game_dir = tmp_path / "agent" / "game_ls20" / "level_current"
    game_dir.mkdir(parents=True)
    (game_dir / "meta.json").write_text('{"level": 2}\n', encoding="utf-8")
    (game_dir / "initial_state.hex").write_text("0123\n4567\n", encoding="utf-8")

    runtime = SimpleNamespace(
        prompt_image_dir=tmp_path / "prompt_images",
        prompt_image_attached_levels=set(),
        active_agent_dir=lambda: tmp_path / "agent" / "game_ls20",
    )

    first = harness_runtime_images.level_start_prompt_images_impl(runtime, {"current_level": 2})
    assert len(first) == 1
    assert first[0].exists()

    second = harness_runtime_images.level_start_prompt_images_impl(runtime, {"current_level": 2})
    assert second == []


def test_ensure_level_start_prompt_image_requires_initial_hex(tmp_path: Path) -> None:
    game_dir = tmp_path / "agent" / "game_ls20" / "level_current"
    game_dir.mkdir(parents=True)
    (game_dir / "meta.json").write_text('{"level": 1}\n', encoding="utf-8")

    runtime = SimpleNamespace(
        prompt_image_dir=tmp_path / "prompt_images",
        prompt_image_attached_levels=set(),
        active_agent_dir=lambda: tmp_path / "agent" / "game_ls20",
    )

    try:
        harness_runtime_images.ensure_level_start_prompt_image_impl(runtime, level=1)
    except RuntimeError as exc:
        assert "missing initial state hex" in str(exc)
    else:
        raise AssertionError("expected missing initial state error")
