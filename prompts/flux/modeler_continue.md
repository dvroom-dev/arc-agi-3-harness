Model acceptance failed.

Acceptance feedback:
{{acceptance_message}}

Use `python3 inspect_sequence.py --current-mismatch` for a compact summary, make one focused patch in `model_lib.py` or `components.py`, rerun `python3 model.py compare_sequences --game-id ... --include-reset-ended`, and return fresh `model_update_v1` JSON.
If two same-action steps seem to branch differently, use `python3 model.py compare_transitions --game-id ... --a-level L1 --a-sequence seq_x --a-step N --b-level L2 --b-sequence seq_y --b-step M` to inspect the exact pre-state, post-state, and frame diffs before patching.
If the feedback is `no_eligible_sequences` for the newest visible level, model the frontier start state instead of retrying the same compare loop.
If a new `untrusted_theories_level_<n>.json` file or updated solver `solver_handoff/untrusted_theories.md` appears, read it, treat it as untrusted context, and refine or invalidate it against compare evidence as part of your next patch.
If `feature_boxes_level_<n>.json` and `feature_labels_level_<n>.json` exist for this level, use them to reason about repeated feature-local deltas before adding another step-specific patch.
When your compare target for a level is fully matched, write or update `modeler_handoff/untrusted_theories_level_<n>.md` before handing off.
Do not start a long investigation pass here. Make one quick model change or one quick frontier update, rerun acceptance, and report the result.
If multiple sequences exist, resume from the earliest failing sequence in order.
For that earliest failing sequence, default to a local mechanics patch from the earliest mismatching step instead of investigating compare internals or loader behavior.
If root `current_compare.*` has moved to a newer frontier level, use the earliest failing ordered sequence report from the acceptance feedback as the source of truth until that earlier sequence passes.
Treat `action_input_name`, `last_action_name`, and sequence `action_name` as canonical; ignore wrapped tool labels like `exec(<...>)`.
Do not inspect `arc_model_runtime/*` or compare helper source before making one local patch in `model_lib.py` or `components.py`.
For game-vs-model diffs, read them literally as `game_value -> model_value`.
If `frame_0001.hex` for the mismatching step equals that step's `after_state.hex`, emit the same post-action frame from your model before any deeper investigation.
If `frame_count_game > 1`, consider that the action may be a transient trigger/HUD/exit-lighting animation even when the settled state barely changes.
Do not treat every multi-frame action as extra movement. Model the transient frames explicitly when the frame files show a pure animation layer.
If you replay synced sequence artifacts from code, resolve `files.*` and `frame_sequence_hex` relative to the matched action directory's actual level root, for example with `artifact_helpers.resolve_sequence_action_path(action_dir, rel_path)`. Do not prepend a hardcoded `level_N` prefix.
Remember that `apply_level_1..apply_level_N` run cumulatively on later levels. If you replay recorded transitions in a per-level hook, gate them to the intended level or match them by `before_state`; do not assume a global action index from a later level belongs under an earlier level's artifact tree.
For `intermediate_frame_mismatch`, patch your model's direct action effect or `last_step_frames` first. Only inspect compare/runtime internals if a rerun after that patch produces a concrete contradiction.
