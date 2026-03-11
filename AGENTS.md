# ARC-AGI Harness: Local Agent Rules

## Common Guidance

### Mission

This repo and the live `super` CLI it depends on exist to run, monitor, diagnose, and improve ARC-AGI-3 benchmark runs.

Hard rules:
- Optimize for benchmark performance that generalizes across ARC-AGI-3 games, not for a single practice game.
- Do not commit or inject game-specific solving logic, heuristics, or prompt instructions into shared code, shared prompts, or shared tools.
- LS20 is a convenient smoke test and debugging target, not a design target.
- These repos have no meaningful legacy consumers. When interfaces change, update the active code path and tests; do not keep dead compatibility shims.

### Live Repos And Entry Points

Use the real runtime, not stale assumptions.

- Harness repo: `~/projs/arc-agi-harness`
  - Main entrypoints: `harness.py`, `harness_runner.py`, `harness_runtime.py`, `super.yaml`
  - Tool/runtime code: `tools/`, `arc_model_runtime/`
- Live `super` CLI wrapper: `~/.local/bin/super`
  - At the time of writing it execs `bun run /home/dvroom/projs/agent-studio/src/bin/run-config.ts`
  - If `super` behavior matters, inspect the wrapper first instead of assuming which repo owns it
- Live `super` source repo: `~/projs/agent-studio`
  - Start with `src/bin/run-config.ts`
  - Then inspect `src/server/stdio/supervisor/**`, `src/server/stdio/requests/**`, `src/supervisor/**`
  - Useful docs: `docs/CLI_OUTPUT_OPTIONS.md`, `docs/FORK_STORAGE.md`, `docs/ARCHITECTURE.md`
- `~/projs/agent-super` is useful background/reference, but it is not the live runtime unless the wrapper has been repointed

### Benchmark Integrity Is Non-Negotiable

Treat both the solving agent and the supervisor as part of the benchmarked system.

Hard rules:
- Never expose game source code, environment implementation files, hidden labels, reference solutions, or prior run transcripts to the active run.
- Never place benchmark secrets in `runs/<run-id>/agent` or `runs/<run-id>/supervisor`.
- Agent/supervisor should solve only from observable state, allowed prompt context, and public tool interfaces.
- If you are unsure whether a file leaks internals, treat it as forbidden until proven safe.

Containment checks:
- Inspect `setup_run_dir_impl`, `setup_run_config_dir_impl`, and `assert_no_game_files_in_agent_dir_impl` before changing run setup behavior.
- Confirm run-visible trees only contain intended files for that run.
- Confirm no copied environment internals or game python sources appear under run-visible trees.
- Confirm tool interfaces expose state/actions only, not internal objects or source.

### Prompt And Policy Source Of Truth

Hard rules:
- Put agent/supervisor behavioral instructions in `super.yaml`, not in Python harness code.
- Harness/runtime code may pass neutral runtime state, env vars, and artifacts; it must not smuggle policy text.
- If a new instruction is needed, update `super.yaml` or prompt assets under `prompts/`.
- Do not add LS20-specific or any other game-specific prompt text to shared prompts.

### Root Cause And Performance Discipline

For any failure, stall, regression, or major slowdown, do not stop at symptoms.

Required deliverables:
- Symptom: what failed
- Proximal cause: immediate trigger
- Root cause: underlying design/logic flaw
- Why safeguards failed
- Fix
- Verification evidence

Evidence standards:
- Every causal claim must cite exact files, artifacts, or log lines.
- Mark hypotheses explicitly.
- If root cause is not proven, say `ROOT CAUSE NOT YET PROVEN` and keep investigating or name the missing observability.
- Never stop at wrapper symptoms when provider/runtime failures are possible; inspect provider raw events, turn completion status, conversation/fork ids, and stderr before concluding root cause.

For solver mistakes:
- Find the first turn where the wrong belief appears.
- Trace it to the exact evidence, tool output, or supervisor instruction that produced that belief.
- Prefer action-linked movement evidence over visual salience when identifying controllable actors.

For regressions:
- Identify the exact triggering action(s).
- Classify as `GAME_OVER`, reset semantics, tool/harness bug, or unknown with discriminating next checks.

For performance problems:
- Quantify where time went: provider latency, supervisor review time, mode-switch churn, repeated compare loops, repeated file review, replay overhead, idle gaps, scorecard operations.
- State whether the problem is primarily prompt design, harness control flow, provider/runtime behavior, or missing observability.
- Suggest fixes in the right layer: code, prompts, or both.

### No Silent Fallbacks

Benchmark-critical features must fail loudly if broken.

Do not silently degrade or no-op when these fail:
- prompt/image generation used for runtime context
- machine/state artifact reads or writes
- tool JSON parsing and contract validation
- environment setup and game loading
- scorecard ownership/validation
- provider/runtime event logging needed for diagnosis

Personal guardrail:
- Do not turn a hard failure into a warning just to keep runs going.
- Prefer explicit preflight validation over permissive recovery.

### Pre-Commit Checks

- Always run `make lint` before committing.
- Always run `make test` before committing.
- If UI files changed, also run `cd ui && npm run lint`.
- If either required check fails, do not commit until fixed.
- Once required validation passes for the changes you made, commit them in the same pass; do not leave validated code changes uncommitted.

### Final Generalization Rule

Never put game-specific anything in this project.

That includes:
- harness logic
- shared prompts
- supervisor rules
- tool behavior
- model scaffolding templates
- UI heuristics, labels, or help text

## Backend Guidance

### Runtime Map

Know where state actually lives.

- `harness.py` delegates to `harness_runner.run_main`.
- `HarnessRuntime` creates:
  - run workspace: `runs/<session>/`
  - agent workspace: `runs/<session>/agent/game_<game_id>/`
  - supervisor game state: `runs/<session>/supervisor/arc/`
  - run-local config/tools: `runs/<session>/config/{bin,tools,prompts}/`
  - transcript context dir: `.ctxs/<session>/`
- The harness copies `super.yaml` into `runs/<session>/super.yaml` per run.
- The agent uses run-local wrappers from `runs/<session>/config/bin`; agent commands should not depend on project-root executables.
- Supervisor conversation state is workspace-local under `runs/<session>/.ai-supervisor/conversations/<conversation_id>/...`.
- `session.md` frontmatter is the conversation source of truth for `conversation_id`.

Important runtime behavior:
- The harness starts a run with `super new ... --cycle-limit 1`.
- It advances one supervised cycle at a time with repeated `super resume <session.md> ...`.
- In streaming mode, the harness intentionally removes `--output` from the `super` subprocess command, streams full stdout live, and writes the transcript file itself afterward.
- Consequence: live stdout/stderr is the earliest progress signal; do not wait only for `session.md` checkpoints.

Special flows:
- `--score-after-solve` is a two-phase flow: solve unscored first, then open a fresh scorecard and replay from level 1.
- Diagnose discovery and scored replay separately; they are not the same failure surface.

### Monitoring Discipline

When monitoring a run, watch the stream and the files.

Hard rules:
- In the Codex tool environment, long runs must use a persistent exec session plus polling.
- Always capture both `stdout` and `stderr`.
- Do not background a run and walk away without polling session output.
- Do not declare a stall just because `session.md` has not changed recently.
- Before starting a new run, kill stale/orphan REPL daemons from prior runs.
- If a run exits unexpectedly, collect root cause from stderr/logs/raw events before restarting.

Monitoring order:
0. Watch streaming stdout/stderr from the persistent exec session for immediate progress, provider errors, tool hangs, and supervisor decisions.
1. Check `runs/<run-id>/supervisor/arc/state.json` and `runs/<run-id>/supervisor/arc/tool-engine-history.json` together.
2. Check `.ctxs/<session>/session.md` for transcript and current `conversation_id`.
3. If progress is unclear, check `runs/<run-id>/.ai-supervisor/conversations/<conversation>/raw_events/events.ndjson`.
4. Only then conclude stall/failure and classify root cause.

Hard rules:
- Never report "still finding where events are recorded" or equivalent uncertainty.
- If a canonical file is missing, name the exact missing path and treat it as an observability bug.
- If transcript progress and raw events disagree, trust raw events for "is provider still doing work?" and explain the discrepancy.

### Timeout Budgets

Operational timeouts are benchmark-critical.

- ARC API game progress appears to have an idle timeout of about 30 minutes; if hit, progress may be lost.
- Scorecard inactivity has historically timed out around 15 minutes; confirm the current behavior before relying on old assumptions.
- Current harness idle keepalive trigger for real game inactivity is `12 * 60` seconds in `harness_runner.py`.

Rules:
- Treat idle budget and scorecard budget as first-class constraints during run design and diagnosis.
- When analyzing a long or failed run, identify exactly how close it got to these budgets and what consumed the time.
- Do not assume a timeout mitigation is active just because a helper module exists; verify callsites with `rg`.

### Prompt-Tuning Heuristic

The central tradeoff in these runs is real:

- Too little supervision: the agent moves fast, solves easy levels, then drifts or hallucinates as levels get harder.
- Too much supervision/process: the agent becomes slow, overconstrained, and less capable.

Rules:
- Evaluate prompt changes against both early-level speed and later-level stability.
- Do not judge a prompt change from one anecdote.
- Compare against prior strong runs in `runs/` and `.ctxs/` before declaring a new prompt better.
- Do not overfit shared prompts or harness behavior to LS20.

### Code Review Expectations

This codebase needs real review, not style commentary.

Primary review focus:
- Behavioral bugs
- Regression risks
- Benchmark-integrity leaks
- Silent fallbacks
- Timeout and pacing hazards
- Missing or misleading observability
- Mismatch between `super.yaml` intent and runtime behavior

Highest-risk files:
- `harness_runner.py`
- `harness_runtime.py` and `harness_runtime_*`
- `harness_setup_helpers.py`
- `tools/arc_repl_*`
- `arc_model_runtime/*`
- `super.yaml`
- In `~/projs/agent-studio`: `src/bin/run-config.ts`, `src/server/stdio/supervisor/**`, `src/server/stdio/requests/**`, `src/supervisor/**`

Review rules:
- Findings first, ordered by severity, with file references.
- Separate proven bugs from hypotheses.
- If a timeout/keepalive path is under review, verify whether it is on the active call path.

### Supervisor Rule Design

The supervisor runs after an agent turn. It cannot rewrite history that the agent already consumed.

Hard rules:
- Never define hard rules that require undoing already-completed actions inside the same conversation.
- Prefer forward guidance and next-turn corrections.
- If a violation is already in history, treat it as non-rewritable context unless the runtime explicitly forks/resumes around it.
- When changing supervisor behavior, inspect both `super.yaml` and the live `super` runtime in `agent-studio`.

### Legacy Code Policy

- Delete unused legacy code aggressively when touched.
- Keep one canonical implementation per critical behavior.
- If a helper, hack, or compatibility path is unused in the active harness flow, remove it instead of preserving it.
- When changing interfaces between this repo and `agent-studio`, update both ends and relevant tests in the same pass.

### Run Logging And Artifacts

- Keep harness logs with combined `stdout` and `stderr`.
- Preserve per-run artifacts needed to reproduce diagnoses.
- Useful run artifacts often include:
  - `supervisor/arc/state.json`
  - `supervisor/arc/tool-engine-history.json`
  - `supervisor/arc/action-history.json`
  - `supervisor/arc/script-history/`
  - `.ctxs/<session>/session.md`
  - `runs/<run-id>/.ai-supervisor/conversations/<conversation>/raw_events/events.ndjson`

Do not trust run names alone. Inspect the artifacts.

### Practical Commands

- Bootstrap: `uv sync`
- Lint: `make lint`
- Test: `make test`
- Typical local run: `python harness.py --game-id ls20 --session-name smoke-minimal`
- Multi-game run: `python harness.py --game-ids "ls20 ft09 vc33" --operation-mode ONLINE --open-scorecard --session-name batch-smoke`
- `super` help: `super --help`

## UI Guidance

The `ui/` subproject is a Next.js App Router app for inspecting and launching harness runs. When working inside `ui/`, also follow [`ui/AGENTS.md`](/home/dvroom/projs/arc-agi-harness/ui/AGENTS.md).

UI-specific rules:
- After UI changes, verify behavior in the actual running UI, not just by reading code or API output.
- Keep benchmark logic authoritative on the server side. UI components may render scores, params, run state, and history, but canonical computation should stay in server routes or shared backend helpers.
- Do not duplicate scoring rules or run-state inference in browser-only code when the backend already has a canonical source.
- UI affordances that expose run metadata must use real artifacts and explicit fallbacks; do not fabricate confidence when logs, scorecards, or traces are missing.
- Treat launcher state, `.next`, and `node_modules` as local artifacts, not commit targets.

If you need game-specific notes for analysis, keep them in run-local artifacts or the current conversation, not in committed shared code or shared prompt configuration.
