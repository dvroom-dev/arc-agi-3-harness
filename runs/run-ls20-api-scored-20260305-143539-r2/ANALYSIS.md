# Run Analysis: `run-ls20-api-scored-20260305-143539-r2`

## Scope
- Run directory: `runs/run-ls20-api-scored-20260305-143539-r2`
- Game: `ls20-cb3b57cc`
- Final state: `WIN` (`7/7`)
- Scorecard id: `9e9a1ba2-22be-411d-a6fb-182e293c92d6`

## High-Level Metrics
- Total real game actions (`env.step`): `1127`
- Total tool turns (`turn_*.md`): `304`
- Zero-step tool turns: `181`
- `reset_level` tool calls: `27`
- `GAME_OVER` step events: `0`
- Step-level regressions detected: `0`
- Script-error turns: `13` (`11, 19, 31, 36, 42, 57, 78, 80, 98, 106, 121, 124, 125`)

Real-action mix:
- `ACTION1`: `343`
- `ACTION2`: `365`
- `ACTION3`: `172`
- `ACTION4`: `247`

## Scoring (scorecard method / EnvironmentScoreCalculator)
Computed with `scripts/score_run.py`:

- Game score: `64.1339`
- Baseline actions by level: `[29, 41, 172, 49, 53, 62, 82]`
- AI actions by level: `[20, 41, 48, 65, 141, 323, 489]`
- Per-level scores:
  - L1: `100.0000`
  - L2: `100.0000`
  - L3: `100.0000`
  - L4: `75.3846`
  - L5: `37.5887`
  - L6: `19.1950`
  - L7: `16.7689`

## Level Completion Timeline
Step-level completion transitions from traces:
- Turn `9`, step `7`: `0 -> 1` (terminal action `ACTION1`)
- Turn `12`, step `22`: `1 -> 2` (terminal action `ACTION2`)
- Turn `14`, step `28`: `2 -> 3` (terminal action `ACTION2`)
- Turn `26`, step `10`: `3 -> 4` (terminal action `ACTION3`)
- Turn `56`, step `45`: `4 -> 5` (terminal action `ACTION1`)
- Turn `166`, step `13`: `5 -> 6` (terminal action `ACTION2`)
- Turn `301`, step `10`: `6 -> 7` (terminal action `ACTION2`, `WIN`)

`level_completions.md` winning windows (actions in terminal level windows):
- L1: `20`
- L2: `41`
- L3: `48`
- L4: `65`
- L5: `44`
- L6: `62`
- L7: `54`

Note: scorecard level actions are much larger for L5-L7 than the final winning windows because score counts all actions spent during each level phase before completion, including resets/retries.

## Supervisor Performance
- Conversation forks in `.ai-supervisor` index: `2` (initial + terminal patch fork)
- Recorded supervisor actions: `1`
  - `stop (hard)` at terminal WIN (`agent_stop`), with explicit evidence in reasoning.

Assessment:
- Supervisor acted primarily as terminal validator in this run.
- No mid-run corrective interventions/forks/rewrite loops were recorded.
- Most trajectory control came from the agent/tool loop, not supervisor steering.

## What Worked
- Monotonic completion to `WIN` without `GAME_OVER`.
- Early/mid levels solved efficiently (perfect score through L3, acceptable L4).
- Solver persistence files were maintained (`play.py`/`play_lib.py`) and ultimately drove completion.

## What Hurt Score
- Heavy action spend in late levels, especially L6/L7.
- Frequent resets on late levels (`27` total reset calls across run) expanded score-counted action windows.
- High zero-step turn ratio (`181/304`) indicates substantial analysis/tool overhead relative to productive game actions.

## Bottom Line
- Outcome is a valid scored API WIN for `ls20` with scorecard id `9e9a1ba2-22be-411d-a6fb-182e293c92d6`.
- Final game score: `64.1339`.
- Primary optimization target remains late-level action efficiency (L5-L7), where replay/reset churn dominated the score.
