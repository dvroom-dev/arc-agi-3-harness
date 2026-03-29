from __future__ import annotations

import json
from pathlib import Path

import numpy as np


def _read_hex_grid(path: Path) -> np.ndarray:
    rows = [line.strip().upper() for line in path.read_text().splitlines() if line.strip()]
    return np.array([[int(ch, 16) for ch in row] for row in rows], dtype=np.int8)


def _current_level_from_meta(game_dir: Path) -> int:
    meta_path = game_dir / "level_current" / "meta.json"
    if not meta_path.exists():
        raise RuntimeError(f"missing level metadata for prompt image generation: {meta_path}")
    payload = json.loads(meta_path.read_text())
    return int(payload.get("level"))


def _sdk_render_grid_to_image(pixels: np.ndarray, dest: Path) -> None:
    from PIL import Image
    from arc_agi.rendering import frame_to_rgb_array

    rgb = frame_to_rgb_array(0, pixels, scale=4)
    Image.fromarray(rgb).save(dest)


def ensure_level_start_prompt_image_impl(runtime, *, level: int | None = None) -> Path:
    game_dir = runtime.active_agent_dir()
    current_level = int(level) if level is not None else _current_level_from_meta(game_dir)
    initial_hex = game_dir / "level_current" / "initial_state.hex"
    if not initial_hex.exists():
        raise RuntimeError(f"missing initial state hex for prompt image generation: {initial_hex}")
    dest = runtime.prompt_image_dir / f"level_{current_level:03d}_initial.png"
    if dest.exists():
        return dest
    runtime.prompt_image_dir.mkdir(parents=True, exist_ok=True)
    pixels = _read_hex_grid(initial_hex)
    _sdk_render_grid_to_image(pixels, dest)
    return dest


def level_start_prompt_images_impl(runtime, state: dict | None) -> list[Path]:
    if not isinstance(state, dict):
        return []
    try:
        level = int(state.get("current_level", 0) or 0)
    except Exception:
        level = 0
    if level <= 0:
        return []
    if level in runtime.prompt_image_attached_levels:
        return []
    try:
        image_path = ensure_level_start_prompt_image_impl(runtime, level=level)
    except RuntimeError as exc:
        if hasattr(runtime, "log"):
            runtime.log(f"[harness] prompt image unavailable for level {level}: {exc}")
        return []
    runtime.prompt_image_attached_levels.add(level)
    return [image_path]
