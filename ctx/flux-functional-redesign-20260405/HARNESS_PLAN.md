# Harness Flux Redesign Plan

## Purpose

This document defines the harness-side half of a fresh flux redesign. The goals are:

- make run state derivable instead of inferred from mutable workspace state
- stop merging artifacts from multiple attempts into one durable workspace
- make model/seed decisions reproducible from immutable fixtures
- make end-to-end failures testable with deterministic mocks and recorded fixtures
- delete the current fragile sync/selection logic instead of preserving it

This plan assumes a paired runtime redesign in:

- [super flux plan](/home/dvroom/projs/super/ctx/flux-functional-redesign-20260405/SUPER_PLAN.md)

## Core Problems To Eliminate

### 1. No canonical attempt snapshot

Current harness hook code synthesizes a model workspace by mixing:

- the active attempt
- the latest attempt
- the "richest" attempt
- synthetic fallback sequence surfaces

That behavior lives primarily in:

- [common.py](/home/dvroom/projs/arc-agi-harness/scripts/flux/common.py)

This must be deleted. A model comparison or seed rehearsal must consume one explicit immutable snapshot, never a merged projection.

### 2. Acceptance depends on mutable workspace refreshes

Current acceptance resyncs the latest attempt into the durable model workspace at compare time. That means the same model revision can pass, fail, and pass again depending on filesystem timing. The acceptance surface is not a function of explicit inputs.

### 3. Synthetic artifact generation hides missing state

Current helper code creates or repairs missing sequence surfaces opportunistically. That turns missing observability into fake success. Missing surfaces must become explicit typed failures.

### 4. Tests mock away the real failure surfaces

Most current tests use tiny happy-path scripts with:

- one evidence object
- one compare report
- no cross-attempt artifact selection
- no stale compare files
- no frontier-level incomplete surfaces
- no race between solver evidence, model compare, and seed decisions

Those tests verify control flow, not correctness.

## Target Model

The harness should stop acting like a mutable state manager and instead become a producer of immutable attempt artifacts plus a thin adapter around ARC-specific tools.

### Immutable units

Define explicit immutable directories and ids:

- `attempt_id`
- `attempt_snapshot_id`
- `evidence_bundle_id`
- `model_input_bundle_id`
- `seed_rehearsal_id`
- `seed_replay_id`

Each bundle directory must be write-once. New information creates a new bundle id instead of mutating an old one.

### Canonical bundle types

#### Attempt snapshot bundle

One attempt snapshot is a frozen view of a solver attempt at a point in time.

Contents:

- normalized state summary
- action history summary
- level summaries
- references to visible artifact files
- provenance:
  - `attempt_id`
  - `captured_at`
  - `source_turn`
  - `source_watermark`

#### Evidence bundle

One evidence bundle is the exact modeler input surface derived from one attempt snapshot.

Contents:

- ordered sequence manifests
- current frontier summary
- compare input manifest
- typed completeness flags:
  - `has_level_sequences`
  - `has_frontier_initial_state`
  - `has_frontier_sequences`
  - `has_compare_surface`

The bundle must be complete enough to either:

- support comparison
- or explicitly encode why comparison is incomplete

#### Rehearsal result bundle

One rehearsal result is a typed outcome of replaying one seed revision against one model revision.

Possible statuses:

- `rehearsal_passed`
- `rehearsal_failed_replay`
- `rehearsal_failed_compare`
- `rehearsal_incomplete_artifacts`
- `rehearsal_infrastructure_failure`

Do not compress these into `rehearsal_ok: bool`.

## Harness Workstreams

### A. Replace `scripts/flux/common.py`

Delete the current cross-attempt selection and sync logic.

Replace it with narrow modules:

- `attempt_snapshot.py`
- `evidence_bundle.py`
- `model_input_bundle.py`
- `seed_rehearsal_bundle.py`
- `seed_replay_bundle.py`
- `artifact_manifest.py`

Rules:

- no "active vs latest vs richest" merge logic
- no synthetic `seq_0001` generation
- no workspace mutation during acceptance
- no copying from one attempt into another attempt

### B. Provision solver instances as fresh, isolated workspaces

`provision_instance.py` should create a fresh solver attempt workspace and return only:

- immutable attempt id
- working directory
- tool env
- initial prompt surface id

It should not imply that later hooks may read arbitrary shared current state.

### C. Make `observe_evidence.py` append-only

`observe_evidence.py` should:

- read one attempt workspace
- build one new attempt snapshot
- materialize one evidence bundle if new observable state exists
- emit typed metadata about what changed

It should not sync anything into the durable model workspace.

Output contract should include:

- `attempt_snapshot_id`
- `evidence_bundle_id`
- `state_delta_kind`
- `progress_delta`
- `frontier_level`
- `bundle_completeness`

### D. Rebuild `check_model.py` around explicit inputs

Current behavior:

- refreshes from latest attempts
- chooses an ARC state dir heuristically
- compares against mutable workspace state

Replace it with:

- input: `model_revision_id`, `evidence_bundle_id`
- materialize a temp compare workspace from those two ids only
- run compare
- emit a typed acceptance result

Acceptance result kinds:

- `accepted`
- `rejected`
- `frontier_discovered_no_sequences`
- `incomplete_artifacts`
- `infrastructure_failure`

### E. Rebuild rehearsal and replay hooks as typed commands

`rehearse_seed_on_model.py` and `replay_seed_on_real_game.py` should consume:

- `seed_revision_id`
- `model_revision_id` or fresh runtime instance id
- explicit immutable bundle ids

They should emit typed results, not a large untyped JSON blob.

### F. Durable model workspace becomes a build artifact, not shared mutable state

The durable `agent/` model workspace should be treated as a checked-out source tree for the latest accepted model revision.

But comparison must not depend on mutating it in place.

Approach:

- modeler edits happen in a revision workspace
- accepted revision is snapshotted as `model_revisions/<id>/workspace/`
- temporary compare workspaces are derived from:
  - one model revision
  - one evidence bundle

## Race Condition Strategy

### Solver vs modeler

Desired behavior:

- solver keeps running
- new evidence can trigger modeler
- modeler should use the latest evidence when it starts comparing

Guard:

- modeler invocation is bound to a `target_evidence_bundle_id`
- if newer evidence arrives while modeler is running, record it
- after the current modeler turn completes, compare against the latest bundle
- if the compared bundle is stale, enqueue a follow-up modeler run with the newer bundle

Do not let one modeler turn mutate the compare target mid-run.

### Modeler vs bootstrapper

Desired behavior:

- bootstrapper should use the model revision that was current when bootstrapper invocation started
- it must not race forward to a newer model mid-run

Guard:

- bootstrapper command includes `baseline_model_revision_id`
- all compare/rehearsal/replay work for that invocation references that revision only
- if a newer accepted model appears during bootstrapper execution, record it as a newer invocation candidate

### Bootstrapper vs solver interruption

Decision policy after seed production:

- `queue_and_interrupt`
  - seed explains a new mechanic not present before
  - seed materially improves a mechanic explanation
  - seed completes a level the previous seed did not complete
- `queue_without_interrupt`
  - improvement is real but marginal
  - not enough value to kill the live solver now
- `no_action`
  - no useful seed delta

This decision must be based on typed seed delta classification, not prose.

Required fields in seed attestation output:

- `seed_delta_kind`
- `supersedes_seed_revision_id`
- `improves_frontier_level`
- `adds_mechanic_ids`
- `improves_mechanic_ids`
- `interrupt_policy`

### Artifact visibility races

Use write-once bundle directories plus manifest files:

- write files into temp dir
- fsync if needed
- atomically rename temp dir to final bundle id
- only publish the bundle id after manifest write succeeds

No consumer may read half-written bundle directories.

## Testing Plan

### 1. Replace fake e2e mocks with recorded replay packs

Create a fixture format under `tests/fixtures/flux_replay_packs/`.

Each replay pack should contain:

- selected `events.jsonl`
- typed attempt snapshots
- evidence bundles
- compare outputs
- rehearsal outputs
- replay outputs
- expected orchestration decisions

Start by harvesting packs from recent failing runs:

- stale compare vs fresh compare disagreement
- missing `level_2/sequences`
- missing frontier level dir after rehearsal advanced a level
- repeated modeler acceptance with no useful bootstrap delta
- repeated seed finalization leading to solver preemption churn

### 2. Functional core tests

Add pure tests for:

- attempt snapshot derivation
- evidence bundle derivation
- bundle completeness classification
- seed delta classification
- interruption policy selection

These tests should use plain data structures, not subprocesses.

### 3. Hook contract tests

For each hook script:

- validate schema of input
- validate schema of output
- validate typed failure behavior

Important negative tests:

- missing sequences
- missing frontier initial state
- contradictory level metadata
- stale compare file present but bundle manifest says incomplete

### 4. Deterministic orchestration scenarios without LLMs

Build a test harness where:

- solver outputs a scripted sequence of evidence bundles
- modeler outputs scripted model revision results
- bootstrapper outputs scripted seed deltas and interruption policies

Then verify:

- modeler reruns only when needed
- bootstrapper compares against the model revision bound at invocation start
- solver interruption happens only for `queue_and_interrupt`
- stale outputs do not overwrite newer ones

### 5. Invariant tests over recorded fixtures

Critical invariants:

- one acceptance result references exactly one model revision and one evidence bundle
- one bootstrapper invocation references exactly one baseline model revision
- one seed attestation references exactly one rehearsal result and one replay result
- no accepted compare may reference missing artifact files
- no finalized seed may rely on `incomplete_artifacts`
- no compare may mix artifacts from different attempts

## Deletion Plan

Delete after replacement:

- cross-attempt merge logic in [common.py](/home/dvroom/projs/arc-agi-harness/scripts/flux/common.py)
- `_ensure_sequence_surface`
- `latest_flux_instance_state_dir`
- `sync_latest_attempt_to_model_workspace`
- acceptance logic that refreshes model inputs from "latest" state at compare time

Keep only:

- ARC environment/tool wrappers
- rendering utilities
- attempt-local artifact capture

## Delivery Stages

### Stage 1: Data model and fixtures

- define typed bundle schemas
- build replay-pack fixture format
- add pure derivation tests

### Stage 2: New harness hooks

- implement immutable attempt snapshot and evidence bundle writers
- implement new typed compare/rehearsal/replay hooks
- add hook contract tests

### Stage 3: Wire into new super runtime

- switch runtime to bundle ids instead of mutable sync files
- remove old sync logic

### Stage 4: Delete legacy harness flux path

- remove old mutable sync helpers
- remove tests that assert current broken behavior
- keep only fixture-driven scenario tests and typed contract tests

## Non-Negotiable Invariants

- missing artifacts are explicit failures, never silently synthesized
- acceptance is a pure function of `(model_revision_id, evidence_bundle_id)`
- bootstrapper attestation is a pure function of `(seed_revision_id, baseline_model_revision_id, rehearsal_result_id, replay_result_id)`
- seed interruption policy is explicit and typed
- no cross-attempt artifact merging
- end-to-end scenario tests run without live LLMs
