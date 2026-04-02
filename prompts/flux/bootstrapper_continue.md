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
- Keep the mechanic explanation cumulative across levels. Preserve confirmed rules from solved levels and add later confirmed mechanics that matter for future reasoning.
- Keep the seed message structure disciplined:
  - cumulative mechanics summary first
  - solved-level route explanations next
  - frontier branch/mechanic message last
- For the frontier, either choose the best current solve attempt or one short exploration branch for the most important unresolved feature.
- Preserve explanations of known mechanics and logical choices in the synthetic seed messages.
- If the frontier now has confirmed trigger/resource mechanics, rewrite the frontier seed message to name them explicitly.
- Examples of the right level of specificity:
  - which trigger refills fuel or budget
  - which trigger rotates a symbol and by how much
  - whether a HUD symbol must match an exit symbol
  - which trigger changes the HUD symbol color/state
- Even if the frontier replay is still unstable, preserve any confirmed reusable mechanic from that level in the cumulative mechanic summary so the next solver can reason from it immediately.

Return fresh `bootstrap_seed_decision_v1` JSON.
