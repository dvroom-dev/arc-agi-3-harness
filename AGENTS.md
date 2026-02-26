# ARC-AGI Harness: Local Agent Rules

## Benchmark integrity is non-negotiable

Treat both the solving agent and supervisor as part of the benchmarked system. They must not receive hidden game internals, reference solutions, or cross-run leakage.

Hard rules:
- Never expose game source code or environment implementation files to agent/supervisor run filesystems.
- Never expose prior run transcripts, hidden labels, or solution artifacts to the active run.
- Never place benchmark secrets in `runs/<run-id>/agent` or `runs/<run-id>/supervisor`.
- Agent/supervisor should solve only from observable state, action interfaces, and allowed prompt context.

## Containment checklist before/after run setup changes

- Confirm run-visible trees only contain intended files for that run.
- Confirm no `environment_files`, game python sources, or copied env internals appear under run-visible trees.
- Confirm tool interfaces expose state/actions only (no direct internal object/source access).
- If uncertain whether a file leaks internals: treat it as forbidden until proven safe.

## Root cause discipline

If leakage is found, fix the setup/root cause (what gets mounted/copied into run filesystems). Do not rely on prompt warnings as primary protection.

When diagnosing solver failures, find the first turn where a wrong belief appears and trace it to the exact evidence/tool output that triggered it. Prefer action-linked movement evidence over visual salience when identifying controllable actors.

Hard rule:
- Never stop at wrapper symptoms (for example, schema validation errors) when provider/runtime failures are possible.
- Always trace to provider-level cause: inspect provider events, turn completion status, thread IDs, and stderr logs before concluding root cause.
- If provider-level evidence is missing, call that out explicitly as an observability gap and propose/add instrumentation instead of guessing.

## Prompt source of truth

Hard rule:
- Do not add hardcoded agent/supervisor prompt instructions in harness Python code.
- Harness should pass neutral runtime state only (for example: structured status/diffs/events), not policy text.
- All behavioral instructions must live in `super.yaml` (mode prompts, supervisor templates, rules), not `harness_runner.py`/other harness modules.
- If a new instruction is needed, update `super.yaml` instead of injecting freeform text from the harness.

## Run logging discipline

- Always capture both `stdout` and `stderr` for harness runs and monitoring commands.
- For background runs, use shell redirection that preserves both streams in one log file (for example: `> <logfile> 2>&1`).
- Do not declare a run diagnosis complete unless both streams were checked for failures.

## Long-run process control (Codex tool environment)

Durable monitoring must use a persistent tool session, not shell backgrounding.

Hard rules:
- Do not rely on `nohup`, `&`, or shell job control for long-running harness/super runs in this environment.
- Start long runs with `functions.exec_command` and keep the returned `session_id` alive.
- Monitor by repeatedly calling `functions.write_stdin` with empty `chars` to poll output.
- For waits/check cadence, use `write_stdin` polling with `yield_time_ms` (do not "wait" by returning control to user).
- If the process must continue while monitored, keep interacting with the same `session_id` until an explicit stop condition is met.
- If you lose the session or process exits unexpectedly, report it immediately and restart explicitly (with a new run id).

## Legacy code policy

- Delete unused legacy code aggressively when touched; do not keep dead compatibility paths around.
- If a code path is not used by the active harness flow, remove it instead of preserving it "just in case."
- Keep one canonical implementation per critical behavior (diff generation, state transitions, tool outputs); avoid duplicate logic across old/new paths.
- After cleanup, run compile/tests and verify no stale references remain.

## No silent fallback policy (harness/tooling)

Benchmark-critical features must fail loudly if broken. Do not silently degrade or no-op when these fail:
- image generation used in prompts,
- machine/state artifact reads and writes,
- tool JSON parsing/contract validation,
- environment setup and game loading.

Allowed soft-fail behavior should be rare and explicitly marked as non-critical observability only.

### Personal failure mode guardrail

I have repeatedly introduced "continue on warning" fallbacks that hid real failures and wasted benchmark runs. Do not do this.
- Never change a hard failure into a warning for scorecards, game state, or tool contracts.
- If a check proves uncertain ownership/publication/validity, stop the run immediately with a clear error.
- Prefer explicit preflight validation over permissive recovery paths.

## Pre-commit checks

- Always run lint before committing: `make lint`
- Always run tests before committing: `make test`
- If either fails, do not commit until fixed.

## Supervisor rule design (no time-travel rules)

The supervisor runs after an agent turn. It cannot undo prior actions already present in the conversation context.

Hard rules:
- Never define agent hard rules that require reversing or erasing already-completed actions.
- Never require post-hoc "fixes" that depend on undoing prior tool calls/messages in the same conversation.
- Supervisor enforcement must only target next-turn-correctable behavior.
- If a violation is already in history and cannot be changed, treat it as non-rewritable context; provide forward guidance instead of repeated rewrite loops.

## Game Rules Explained

Use this section to calibrate run analysis quality. It is for evaluator understanding only, not for injecting game-specific solving logic into prompts/harness behavior.

### LS20 (public practice game) - mechanic summary

- Core objective: transform the lower-left HUD symbol so it matches the symbol shown on the exit square (same symbol at smaller scale on exit tile).
- Player movement: directional actions move the player block.
- Turn/life system:
  - A yellow turn counter decreases with movement.
  - When it reaches zero, one red life dot is lost.
  - Losing all red life dots causes `GAME_OVER`.
- Level 1:
  - Landing on the cross rotates the HUD symbol by 90 degrees.
  - Do this once, then move to exit.
- Level 2:
  - Same rotation mechanic as level 1.
  - Requires 270 degrees total rotation, so trigger cross three times (move off/on between triggers), then exit.
  - Adds yellow refill boxes that replenish turn counter.
- Level 3:
  - Adds rainbow box mechanic that cycles HUD symbol color.
  - Must satisfy both rotation requirement and color match before exiting.
- Level 4:
  - Adds shape-change trigger for HUD symbol shape.
- Level 5:
  - Combines prior mechanics (rotation, color, shape) together.
- Level 6:
  - Adds a second gate before the final exit that must be cleared first.
- Level 7:
  - Adds a visibility mask limiting view to nearby area around player.

## Post-Run Prompt TODOs

- Instruct agent to build reusable code abstractions first (helpers in `play_lib.py`), then keep per-level `solve_*.py` scripts thin and compositional.
- On any `GAME_OVER`, require a written causal theory of why it happened (resource exhaustion/pathing/mechanic mismatch), with concrete evidence and the minimal fix plan before retry.
