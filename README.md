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
  - Persistent globals per conversation: `env`, `current`, `GameAction`, `GA`, `diff()`, `get_state()`, and helpers from `play_lib.py`.
  - Persistent action-history globals:
    - `get_action_history(level=None, action_name=None, since=None, until=None, last=None) -> list[dict]`
    - `get_action_record(action_index: int) -> dict | None`
    - Records are game-scoped for the current run and include:
      - `state_before` (full state snapshot incl `grid_hex_rows`)
      - `state_after` (full state snapshot incl `grid_hex_rows`)
      - `diff` (per-action diff payload)
      - action metadata (`action_index`, `action_name`, `tool_turn`, `step_in_call`, level metadata)
    - On level transitions, cross-level diffs are suppressed in-record:
      - `diff.suppressed_cross_level_diff = true`
      - inspect `state_before` / `state_after` directly for transition context
  - `get_state()` grid payload is `grid_hex_rows` (not `grid`).
  - Action enum members are `GameAction.ACTION1..ACTION7` plus `RESET`.
  - `diff(before, after, output=\"json\"|\"text\", pad=0)`:
    - `json`: changed-pixel summary plus `before`/`after` chunks
    - `text`: explicit per-cell transitions
  - Action-history records are persisted at:
    - `${ARC_STATE_DIR}/action-history.json`

Example:
```bash
arc_repl exec --game-id ls20 <<'PY'
env.step(GameAction.ACTION4)
env.step(GameAction.ACTION1)
recent = get_action_history(last=2)
print([{"idx": r["action_index"], "action": r["action_name"]} for r in recent])
r1 = get_action_record(1)
print(bool(r1), sorted(r1.keys()) if r1 else [])
PY
```
- Harness now stages run-local command wrappers in `runs/<session>/config/bin` and run-local tool copies in `runs/<session>/config/tools`, so agent shell commands do not reference project-root executables.
- Agent workspace is per-run `runs/<session>/agent`.
- Supervisor workspace is per-run `runs/<session>/supervisor`.

## Quick smoke
```bash
uv sync
source .env
. .venv/bin/activate
python harness.py --game-id ls20 --max-turns 2 --session-name smoke-minimal

# Multiple games under one scorecard
python harness.py --game-ids "ls20 ft09 vc33" --operation-mode ONLINE --open-scorecard --session-name batch-smoke
```

## Checks
```bash
make lint
make test
```

## Actor-identification note (important)
- Do not identify the controllable actor from visual salience alone.
- Identify actor(s) from action-linked evidence: whichever component consistently moves under directional actions is the actor.
- Static markers/symbols that do not move under directional actions are environment features, not the actor.
