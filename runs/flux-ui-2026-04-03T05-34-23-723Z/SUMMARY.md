# `flux-ui-2026-04-03T05-34-23-723Z`

## Outcome

- Game: `ls20-9607627b`
- Operation mode: `OFFLINE`
- Scorecard: none (`scorecard_id: null`)
- Result: `WIN`
- Solver stop reason: `solved`

This is the first benchmark-valid `flux` win recorded in this repo.

## Core Metrics

- Wall time to win: `6:55:33.734508`
- Wall time to orchestrator stop: `8:59:43.431000`
- Solver sessions: `1`
- Modeler sessions: `1` durable session, `23` accepted revisions
- Bootstrapper sessions: `1` durable session, `23` rehearsal starts, `23` failures
- Tool turns in the winning solver attempt: `338`
- Action-history records: `3,537`
- Non-reset action steps in final ARC state: `3,472`
- Total resets: `62`

## Level Progression

These milestones come from [`action-history.json`](/home/dvroom/projs/arc-agi-harness/runs/flux-ui-2026-04-03T05-34-23-723Z/flux_instances/attempt_6d1b23ec-ce24-407f-800c-2cb105bc1349/supervisor/arc/action-history.json).

| Completed Level | Timestamp (UTC) | Action Index | Segment Actions | Final Action |
|---|---|---:|---:|---|
| 1 | `2026-04-03T05:57:26.243934+00:00` | 68 | 68 | `ACTION1` |
| 2 | `2026-04-03T06:07:25.404577+00:00` | 155 | 87 | `ACTION2` |
| 3 | `2026-04-03T06:39:47.512538+00:00` | 284 | 129 | `ACTION2` |
| 4 | `2026-04-03T07:25:48.634135+00:00` | 597 | 313 | `ACTION3` |
| 5 | `2026-04-03T07:41:36.828103+00:00` | 802 | 205 | `ACTION1` |
| 6 | `2026-04-03T11:56:28.783012+00:00` | 3378 | 2576 | `ACTION2` |
| 7 / Game Win | `2026-04-03T12:29:58.792508+00:00` | 3537 | 159 | `ACTION2` |

Per-level action distribution by `level_after`:

- Level 1: `67`
- Level 2: `87`
- Level 3: `129`
- Level 4: `313`
- Level 5: `205`
- Level 6: `2,576`
- Level 7: `159`
- Level 8 / post-win state record: `1`

## Session Timeline

These milestones come from [`flux/events.jsonl`](/home/dvroom/projs/arc-agi-harness/runs/flux-ui-2026-04-03T05-34-23-723Z/flux/events.jsonl).

- `2026-04-03T05:34:25.059Z`: `orchestrator.started`
- `2026-04-03T05:34:27.494Z`: `solver.instance_provisioned`
  - attempt: `attempt_6d1b23ec-ce24-407f-800c-2cb105bc1349`
- `2026-04-03T06:14:32.639Z`: first `modeler.acceptance_passed`
- `2026-04-03T06:15:58.104Z`: first `bootstrapper.model_rehearsal_started`
- `2026-04-03T06:15:58.728Z`: first bootstrap rehearsal failure
- `2026-04-03T11:36:56.963Z`: modeler accepted revision `model_rev_9026ddd8-9722-4700-b272-6b8543b9e805`
- `2026-04-03T12:22:25.430Z`: modeler accepted revision `model_rev_5d5f737c-7846-434b-bd6c-1fd1191c5d37`
- `2026-04-03T12:30:32.632Z`: `session.stopped` for solver
- `2026-04-03T12:37:31.664Z`: modeler accepted revision `model_rev_407701d6-0709-4069-a081-c48ca2efcd39`
- `2026-04-03T12:52:36.592Z`: last modeler acceptance in this run
- `2026-04-03T12:53:16.877Z`: last bootstrap rehearsal start
- `2026-04-03T12:53:17.462Z`: last bootstrap rehearsal failure
- `2026-04-03T14:34:08.489Z`: `orchestrator.stopped` after manual stop request

## What Actually Solved The Game

The win came from the original solver session, not from the full intended `solver -> modeler -> bootstrapper -> replacement solver` loop.

What worked:

- One solver session stayed alive for the whole solve.
- The modeler remained productive enough to land `23` accepted revisions.
- The solver eventually reached `WIN` in the live game state:
  - [`state.json`](/home/dvroom/projs/arc-agi-harness/runs/flux-ui-2026-04-03T05-34-23-723Z/flux_instances/attempt_6d1b23ec-ce24-407f-800c-2cb105bc1349/supervisor/arc/state.json)

What did not work:

- The bootstrapper never successfully rehearsed a candidate seed.
- Because rehearsal failed every time, no seed was finalized.
- Because no seed was finalized, no replacement solver session was ever started from a preplayed finalized seed.

So this run is a real `flux` win, but not yet a clean proof that the full bootstrap/finalize/relaunch loop is healthy.

## Bootstrapper Failure Pattern

The bootstrapper ran `23` model rehearsals and all `23` failed.

Primary failure mode:

- `rehearse_seed_on_model.py` resolved seed `read_file` steps against the wrong path shape and failed on missing files like:
  - `agent/game_ls20/level_1/sequences/seq_0007.json`

Later failure mode:

- Rehearsal workspace copies also hit live copy races while cloning the model workspace.

Representative failures:

- [`events.jsonl`](/home/dvroom/projs/arc-agi-harness/runs/flux-ui-2026-04-03T05-34-23-723Z/flux/events.jsonl)
- [`bootstrapper_run/session.json`](/home/dvroom/projs/arc-agi-harness/runs/flux-ui-2026-04-03T05-34-23-723Z/.ai-flux/sessions/bootstrapper/bootstrapper_run/session.json)

## Scoring Notes

There is no official scorecard score for this run because it was unscored.

Latest public scoring references:

- The latest public `arc-agi` release page says that since `0.9.3`, official scoring changed so:
  - per-level score is squared
  - per-game score is weighted by 1-indexed level
- The latest public `arc_agi.scorecard.py` source available in the installed open-source package still computes:
  - per-level score as `min((baseline_actions / actions_taken) * 100, 100)`
  - per-game score as the simple arithmetic average of those per-level scores

That means the current public changelog/docs and the current public `scorecard.py` implementation do not fully agree.

### Duplicate-Game Behavior On One Scorecard

Yes. In the latest public `arc_agi.scorecard.py`, multiple runs of the same game on one scorecard take the best per-game score:

- `EnvironmentScoreList.score = max(run.score for run in self.runs)`
- `EnvironmentScoreList.levels_completed = max(run.levels_completed for run in self.runs)`
- `EnvironmentScoreList.completed = any(run.completed for run in self.runs)`

So duplicate instances of the same game on a scorecard are aggregated by best score / best completion, not averaged together.

### Inferred Scores For This Run

These are informational only, because there is no official scorecard for this run.

Using the current public `ui_run_scores.py` path is not reliable for this flux run; it reports zeros because it still reads stale run-root state rather than the winning attempt state.

Using LS20 human baselines `[21, 123, 39, 92, 54, 108, 109]` and the actual completed-level segment actions `[68, 87, 129, 313, 205, 2576, 159]`:

- If you apply the latest published docs/changelog rule (squared per-level score, level-index weighted average), the inferred game score is approximately `22.7226`.
- If you apply the current public `arc_agi.scorecard.py` implementation literally (simple capped percentage per level, simple average), the inferred game score is approximately `41.3708`.

Because the docs/code disagree, neither inferred score should be treated as an official benchmark number.

## Provenance

These revisions are inferred from local git history by selecting the latest commit before the run start timestamp. The run artifacts did not persist exact git SHAs.

- Harness repo (inferred): `d229556aa452f050802905372c162a06936a855a`
  - `Initialize flux seeds with timestamps`
- `super` repo (inferred): `061659d90114ff2ada7133a2c60595bdf73749fe`
  - `Contain flux sessions and reconcile stale resume state`
