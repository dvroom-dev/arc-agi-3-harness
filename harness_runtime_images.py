from __future__ import annotations

import shutil

import numpy as np


def level_start_prompt_images_impl(runtime, state: dict | None, *, initial: bool = False) -> list:
    if not runtime.enable_level_start_images:
        return []
    if not state:
        raise RuntimeError(
            "Cannot determine level-start prompt image: state is unavailable."
        )
    try:
        level = int(state.get("current_level", 0) or 0)
    except Exception:
        raise RuntimeError(
            "Cannot determine level-start prompt image: invalid current_level in state."
        )
    if level <= 0:
        raise RuntimeError(
            f"Cannot determine level-start prompt image: invalid current_level={level}."
        )

    per_level_image = runtime.level_start_images_dir / f"level_{level:02d}-start.png"
    if not per_level_image.exists():
        pixels = runtime.load_current_pixels()
        if pixels is None:
            raise RuntimeError(
                "Unable to generate level-start image: missing current grid "
                f"at {runtime.arc_state_dir / 'current_grid.npy'}."
            )
        try:
            runtime.deps.render_grid_to_image(
                np.array(pixels),
                per_level_image,
                scale=8,
                grid_lines=False,
            )
        except Exception as exc:
            raise RuntimeError(
                f"Failed to render level-start image for level {level}: {exc}"
            ) from exc
        if not per_level_image.exists():
            raise RuntimeError(
                f"Level-start image generation failed for level {level}: "
                f"{per_level_image} was not created."
            )

    if (
        (not runtime.current_level_start_image.exists())
        or runtime.current_level_start_image.read_bytes() != per_level_image.read_bytes()
    ):
        shutil.copyfile(per_level_image, runtime.current_level_start_image)

    should_attach = initial or (runtime.last_prompted_image_level != level)
    runtime.last_prompted_image_level = level
    return [runtime.current_level_start_image] if should_attach else []

