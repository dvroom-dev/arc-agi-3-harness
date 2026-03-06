from __future__ import annotations

import re
from pathlib import Path

import numpy as np


def update_prompt_game_vars_impl(runtime) -> None:
    raw_game_id = str(runtime.active_game_id or runtime.args.game_id or "").strip()
    runtime.prompt_game_id = raw_game_id
    slug_source = raw_game_id.split("-", 1)[0] if raw_game_id else ""
    safe_slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", slug_source).strip("._")
    if not safe_slug:
        safe_slug = "game"
    runtime.prompt_game_slug = safe_slug
    runtime.prompt_game_dir = f"game_{safe_slug}"


def load_current_pixels_impl(runtime) -> np.ndarray | None:
    grid_path = runtime.arc_state_dir / "current_grid.npy"
    if not grid_path.exists():
        return None
    try:
        return np.load(grid_path)
    except Exception as exc:
        raise RuntimeError(f"Failed to load current grid file: {grid_path}: {exc}") from exc


def prompt_args_impl(
    runtime,
    prompt_text: str,
    *,
    prompt_kind: str,
    image_paths: list[Path] | None = None,
) -> list[str]:
    if image_paths:
        runtime.prompt_file_counter += 1
        prompt_file = runtime.session_dir / f"{prompt_kind}.prompt.{runtime.prompt_file_counter:04d}.yaml"
        runtime.deps.write_prompt_file(prompt_file, prompt_text, image_paths=image_paths)
        return ["--prompt-file", str(prompt_file)]
    return ["--prompt", prompt_text]
