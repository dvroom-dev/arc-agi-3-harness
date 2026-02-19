# arc-agi-3-toolkit

Sibling project for ARC-AGI-3 harness experiments using package imports (`arc-agi`) instead of a full source checkout.

## What is included
- `harness.py`: super-driven run loop
- `tools/arc_action.py`: JSON CLI backend for action execution
- `super.yaml`: agent/supervisor prompts + mode logic
- `game_state.py`: state rendering/diff helpers

## Runtime model
- `arc_action` uses `ARC_OPERATION_MODE` (`NORMAL` default, supports `ONLINE` and `OFFLINE`).
- Harness sets:
  - `ARC_OPERATION_MODE` from `--operation-mode`
  - `ARC_ENVIRONMENTS_DIR` to `/tmp/arc-agi-env-cache/<session>` (outside agent/supervisor filesystems)
  - `ARC_STATE_DIR` to `runs/<session>/supervisor/arc`
- CLI commands exposed via config filesystem `PATH`:
  - `arc_action` (status/reset/run_script)
  - `arc_get_state` (read current state JSON/grid)
  - `arc_action run_script` accepts script content on stdin only (heredoc/pipe).
- Harness now stages run-local command wrappers in `runs/<session>/config/bin` and run-local tool copies in `runs/<session>/config/tools`, so agent shell commands do not reference project-root executables.
- Agent workspace is per-run `runs/<session>/agent`.
- Supervisor workspace is per-run `runs/<session>/supervisor`.

## Quick smoke
```bash
uv sync
source .env
. .venv/bin/activate
python harness.py --game-id ls20 --max-turns 2 --session-name smoke-minimal
```
