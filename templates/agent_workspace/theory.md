Game <id> Theory

# Elements
- Name:
  - Code name: neutral identifier used in `components.py` (for example `feature_a`, `cluster_b`, `box_c`). Do not use semantic names like `player`, `cursor`, `target`, `goal`, `enemy`, `exit`, or `hud` here until action-linked evidence proves the role.
  - Role hypothesis: optional semantic meaning recorded in `theory.md` only, with confidence and evidence. Leave blank or use `unknown` until proven.
  - Detector: `find_all_<name>` in `components.py`
  - Covers: which visible pixels/regions this component owns
  - Copies: single|multiple|unknown
  - Mechanics:
    - Confidence: High|Medium|Low
      Mechanic:
      Evidence:
        - Level X Turn Y: action -> observed state change

Coverage guardrail:
- Every visible pixel in every seen state for the active level should lie inside at least one component bounding box.
- Keep `components.py` detectors broad enough that `python3 inspect_components.py --coverage --level <n>` passes before leaving theory mode.
- Use neutral feature names until a semantic role is proven by evidence.
- Keep semantic meaning out of `components.py` identifiers. Put semantic guesses only in the `Role hypothesis` line here, and only when you can cite evidence.
- Do not assume a feature is unique; track multiple copies explicitly.
- Rule of thumb: if a region can move independently, recolor independently, or be consumed independently, it should usually be its own detected component rather than part of one giant bounding box.
- Prefer multiple specific detectors over one broad umbrella detector when the broad box would hide which sub-part actually changed.
- Early in level 1, speculation is allowed and expected, but keep it clearly marked as a hypothesis and revise it quickly once action evidence arrives.

# Available Real-Game Actions (exclude RESET)
  - ACTION#: what it appears to do

# Action Effects
- ACTION#:
  - Changed elements:
  - Unchanged salient elements:
  - Open questions:

# Completion Candidates
- Candidate:
  - Confidence: High|Medium|Low
  - Evidence:
  - Missing evidence:

# Unknowns
- Unknown:
  - Why it matters:
  - Smallest next probe or model patch:

# Explore Plan
- Target class:
  - What unresolved feature or completion question is being tested
- Probe sequence:
  - Ordered real-game actions to run next
- Expected observations:
  - What outcomes would confirm or falsify the target class
- Stop condition:
  - When explore should return to theory
- Notes:
  - Keep this scoped to one target class at a time
  - On level 1, do not put an unbounded route plan or a mixed probe-plus-then-route agenda here
  - When movement semantics and route topology are already confirmed, this target class may be one bounded multi-action route
  - If you hand off a bounded route, include an explicit stop condition: completion, novel event, route exhausted, blocked, or budget boundary
  - Keep the probe sequence minimal: only the next action sequence needed to answer the current target class

# Levels
1: SOLVED|UNSOLVED
Observations:
  - Key observations
  - Component/effect facts established
  - What is still uncertain
Level Delta:
  - What changed vs previous level
  - New feature/mechanic/challenge/twist

2: SOLVED|UNSOLVED
Observations:
  - Key observations
  - Mechanics used
  - What is still uncertain
Level Delta:
  - What changed vs previous level
  - New feature/mechanic/challenge/twist
