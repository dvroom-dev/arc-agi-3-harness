# Solved-Level Wrap-Up Contract

This document describes the intended control flow after a real-game level
completes and before the agent is allowed to work on the next frontier level.

The goal is to ensure that every solved level is fully incorporated into:
- `theory.md`
- `components.py`
- model mechanics / compare parity

before the run proceeds to the next level.

## Core Rule

When the real game completes level `N` and advances to level `N+1`, the run
must enter a solved-level wrap-up phase for level `N`.

During this phase:
- the run is **not** considered fully advanced to the new level for theory/model
  purposes
- compare, model status, and visible level workspace must stay pinned to the
  solved level
- the supervisor must certify that solved-level wrap-up is complete before the
  frontier level is allowed to proceed

## Required Post-Completion Flow

1. Real game completes level `N`.
2. Harness/runtime writes a solved-level analysis pin for level `N`.
3. Supervisor runs immediately on the level-complete event.
4. Supervisor decides whether solved-level wrap-up still requires:
   - `theory` work
   - `components.py` updates / coverage repair
   - `code_model` repair for compare parity
5. Supervisor resumes the appropriate mode(s) to wrap up the solved level.
6. The run remains pinned to level `N` until wrap-up is certified complete.
7. Only after certification may the run proceed to true frontier-level work on
   `N+1`.

## Pin Semantics

While solved-level wrap-up is active for level `N`:
- `level_current/` in the visible agent workspace must point at the solved level
- compare must operate on the solved level
- component helpers must operate on the solved level
- model status must report the solved level as current
- theory/code-model prompts must tell the agent it is still working on the
  solved level
- frontier-level observations must not be recorded into solved-level artifacts

The frontier level may exist on disk internally, but it must not become the
active visible level for theory/code-model work until the pin is cleared.

## Supervisor Certification Conditions

The supervisor should only certify solved-level wrap-up when all required
solved-level work is done.

Typical certification requirements:
- `theory.md` reflects the solved-level mechanics actually observed
- `components.py` covers all seen solved-level states
- solved-level compare is clean in `code_model`
- no solved-level component or mechanic updates are still pending

If any of those are missing, the supervisor must keep the run pinned and resume
the appropriate wrap-up mode.

Certification is explicit:
- when leaving solved-level wrap-up, the supervisor must switch to the next mode
  with `mode_payload.wrapup_certified=true`
- and `mode_payload.wrapup_level=<solved level>`
- the harness will not clear the pin without those fields, even if helper
  evidence is otherwise ready

## Mode Responsibilities During Wrap-Up

### Theory

Use when the solved level still needs:
- updated mechanism descriptions
- updated component names/detectors
- fresh coverage confirmation

### Code Model

Use when the solved level still needs:
- parity repair against explored solved-level sequences
- mechanical/completion updates in the model

`code_model` must not exit while solved-level compare is still red.

## Anti-Requirements

During solved-level wrap-up:
- do not let theory/code-model drift into frontier-level exploration
- do not let compare silently switch to the frontier level
- do not treat the real game’s new `current_level` as the active analysis level
- do not clear the pin just because the real game already advanced

## Why This Exists

Without this phase, the agent can:
- solve a level in the real game
- leave theory/components/model partially stale
- then start reasoning about the next level with a half-updated model

That causes confusion, broken compare behavior, and poor frontier performance.
