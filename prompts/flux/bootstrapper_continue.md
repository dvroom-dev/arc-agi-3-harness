Replay feedback for the current seed bundle:

{{replay_results}}

Re-read `flux/seed/current.json`, compare the replay feedback against the accepted model state under `agent/`, and make sure the synthetic seed message names any still-unexplained visible feature that should be prioritized next.

Revise the seed only if it improves the next solver attempt, then return fresh `bootstrap_attestation_v1` JSON.
