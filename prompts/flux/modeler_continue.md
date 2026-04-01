Model acceptance failed.

Acceptance feedback:
{{acceptance_message}}

Use `python3 inspect_sequence.py --current-mismatch` for a compact summary, make one focused patch in `model_lib.py` or `components.py`, rerun `python3 model.py compare_sequences --game-id ...`, and return fresh `model_update_v1` JSON.
If the feedback is `no_eligible_sequences` for the newest visible level, model the frontier start state instead of retrying the same compare loop.
Do not start a long investigation pass here. Make one quick model change or one quick frontier update, rerun acceptance, and report the result.
If multiple sequences exist, resume from the earliest failing sequence in order.
For that earliest failing sequence, default to a local mechanics patch from the earliest mismatching step instead of investigating compare internals or loader behavior.
If root `current_compare.*` has moved to a newer frontier level, use the earliest failing ordered sequence report from the acceptance feedback as the source of truth until that earlier sequence passes.
Treat `action_input_name`, `last_action_name`, and sequence `action_name` as canonical; ignore wrapped tool labels like `exec(<...>)`.
