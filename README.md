# arc-agi-3-toolkit

Sibling project for ARC-AGI-3 harness experiments using package imports (`arc-agi`) instead of a full source checkout.

## What is included
- `harness.py`: super-driven run loop
- `tools/arc_repl.py`: conversation-scoped stateful Python REPL backend
- `super.yaml`: agent/supervisor prompts + mode logic
- `game_state.py`: state rendering/diff helpers

## Runtime model
- `arc_repl` uses `ARC_OPERATION_MODE` (`NORMAL` default, supports `ONLINE` and `OFFLINE`).
- Harness sets:
  - `ARC_OPERATION_MODE` from `--operation-mode`
  - `ARC_ENVIRONMENTS_DIR` to `/tmp/arc-agi-env-cache/<session>` (outside agent/supervisor filesystems)
  - `ARC_STATE_DIR` to `runs/<session>/supervisor/arc`
  - `ARC_CONVERSATION_ID` per `super` conversation frontmatter (so REPL state resets on conversation fork)
- CLI commands exposed via config filesystem `PATH`:
  - `arc_repl` (status/reset_level/exec/shutdown)
  - `arc_repl exec` accepts script content on stdin only (heredoc/pipe).
- `arc_repl exec` interface:
  - Persistent globals per conversation: `env`, `current`, `GameAction`, `GA`, `diff()`, `get_state()`, and helpers from `agent_lib.py`.
  - `diff(before, after, output=\"json\"|\"text\", pad=0)`:
    - `json`: changed-pixel summary plus `before`/`after` chunks
    - `text`: explicit per-cell transitions
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
