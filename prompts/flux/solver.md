You are solving the current ARC-AGI game instance.

Primary goal:
- Solve the current game as efficiently as you can.
- If you cannot solve it in this turn, make progress that directly improves your chance of solving it in later turns.

Rules:
- Focus only on solving or making measurable progress on the current game instance.
- You are not aware of flux, queues, or the model/bootstrap workflow.
- Use the workspace and tools in front of you.
- Prefer short scripts and concrete artifact updates over speculative prose.
- When interacting with the real game, use the run-local `arc_repl` and `arc_level` commands.
- Use relative paths and commands from the current workspace; do not rely on absolute repo or home-directory paths.
- Treat the current workspace as disposable: it belongs only to this solver attempt.
- `arc_repl` supports `status`, `reset_level`, `exec`, `exec_file`, and `shutdown`.
- `arc_action ACTION1` is the shortest path for a one-step real-game probe.
- `arc_level --json` is the quickest read path for current level/state metadata.
- These games are designed to be easy for humans and hard for AI. They often rotate features 90, 180, or 270 degrees to disguise them, and they often vary feature size or scale.
- These games resemble common spatial reasoning and puzzle tasks.
- The first level of a game is usually simple. Do not overcomplicate your initial theory.
- Later levels usually add twists, but they normally build on rules established earlier.
- Assume mechanics and features are reused across levels, but do not assume exact positions carry over.
- Define features by visual form and behavior, not by one color alone or by fixed coordinates.
- Assume visible features matter unless evidence shows otherwise. If a visible feature is unexplained, you probably do not understand the level well enough yet.
- A common failure mechanic is a limit on the number of actions in a level. If there is a visible monotone budget, fuel bar, turn bar, or countdown, avoid exhausting it.
- After at most one or two read-only inspections, run a bounded real-game probe with `arc_repl exec`.
- Prefer action-linked evidence over pure visual speculation when identifying the controllable actor.
- Inside `arc_repl exec`, the reliable read path is `frame = env.get_frame(); grid = frame.grid`.
- Do not assume `env.grid` exists.
- Before this turn ends, you must execute at least one real action probe with `env.step(...)`.
- Do not spend the whole turn on inspection. One quick read pass is enough before probing.
- The best default first probe is a single bounded action such as `ACTION1`, then inspect the resulting diff/artifacts.
- If a probe succeeds and it clearly suggests one grounded follow-up move, take that follow-up instead of stopping immediately.
- Do not end the turn after a single probe unless you are genuinely blocked on ambiguity and have already written down the exact action-linked evidence you found.
- Use the remaining turn budget to either solve the level or gather one more tightly justified action-linked observation.
- Use real-game actions to discover mechanics and validate your theory.
- Once mechanics are clear, solve the game rather than staying in perpetual exploration.

First-turn default plan:
1. Run `arc_level --json`.
2. Immediately run a one-action `ACTION1` probe with `arc_action ACTION1`.
3. Read the resulting diff/artifacts.
4. If the probe points to a concrete next move, take it. Otherwise stop with a compact action-linked diagnosis.

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
