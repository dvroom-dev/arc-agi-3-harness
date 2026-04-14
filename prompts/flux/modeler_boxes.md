You are in the modeler's feature-box labeling phase.

Goals:
- Before mechanic patching continues for this level, classify every harness-generated feature box.
- Use the box ids from `feature_boxes_level_<n>.json`.
- Use `python3 inspect_box_sequence.py --level <n> --box <box_id>` to inspect how a box changes across steps and sequences.
- Name visual/local features, not hidden mechanics or speculative win conditions.
- Good names are concrete and descriptive, for example `five_by_five_stack`, `bottom_pair_bar`, `cross_symbol`, `target_icon`, `wall_cluster`, `flash_overlay`.
- For each box, provide one or more feature names plus one or more tags from:
  - `stable`
  - `movable`
  - `transient`
  - `ui_like`
  - `unknown`
- Use this exact JSON shape for each box entry:
  - `box_id`
  - `features`
  - `tags`
- Do not use `feature_names`; the key must be exactly `features`.
- Cover every box exactly once.
- Do not patch `model_lib.py` in this phase.
- Do not skip boxes because they seem unimportant. The point is to build a reusable structural map before mechanic modeling.

Return only JSON matching `model_box_labels_v1`.
