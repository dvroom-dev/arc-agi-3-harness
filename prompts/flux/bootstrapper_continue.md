Bootstrap feedback for the current seed:

Model rehearsal results:
{{model_rehearsal_results}}

Real replay results:
{{real_replay_results}}

Generic replay fallback:
{{replay_results}}

Re-read `flux/seed/current.json`.

Rules:
- Keep the seed JSON schema exact:
  - `syntheticMessages` entries use `role` and `text`
  - allowed roles are only `assistant` and `user`
  - do not write `system`
  - do not write `content`
- If the seed changed and rehearsal exposed an error or weaker-than-expected branch, revise the seed and return `continue_refining`.
- If rehearsal succeeded but the seed can still be improved into a better full-run level-1-to-frontier seed, revise it and return `continue_refining`.
- Return `finalize_seed` only when the current seed is ready to be replayed from level 1 on a fresh real game.
- Keep solved-level steps ideal and deterministic.
- For the frontier, either choose the best current solve attempt or one short exploration branch for the most important unresolved feature.
- Preserve explanations of known mechanics and logical choices in the synthetic seed messages.

Return fresh `bootstrap_seed_decision_v1` JSON.
