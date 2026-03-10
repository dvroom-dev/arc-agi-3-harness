Game <id> Theory

# Elements
- Name:
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
- Do not assume a feature is unique; track multiple copies explicitly.
- Rule of thumb: if a region can move independently, recolor independently, or be consumed independently, it should usually be its own detected component rather than part of one giant bounding box.
- Prefer multiple specific detectors over one broad umbrella detector when the broad box would hide which sub-part actually changed.

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
