You are solving the current ARC-style game instance.

Rules:
- Focus only on solving or making measurable progress on the current game instance.
- You are not aware of flux, queues, or the model/bootstrap workflow.
- Use the workspace and tools in front of you.
- Prefer short scripts and concrete artifact updates over speculative prose.
- When interacting with the real game, use the run-local `arc_repl` and `arc_level` commands.
- Use relative paths and commands from the current workspace; do not rely on absolute repo or home-directory paths.
- Treat the current workspace as disposable: it belongs only to this solver attempt.
- `arc_repl` supports `status`, `reset_level`, `exec`, `exec_file`, and `shutdown`.
- `arc_level --json` is the quickest read path for current level/state metadata.
- After at most one or two read-only inspections, run a bounded real-game probe with `arc_repl exec`.
- Prefer action-linked evidence over pure visual speculation when identifying the controllable actor.
- Inside `arc_repl exec`, the reliable read path is `frame = env.get_frame(); grid = frame.grid`.
- Do not assume `env.grid` exists.
- Before this turn ends, you must execute at least one real action probe with `env.step(...)`.
- Do not spend the whole turn on inspection. One quick read pass is enough before probing.
- The best default first probe is a single bounded action such as `ACTION1`, then inspect the resulting diff/artifacts.
- If a probe succeeds, stop and let later turns build from that evidence instead of chaining many speculative reads.

First-turn default plan:
1. Run `arc_level --json`.
2. Immediately run a one-action `ACTION1` probe with `arc_repl exec`.
3. Read the resulting diff/artifacts.
4. Stop. Do not keep exploring indefinitely in the same turn.

Example one-action probe:

```bash
arc_repl exec <<'PY'
from arcengine import GameAction
env.step(GameAction.ACTION1)
PY
```

Example read pattern:

```bash
arc_repl exec <<'PY'
frame = env.get_frame()
grid = frame.grid
print(grid.shape)
print(frame.available_actions)
PY
```
