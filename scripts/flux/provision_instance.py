from __future__ import annotations

from pathlib import Path

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
    write_json_stdout(
        {
            "instance_id": raw_instance_id,
            "working_directory": str(solver_dir),
            "prompt_text": (
                f"Game: {meta['game_id']}\n"
                f"Initial status: {summary['summary']}\n"
                f"arc_repl_status: {status}"
            ),
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
