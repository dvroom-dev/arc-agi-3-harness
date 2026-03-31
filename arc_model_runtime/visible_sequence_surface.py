from __future__ import annotations

import shutil
from pathlib import Path


def preserve_local_sequence_surface(
    *,
    game_dir: Path,
    temp_level_current: Path,
    visible_level: int,
) -> None:
    candidate_roots = [
        game_dir / "level_current",
        game_dir / f"level_{int(visible_level)}",
    ]
    for candidate_root in candidate_roots:
        sequences_dir = candidate_root / "sequences"
        if not sequences_dir.exists() or not sequences_dir.is_dir():
            continue
        destination = temp_level_current / "sequences"
        if destination.exists() or destination.is_symlink():
            if destination.is_dir() and not destination.is_symlink():
                shutil.rmtree(destination, ignore_errors=True)
            else:
                destination.unlink(missing_ok=True)
        shutil.copytree(sequences_dir, destination)
        return
