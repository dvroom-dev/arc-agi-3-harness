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

## Supervisor rule design (no time-travel rules)

The supervisor runs after an agent turn. It cannot undo prior actions already present in the conversation context.

Hard rules:
- Never define agent hard rules that require reversing or erasing already-completed actions.
- Never require post-hoc "fixes" that depend on undoing prior tool calls/messages in the same conversation.
- Supervisor enforcement must only target next-turn-correctable behavior.
- If a violation is already in history and cannot be changed, treat it as non-rewritable context; provide forward guidance instead of repeated rewrite loops.
