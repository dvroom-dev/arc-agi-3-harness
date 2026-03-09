from __future__ import annotations

import importlib.util
import inspect
import json
import re
from pathlib import Path

import numpy as np

ACTION_DOCS: dict[int, str] = {
    1: "Simple action - varies by game (semantically mapped to up)",
    2: "Simple action - varies by game (semantically mapped to down)",
    3: "Simple action - varies by game (semantically mapped to left)",
    4: "Simple action - varies by game (semantically mapped to right)",
    5: "Simple action - varies by game (e.g., interact, select, rotate, attach/detach, execute, etc.)",
    6: "Complex action requiring x,y coordinates (0-63 range)",
    7: "Simple action - Undo (e.g., interact, select)",
}


def _default_class_name_for_game_id(game_id: str) -> str:
    normalized = str(game_id or "").strip()
    if len(normalized) >= 4:
        first_four = normalized[:4]
        return first_four[0].upper() + first_four[1:]
    if normalized:
        return normalized[0].upper() + normalized[1:]
    return ""


def _game_id_candidates(game_id: str) -> list[str]:
    normalized = str(game_id or "").strip()
    if not normalized:
        return []
    out = [normalized]
    if "-" in normalized:
        base = normalized.split("-", 1)[0].strip()
        if base and base not in out:
            out.append(base)
    if re.fullmatch(r".+-[0-9a-f]{8}", normalized):
        base = normalized.rsplit("-", 1)[0]
        if base and base not in out:
            out.append(base)
    return out


def _metadata_matches_game_id(metadata_game_id: str, requested_game_id: str) -> bool:
    metadata_value = str(metadata_game_id or "").strip()
    if not metadata_value:
        return False
    for candidate in _game_id_candidates(requested_game_id):
        if metadata_value == candidate or metadata_value.startswith(f"{candidate}-"):
            return True
    return False


def _find_prompt_environment_metadata_impl(game_id: str, search_roots: list[Path]) -> dict[str, object]:
    candidates: list[tuple[float, Path, dict[str, object]]] = []
    seen: set[Path] = set()
    for root in search_roots:
        resolved_root = Path(root)
        if resolved_root in seen or not resolved_root.exists():
            continue
        seen.add(resolved_root)
        for metadata_path in resolved_root.rglob("metadata.json"):
            try:
                payload = json.loads(metadata_path.read_text())
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            if not _metadata_matches_game_id(str(payload.get("game_id", "")), game_id):
                continue
            payload = dict(payload)
            payload["local_dir"] = str(metadata_path.parent)
            try:
                mtime = metadata_path.parent.stat().st_mtime
            except Exception:
                mtime = metadata_path.stat().st_mtime
            candidates.append((mtime, metadata_path, payload))
    if not candidates:
        raise RuntimeError(
            f"Could not resolve local environment metadata for prompt game {game_id!r}"
        )
    candidates.sort(key=lambda item: (item[0], str(item[1])))
    return candidates[-1][2]


def _load_prompt_game_class_impl(local_dir: Path, class_name: str, game_id: str):
    from arcengine import ARCBaseGame

    candidates = [
        local_dir / f"{class_name.lower()}.py",
        local_dir / f"{class_name}.py",
    ]
    game_file = next((path for path in candidates if path.exists()), None)
    if game_file is None:
        raise RuntimeError(
            "Prompt action helper could not find game source file. Looked in: "
            + ", ".join(str(path) for path in candidates)
        )

    source_code = game_file.read_text(encoding="utf-8")
    module_name = f"arc_prompt_actions.{game_id}"
    spec = importlib.util.spec_from_loader(module_name, loader=None)
    if spec is None:
        raise RuntimeError(f"Could not create module spec for {module_name}")
    module = importlib.util.module_from_spec(spec)
    exec(source_code, module.__dict__)

    cls = getattr(module, class_name, None)
    if cls is None or not isinstance(cls, type):
        raise RuntimeError(f"Expected class `{class_name}` not found in {game_file}")
    if not issubclass(cls, ARCBaseGame):
        raise RuntimeError(f"Class `{class_name}` is not a subclass of ARCBaseGame")
    return cls


def resolve_prompt_available_action_ids_impl(game_id: str, search_roots: list[Path]) -> list[int]:
    from arcengine import ActionInput, GameAction

    payload = _find_prompt_environment_metadata_impl(game_id, search_roots)
    local_dir_value = str(payload.get("local_dir", "")).strip()
    class_name = str(payload.get("class_name", "")).strip() or _default_class_name_for_game_id(game_id)
    if not local_dir_value:
        raise RuntimeError(f"Prompt action helper found metadata without local_dir for {game_id!r}")
    if not class_name:
        raise RuntimeError(f"Prompt action helper found metadata without class_name for {game_id!r}")

    game_cls = _load_prompt_game_class_impl(Path(local_dir_value), class_name, game_id)
    sig = inspect.signature(game_cls)
    kwargs = {"seed": 0} if "seed" in sig.parameters else {}
    game = game_cls(**kwargs)
    frame = game.perform_action(ActionInput(id=GameAction.RESET), raw=True)
    available = [int(action) for action in getattr(frame, "available_actions", []) if int(action) != 0]
    if not available:
        raise RuntimeError(f"Prompt action helper found no non-RESET available actions for {game_id!r}")
    return available


def render_prompt_actions_block_impl(action_ids: list[int]) -> str:
    normalized = sorted({int(action) for action in action_ids if int(action) != 0})
    if not normalized:
        raise RuntimeError("Prompt action block requires at least one non-RESET action")

    lines = [
        "Official ARC action semantics (from https://docs.arcprize.org/actions):",
    ]
    for action_id in normalized:
        description = ACTION_DOCS.get(action_id, "Action exposed by this game")
        lines.append(f"- `ACTION{action_id}`: {description}")
    lines.extend(
        [
            "",
            "Only use the actions listed above for this game.",
            "Do not invent or call unavailable actions.",
            "Do not use `RESET` as a game action; use `arc_repl reset_level` when a reset is needed.",
        ]
    )
    return "\n".join(lines)


def _available_actions_from_runtime_state_impl(runtime) -> list[int]:
    state = None
    try:
        state = runtime.load_state()
    except Exception:
        state = None
    if not isinstance(state, dict):
        return []
    available = state.get("available_actions")
    if not isinstance(available, list):
        return []
    return sorted({int(action) for action in available if int(action) != 0})


def update_prompt_game_vars_impl(runtime) -> None:
    raw_game_id = str(runtime.active_game_id or runtime.args.game_id or "").strip()
    runtime.prompt_game_id = raw_game_id
    slug_source = raw_game_id.split("-", 1)[0] if raw_game_id else ""
    safe_slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", slug_source).strip("._")
    if not safe_slug:
        safe_slug = "game"
    runtime.prompt_game_slug = safe_slug
    runtime.prompt_game_dir = str((runtime.agent_dir / f"game_{safe_slug}").resolve())
    if getattr(runtime, "prompt_actions_game_id", None) != raw_game_id:
        resolved_actions: list[int] = []
        search_roots = [runtime.arc_env_dir, runtime.deps.ARC_ENV_CACHE_ROOT]
        try:
            resolved_actions = resolve_prompt_available_action_ids_impl(
                raw_game_id,
                search_roots,
            )
        except Exception:
            resolved_actions = _available_actions_from_runtime_state_impl(runtime)
        if resolved_actions:
            runtime.prompt_available_actions = resolved_actions
            runtime.prompt_actions_block = render_prompt_actions_block_impl(
                runtime.prompt_available_actions
            )
            runtime.prompt_actions_game_id = raw_game_id


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
