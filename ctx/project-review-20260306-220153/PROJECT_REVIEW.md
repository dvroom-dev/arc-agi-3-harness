# ARC-AGI Harness Project Review

Date: 2026-03-06

Scope:
- Reviewed the Python harness, prompts, tools, templates, tests, and tracked repo artifacts.
- Ignored the in-progress TypeScript UI in `ui/` as requested.
- Used the live repo state, including existing unrelated uncommitted changes.

## Current status

- Commit is currently blocked by repo policy because both required pre-commit checks fail:
  - `make lint`
  - `make test`
- `make lint` currently fails because the repo enforces a 500-line limit in `scripts/lint.py:9-54`, but several active core modules exceed it:
  - `arc_model_runtime/session.py`: 601 lines
  - `tools/arc_repl_session_artifacts.py`: 558 lines
  - `harness_runner.py`: 536 lines
  - `tools/arc_repl_session_core.py`: 535 lines
  - `harness_runtime.py`: 503 lines
  - `tools/arc_repl.py`: 503 lines
- `make test` currently fails with an active integration regression rooted in run-config setup, described below.

## Executive summary

- The project has a solid benchmark-oriented shape in the areas that matter most: run-local tool staging, separate agent/supervisor workspaces, a conversation-scoped REPL, and useful runtime artifacts under `runs/<session>/...`.
- The biggest current problems are not architectural ambition but consistency gaps:
  - one canonical runtime path has not fully replaced legacy tool paths,
  - timeout handling is split and partially dead,
  - some benchmark-integrity protections are still blacklist-based and LS20-specific,
  - the repo’s own lint/test rules are currently broken on the active path.
- The main strategic theme is to finish the migration to one benchmark-safe, game-agnostic, observable runtime instead of carrying parallel tool families, backup configs, and old mitigation paths.

## Prioritized findings

### 1. Active integration regression: `arc_level.py` became required, but integration test fixtures were not updated

Severity: High

Symptom:
- `make test` fails in multiple integration tests with `FileNotFoundError` for `tools/arc_level.py`.

Proximal cause:
- `setup_run_config_dir_impl()` now treats `arc_level.py` as required and unconditionally copies it from the project root.

Root cause:
- The run-config contract changed, but the minimal fake-project seed helpers used by integration tests were not updated to match the new required tool set.

Why safeguards failed:
- Unit coverage was updated for the new wrapper in `tests/unit/test_harness_helpers.py:158-179`, but the integration fixtures still seed only the older three-tool set.
- There is no shared fixture builder for “minimum valid project layout”, so test setups drift independently.

Evidence:
- `harness_setup_helpers.py:189-215` now requires and copies:
  - `arc_repl.py`
  - `arc_repl_cli.py`
  - `arc_repl_daemon.py`
  - `arc_level.py`
- `tests/unit/test_harness_helpers.py:164-179` already expects `arc_level.py` and the `arc_level` wrapper.
- Representative stale integration fixture:
  - `tests/integration/test_harness_auto_explore_and_completion.py:14-21`
  - It seeds only `arc_repl.py`, `arc_repl_cli.py`, and `arc_repl_daemon.py`, plus `prompts/new_game_auto_explore.py`.

Fix:
- Create one shared test helper that seeds the canonical minimum project layout, and make both unit and integration tests use it.
- Do not let individual tests hand-roll the tool list.

Verification:
- Rerun the failing integration set after switching those fixtures to the shared helper.
- `make test` should stop failing on missing `tools/arc_level.py`.

### 2. Idle keepalive protection is scoped to scorecards, not to online game sessions

Severity: High

Symptom:
- ONLINE API runs without an active scorecard appear to receive no idle-keepalive protection, even though the game session itself can time out and lose progress.

Proximal cause:
- The runtime-level keepalive gate returns true only when both the base ONLINE/API gate is enabled and `active_scorecard_id` is present.
- The tool-side intercept logic repeats the same scorecard requirement from environment variables.

Root cause:
- “Idle keepalive” was modeled as a scorecard feature instead of a generic ONLINE game-session liveness feature.
- Timeout logic is duplicated across the harness and tool layers, which makes the policy easier to mis-scope.

Why safeguards failed:
- The codebase has tests around keepalive markers and scorecard timeout hacks, but there does not appear to be a test that exercises ONLINE/API idle behavior with no scorecard ID.
- The duplication between harness and tool layers hides the fact that both sides share the same assumption.

Evidence:
- Base ONLINE/API gate is set in `harness_runtime.py:217-229`.
- Actual runtime gate is `harness_runtime_env.py:35-36`:
  - `return bool(runtime.api_idle_keepalive_base_enabled and runtime.active_scorecard_id)`
- Tool-side intercept gate is `tools/arc_repl_intercepts.py:46-57`, which also returns false when `ARC_SCORECARD_ID` is absent.

Fix:
- Define two separate concepts explicitly:
  - gameplay-session keepalive for ONLINE/API runs
  - scorecard keepalive for scorecard scoring windows
- Make gameplay keepalive independent of scorecard presence.
- Keep the gating logic in one canonical place and have the other layer consume that decision, not re-derive it.

Verification:
- Add tests for ONLINE/API with and without `ARC_SCORECARD_ID`.
- Confirm keepalive markers still appear for unscored ONLINE runs.
- Confirm scorecard-only heartbeats remain gated to scored runs.

### 3. Scorecard preflight is LS20-hardcoded inside shared harness logic

Severity: High

Symptom:
- Shared scorecard preflight logic is not game-agnostic and can issue REST calls against `ls20-cb3b57cc` even when the active benchmark target is another game.

Proximal cause:
- `_scorecard_probe_reset_and_action()` posts hardcoded LS20 payloads for both `RESET` and `ACTION1`.

Root cause:
- A one-off LS20 probe appears to have been promoted into shared helper code instead of being isolated as a debug/probe path.

Why safeguards failed:
- The project does have some multi-game harness tests, but there is no assertion that scorecard preflight uses the active game ID rather than a baked-in one.
- The repo has a high LS20 testing bias, which makes this kind of overfitting easier to miss.

Evidence:
- `harness_scorecard_helpers.py:238-267`
- Hardcoded values:
  - `harness_scorecard_helpers.py:250-253`
  - `harness_scorecard_helpers.py:261-265`

Fix:
- Pass the current active game ID explicitly into scorecard preflight, or remove gameplay mutation from preflight entirely if the API allows a non-mutating validation path.

Verification:
- Add a multi-game test asserting the probe uses the requested game ID.
- Confirm no LS20-specific identifiers remain in shared harness logic.

### 4. Containment checks are still blacklist-based and partially LS20-specific

Severity: High

Symptom:
- The agent-filesystem leak check blocks a few specific known-bad files, but it does not prove that other game/environment implementation files cannot leak into the run filesystem.

Proximal cause:
- `assert_no_game_files_in_agent_dir_impl()` flags `environment_files`, `.zip` names containing `environment`, and only two specific filenames: `game_state.py` and `ls20.py`.

Root cause:
- The project still uses a partial denylist for benchmark-integrity checking instead of a strict allowlist on what may appear in run-visible trees.

Why safeguards failed:
- The current check catches some known leak shapes, but not the whole class of leaks.
- `ls20.py` is singled out by name, which is a direct sign that the protection logic is anchored to known examples rather than a general invariant.

Evidence:
- `harness_setup_helpers.py:268-287`
- Specific LS20 branch:
  - `harness_setup_helpers.py:276-277`

Fix:
- Replace the blacklist-style scan with an allowlist-style publication model:
  - only copy known-safe run-local files,
  - then assert the resulting run-visible trees contain only those expected paths.
- If a post-copy scan remains, make it generic by source-root and file provenance, not game-specific filenames.

Verification:
- Add tests that intentionally place non-LS20 environment/game source files in the candidate tree and assert the setup fails.

### 5. The repo’s own lint policy is violated by the active core runtime

Severity: Medium

Symptom:
- The repository enforces a 500-line max per Python file but currently fails that rule in several central runtime modules.

Proximal cause:
- Large modules accumulated new responsibilities without being split.

Root cause:
- The codebase is mid-refactor: runtime logic is being separated into helper modules, but the remaining core files are still too large for the repository’s chosen limit.

Why safeguards failed:
- The limit exists in `scripts/lint.py`, but the repo state shows it has not been treated as a blocking design constraint during recent changes.

Evidence:
- Limit definition: `scripts/lint.py:9-54`
- Current line counts:
  - `arc_model_runtime/session.py`: 601
  - `tools/arc_repl_session_artifacts.py`: 558
  - `harness_runner.py`: 536
  - `tools/arc_repl_session_core.py`: 535
  - `harness_runtime.py`: 503
  - `tools/arc_repl.py`: 503

Fix:
- Split by behavior boundaries, not generic “utils” buckets.
- Suggested first cuts:
  - `harness_runner.py`: loop control vs. completion bookkeeping vs. keepalive resolution
  - `harness_runtime.py`: construction/bootstrap vs. runtime filesystem/path helpers vs. scorecard/runtime API helpers
  - `tools/arc_repl.py`: CLI/mainline vs. daemon startup vs. request dispatch

Verification:
- `make lint` should pass without raising the line limit or adding exemptions for active core files.

### 6. Legacy `arc_action` / `arc_get_state` tooling is still tracked, tested, and covered despite the active harness having moved on

Severity: Medium

Symptom:
- The active run-local setup stages `arc_repl` and `arc_level`, but the repo still treats `arc_action`, `arc_action_cli`, and `arc_get_state` as first-class codepaths.

Proximal cause:
- The migration to the `arc_repl` family was only partially completed.

Root cause:
- The project is carrying two overlapping tool families:
  - old `arc_action` / `arc_get_state`
  - current `arc_repl` / `arc_level`

Why safeguards failed:
- The repo still tests and coverage-tracks the older toolchain, so dead or semi-dead paths continue to look “supported”.

Evidence:
- Active setup stages only the new path in `harness_setup_helpers.py:189-250`.
- Unit test explicitly asserts the old tool is not copied:
  - `tests/unit/test_harness_helpers.py:172-179`
- `Makefile:6-10` still collects coverage for:
  - `arc_action`
  - `arc_action_cli`
  - `arc_get_state`
- Tracked legacy files still present:
  - `tools/arc_action.py`
  - `tools/arc_action_cli.py`
  - `tools/arc_action_diffs.py`
  - `tools/arc_action_env.py`
  - `tools/arc_action_exec.py`
  - `tools/arc_action_state.py`
  - `tools/arc_get_state.py`
  - `bin/arc_action`
  - `bin/arc_get_state`

Fix:
- Decide whether any non-test consumer still needs the old tool family.
- If not, delete it and migrate the useful pieces into the `arc_repl` path only.
- If yes, document the split explicitly and stop pretending there is one canonical tool path.

Verification:
- Remove old modules from coverage once deleted.
- Confirm no active harness or operator workflow depends on them.

### 7. Timeout mitigation is duplicated and one of the paths appears dead

Severity: Medium

Symptom:
- The repo contains two timeout-mitigation concepts:
  - live idle-keepalive marker/intercept flow
  - a separate scorecard keepalive “hack” module
- The hack module has tests but no non-test callsites.

Proximal cause:
- `harness_scorecard_timeout_hack.py` remains tracked even though the active runtime path appears to use marker-based keepalive logic instead.

Root cause:
- Old timeout experiments were retained instead of being either promoted into the canonical flow or deleted.

Why safeguards failed:
- Tests still cover the hack, which makes it look maintained even though the runtime does not appear to call it.

Evidence:
- Dead-path search found no non-test runtime callsites for:
  - `maybe_inject_scorecard_keepalive_hack`
- Module:
  - `harness_scorecard_timeout_hack.py:1-84`
- The module itself still encodes a 14-minute threshold:
  - `harness_scorecard_timeout_hack.py:6-10`

Fix:
- Either:
  - delete `harness_scorecard_timeout_hack.py`, or
  - integrate it into the single canonical keepalive design and stop calling it a hack.

Verification:
- One timeout/heartbeat design should remain, with one set of tests and one observability story.

### 8. Documentation is behind the active runtime

Severity: Medium

Symptom:
- README no longer accurately describes the CLI surface that the harness stages into run-local config.

Proximal cause:
- Tooling evolved, but README did not.

Evidence:
- README says the exposed command surface is:
  - `arc_repl (status/reset_level/exec/shutdown)`
  - `arc_repl exec` accepts stdin only
  - `README.md:18-22`
- Actual CLI also supports `exec_file`:
  - `tools/arc_repl_cli.py:5-9`
  - `tools/arc_repl_cli.py:92-95`
  - `tools/arc_repl_cli.py:138-187`
- Run setup also stages `arc_level`:
  - `harness_setup_helpers.py:189-250`
- README has no mention of `arc_level` or `exec_file`.

Fix:
- Update README so operator docs match the current run-local tool surface.

Verification:
- README examples should be executable against the current harness without discovering extra commands by code reading.

### 9. There are likely dead or orphaned tracked assets in the active repo

Severity: Medium

Status:
- Some of these are proven dead by search.
- Some are best labeled “likely dead repo residue” rather than proven runtime-dead.

Evidence:
- `agent_lib.py` is tracked, but no references were found in the repo.
- `prompts/new_game_auto_explore.py` is copied into run config and referenced by tests, but the active auto-explore path is implemented in Python:
  - live path: `harness_explore.py:6-182`
  - invocation from harness loop: `harness_runner.py:133-147`
  - prompt file refs found only in setup/tests, not active runtime dispatch
- The active workspace template for play helpers comes from:
  - `harness.py:61-72`
  - `templates/agent_workspace/play_lib.py:1-25`
- `game_ls20/play_lib.py` is tracked, but no repo references to that exact path were found.
- `super.yaml.backup.pre-intercepts.yaml` is also still tracked and is larger than the active `super.yaml`:
  - `super.yaml`: 518 lines
  - `super.yaml.backup.pre-intercepts.yaml`: 741 lines

Fix:
- Delete proven-dead files.
- For “likely dead” artifacts, confirm no external/manual workflow depends on them, then delete aggressively.
- Keep historical material in `.ctxs/` or a docs/history area, not mixed into the active harness surface.

Verification:
- After cleanup, rerun search and tests to confirm there are no stale references.

### 10. The test suite is still heavily LS20-biased

Severity: Medium

Symptom:
- The project philosophy is explicitly “generalize across many very different games”, but the test suite remains concentrated on LS20.

Evidence:
- 26 of 71 files under `tests/` reference `ls20`.
- Only 3 test files reference `ft09` or `vc33`.
- There are a few multi-game scorecard tests, but the overall suite is still dominated by LS20 fixtures and identifiers.

Risk:
- Overfitted logic can continue to pass local testing as long as it works on LS20-shaped assumptions.
- This is especially dangerous for benchmark-integrity code, scorecard flow, and timeout handling, which should be game-agnostic.

Fix:
- Add a small generic cross-game fixture pack for:
  - another non-click game
  - another click-heavy or state-weird game
  - one scorecard/multi-game path
- Use those fixtures for setup, keepalive, and scorecard preflight tests.

## Consistency and clarity review

- Good:
  - The run-local staging model is clear and benchmark-appropriate.
  - The active workspace templates under `templates/agent_workspace/` are cleaner than keeping mutable game dirs in repo root.
  - The artifact model around `runs/<session>/supervisor/arc` is useful for diagnosis.
- Weak spots:
  - The repo still mixes active runtime, legacy tools, debug backups, experiments, and run-history documents in one top-level working surface.
  - The README documents one tool surface while the code exposes another.
  - The lint policy says “keep modules small”, but the hottest modules are exactly where size pressure is highest.
  - Several benchmark-safety and timeout policies are implemented as partial patches rather than one coherent system.

## Dead code and duplication review

- Strong candidates for deletion or consolidation:
  - `tools/arc_action*.py`
  - `tools/arc_get_state.py`
  - `bin/arc_action`
  - `bin/arc_get_state`
  - `harness_scorecard_timeout_hack.py`
  - `agent_lib.py`
  - `prompts/new_game_auto_explore.py`
  - `super.yaml.backup.pre-intercepts.yaml`
- Likely repo-residue / history material that should not sit on the active path:
  - `experiments/**`
  - tracked run-analysis content such as `runs/INDEX.md` and `runs/run-ls20-api-scored-20260305-143539-r2/ANALYSIS.md`
  - `game_ls20/play_lib.py`
- Duplication hotspots:
  - timeout/keepalive logic split between runtime env, REPL intercepts, and the unused scorecard hack
  - old `arc_action` family and new `arc_repl` family share underlying concerns but are maintained in parallel

## Tactical improvements

- Fix the active `arc_level.py` test regression first so `make test` is trustworthy again.
- Make gameplay keepalive independent of scorecard presence.
- Remove LS20 hardcoding from scorecard preflight immediately.
- Replace the current containment blacklist with an allowlist publication/assertion model.
- Update README to include `arc_level` and `arc_repl exec_file`.
- Delete or quarantine dead assets once their last external/manual consumer is confirmed gone.
- Split the six current line-limit offenders along behavior seams rather than adding lint exemptions.

## Strategic improvements

- Finish the migration to one canonical runtime/tool path.
  - The clean target is `arc_repl` + `arc_level` + run-local config staging.
  - Everything else should either be migrated into that path or deleted.
- Treat timeout management as a first-class subsystem.
  - One model for gameplay idle timeout.
  - One model for scorecard timeout.
  - One observability story.
  - One place where policy decisions are made.
- Make benchmark-integrity enforcement structural rather than reactive.
  - Publish only allowlisted files into run filesystems.
  - Assert run-visible trees match that allowlist.
  - Add leak tests for non-LS20 names so the protection is genuinely generic.
- Reduce LS20 centrality in the test suite.
  - Keep LS20 as the fastest public practice target.
  - Do not let LS20 be the only shape the code is pressured against.
- Move historical/debug material off the active repo surface.
  - If it is worth keeping, keep it as intentionally archived context, not as active implementation baggage.

## Positive notes

- The project is pointed at the right problem: balancing agent autonomy against supervisory correction without benchmark leakage.
- The run-local filesystem setup is the right instinct for containment.
- The raw artifact trail gives a workable foundation for the deeper failure analysis the project needs.
- The remaining work is mostly cleanup and consistency pressure, not a need to reinvent the architecture.
