Replay feedback for the current seed bundle:

{{replay_results}}

Re-read `flux/seed/current.json`, compare the replay feedback against the accepted model state under `agent/`, and make sure the synthetic seed message names any still-unexplained visible feature that should be prioritized next.
If the replay or accepted evidence shows a newer stage or frontier than the current seed message talks about, rewrite the seed so it targets that newer frontier instead of repeating older opening guidance.
Prefer a seed that will give the next solver a quick useful result: one focused feature probe or one concrete solve attempt.

Revise the seed only if it improves the next solver attempt, then return fresh `bootstrap_attestation_v1` JSON.
