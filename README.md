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
  - `ARC_ENVIRONMENTS_DIR` to `<project>/environment_files` (outside agent run cwd)
  - `ARC_STATE_DIR` to `runs/<session>/supervisor/arc` (outside agent workspace)
- CLI commands exposed via config filesystem `PATH`:
  - `arc_action` (status/reset/run_script)
  - `arc_get_state` (read current state JSON/grid)
- Agent workspace is per-run `runs/<session>/agent`.
- Supervisor workspace is per-run `runs/<session>/supervisor`.

## Quick smoke
```bash
uv sync
source .env
. .venv/bin/activate
python harness.py --game-id ls20 --max-turns 2 --session-name smoke-minimal
```
