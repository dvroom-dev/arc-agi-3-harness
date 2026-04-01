from __future__ import annotations

from pathlib import Path

from harness_runtime_images import _read_hex_grid, _sdk_render_grid_to_image

from common import (
    build_instance_env,
    copy_solver_template,
    instance_root,
    load_runtime_meta,
    read_json_stdin,
    run_arc_repl_status,
    summarize_instance_state,
    write_json_stdout,
)


def _render_initial_prompt_image(workspace_root: str, raw_instance_id: str, solver_dir: Path) -> Path | None:
    initial_hex = solver_dir / "level_current" / "initial_state.hex"
    if not initial_hex.exists():
        return None
    prompt_image_dir = Path(workspace_root) / "prompt_images"
    prompt_image_dir.mkdir(parents=True, exist_ok=True)
    dest = prompt_image_dir / f"{raw_instance_id}_initial.png"
    if not dest.exists():
        pixels = _read_hex_grid(initial_hex)
        _sdk_render_grid_to_image(pixels, dest)
    return dest


def main() -> None:
    payload = read_json_stdin()
    workspace_root = str(payload["workspaceRoot"])
    meta = load_runtime_meta(workspace_root)
    raw_instance_id = str(payload.get("attemptId") or payload.get("seedRevisionId") or "instance")
    root = instance_root(workspace_root, raw_instance_id)
    agent_root = root / "agent"
    solver_dir = agent_root / Path(meta["solver_template_dir"]).name
    state_dir = root / "supervisor" / "arc"
    state_dir.mkdir(parents=True, exist_ok=True)
    copy_solver_template(meta, solver_dir)
    env = build_instance_env(meta, state_dir, conversation_id=raw_instance_id)
    status = run_arc_repl_status(meta, env, solver_dir)
    summary = summarize_instance_state(state_dir)
    available_actions = status.get("available_actions", [])
    prompt_image = _render_initial_prompt_image(workspace_root, raw_instance_id, solver_dir)
    write_json_stdout(
        {
            "instance_id": raw_instance_id,
            "working_directory": str(solver_dir),
            "prompt_text": (
                f"Game: {meta['game_id']}\n"
                f"Initial status: {summary['summary']}\n"
                f"Current level: {status.get('current_level')}\n"
                f"Levels completed: {status.get('levels_completed')}\n"
                f"Available actions: {available_actions}\n"
                "Use only the current workspace and run-local commands already on PATH.\n"
                "Do not construct or chase absolute filesystem paths."
            ),
            "prompt_images": [str(prompt_image)] if prompt_image else [],
            "env": env,
            "metadata": {
                "instance_root": str(root),
                "state_dir": str(state_dir),
                "solver_dir": str(solver_dir),
            },
        }
    )


if __name__ == "__main__":
    main()
