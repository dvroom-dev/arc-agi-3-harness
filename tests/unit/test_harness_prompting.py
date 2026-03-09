from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import harness_runtime_prompting


def test_metadata_matches_game_id_accepts_slug_and_hashed_variant() -> None:
    assert harness_runtime_prompting._metadata_matches_game_id("ls20-cb3b57cc", "ls20")
    assert harness_runtime_prompting._metadata_matches_game_id("ls20-cb3b57cc", "ls20-cb3b57cc")
    assert not harness_runtime_prompting._metadata_matches_game_id("ft09-abcd1234", "ls20")


def test_render_prompt_actions_block_excludes_reset_and_unknown_actions() -> None:
    text = harness_runtime_prompting.render_prompt_actions_block_impl([0, 1, 4, 6])
    assert "`ACTION1`" in text
    assert "`ACTION4`" in text
    assert "`ACTION6`" in text
    assert "- `RESET`:" not in text
    assert "arc_repl reset_level" in text


def test_update_prompt_game_vars_sets_action_prompt_fields(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        harness_runtime_prompting,
        "resolve_prompt_available_action_ids_impl",
        lambda game_id, search_roots: [1, 2, 4],
    )
    runtime = SimpleNamespace(
        active_game_id="ls20-cb3b57cc",
        args=SimpleNamespace(game_id="ls20-cb3b57cc"),
        agent_dir=tmp_path / "agent",
        arc_env_dir=tmp_path / "run-cache",
        deps=SimpleNamespace(ARC_ENV_CACHE_ROOT=tmp_path / "global-cache"),
        prompt_game_id="",
        prompt_game_slug="",
        prompt_game_dir="",
        prompt_available_actions=[],
        prompt_actions_block="",
        prompt_actions_game_id=None,
    )

    harness_runtime_prompting.update_prompt_game_vars_impl(runtime)

    assert runtime.prompt_game_id == "ls20-cb3b57cc"
    assert runtime.prompt_game_slug == "ls20"
    assert runtime.prompt_available_actions == [1, 2, 4]
    assert runtime.prompt_game_dir.endswith("agent/game_ls20")
    assert "`ACTION1`" in runtime.prompt_actions_block
    assert "`ACTION2`" in runtime.prompt_actions_block
    assert "`ACTION4`" in runtime.prompt_actions_block
    assert "Do not invent or call unavailable actions." in runtime.prompt_actions_block


def test_update_prompt_game_vars_falls_back_to_state_actions(
    monkeypatch,
    tmp_path: Path,
) -> None:
    def fail(*_args, **_kwargs):
        raise RuntimeError("no local env")

    monkeypatch.setattr(
        harness_runtime_prompting,
        "resolve_prompt_available_action_ids_impl",
        fail,
    )
    runtime = SimpleNamespace(
        active_game_id="ls20-gamehash",
        args=SimpleNamespace(game_id="ls20"),
        agent_dir=tmp_path / "agent",
        arc_env_dir=tmp_path / "run-cache",
        deps=SimpleNamespace(ARC_ENV_CACHE_ROOT=tmp_path / "global-cache"),
        prompt_game_id="",
        prompt_game_slug="",
        prompt_game_dir="",
        prompt_available_actions=[],
        prompt_actions_block="",
        prompt_actions_game_id=None,
        load_state=lambda: {"available_actions": [0, 1, 2, 4]},
    )

    harness_runtime_prompting.update_prompt_game_vars_impl(runtime)

    assert runtime.prompt_available_actions == [1, 2, 4]
    assert "`ACTION1`" in runtime.prompt_actions_block
    assert "`ACTION2`" in runtime.prompt_actions_block
    assert "`ACTION4`" in runtime.prompt_actions_block
