import { afterEach, describe, expect, test } from "bun:test";
import fs from "node:fs/promises";
import path from "node:path";
import { readFluxRunDetail } from "@/lib/flux.server";
import { RUNS_DIR } from "@/lib/paths";

const createdRuns: string[] = [];

afterEach(async () => {
  await Promise.all(
    createdRuns.splice(0).map(async (runId) => {
      await fs.rm(path.join(RUNS_DIR, runId), { recursive: true, force: true });
    }),
  );
});

describe("flux UI server helpers", () => {
  test("prefers active seed_rev instance over stale attempt for run detail state", async () => {
    const runId = `ui-flux-test-${Date.now()}`;
    createdRuns.push(runId);
    const runRoot = path.join(RUNS_DIR, runId);
    const attemptRoot = path.join(runRoot, "flux_instances", "attempt_old");
    const seedRoot = path.join(runRoot, "flux_instances", "seed_rev_live");

    await fs.mkdir(path.join(runRoot, "flux"), { recursive: true });
    await fs.mkdir(path.join(runRoot, "flux", "seed"), { recursive: true });
    await fs.mkdir(path.join(runRoot, "flux", "model", "current"), { recursive: true });
    await fs.mkdir(path.join(runRoot, ".ai-flux", "sessions", "solver", "solver_attempt_live"), { recursive: true });
    await fs.mkdir(path.join(attemptRoot, "agent", "game_ls20", "level_current"), { recursive: true });
    await fs.mkdir(path.join(seedRoot, "agent", "game_ls20", "level_current", "turn_0001"), { recursive: true });
    await fs.mkdir(path.join(attemptRoot, "supervisor", "arc"), { recursive: true });
    await fs.mkdir(path.join(seedRoot, "supervisor", "arc"), { recursive: true });

    await fs.writeFile(path.join(runRoot, "flux_runtime.json"), JSON.stringify({ game_id: "ls20" }, null, 2), "utf8");
    await fs.writeFile(
      path.join(runRoot, "flux", "seed", "current_meta.json"),
      JSON.stringify({
        lastBootstrapperModelRevisionId: "model_rev_old",
        lastQueuedBootstrapModelRevisionId: "model_rev_live",
        lastAttestedSeedRevisionId: "seed_rev_live",
        lastAttestedSeedHash: "hash_live",
        lastInterruptPolicy: "queue_and_interrupt",
        lastSeedDeltaKind: "level_completion_advanced",
      }, null, 2),
      "utf8",
    );
    await fs.writeFile(
      path.join(runRoot, "flux", "model", "current", "meta.json"),
      JSON.stringify({ revisionId: "model_rev_live" }, null, 2),
      "utf8",
    );
    await fs.writeFile(
      path.join(runRoot, "flux", "state.json"),
      JSON.stringify({
        version: 1,
        workspaceRoot: runRoot,
        configPath: path.join(runRoot, "flux.yaml"),
        pid: process.pid,
        startedAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        status: "running",
        stopRequested: false,
        active: {
          solver: {
            sessionId: "solver_attempt_live",
            status: "running",
            attemptId: "attempt_old",
            instanceId: "seed_rev_live",
          },
          modeler: { status: "idle" },
          bootstrapper: { status: "idle" },
        },
      }, null, 2),
      "utf8",
    );
    await fs.writeFile(
      path.join(runRoot, ".ai-flux", "sessions", "solver", "solver_attempt_live", "session.json"),
      JSON.stringify({
        sessionId: "solver_attempt_live",
        sessionType: "solver",
        status: "running",
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        provider: "claude",
        model: "claude-opus-4-6",
      }, null, 2),
      "utf8",
    );

    await fs.writeFile(
      path.join(attemptRoot, "supervisor", "arc", "state.json"),
      JSON.stringify({
        current_level: 1,
        levels_completed: 0,
        state: "NOT_FINISHED",
        win_levels: 7,
      }, null, 2),
      "utf8",
    );
    await fs.writeFile(
      path.join(seedRoot, "supervisor", "arc", "state.json"),
      JSON.stringify({
        current_level: 2,
        levels_completed: 1,
        state: "NOT_FINISHED",
        win_levels: 7,
      }, null, 2),
      "utf8",
    );
    await fs.writeFile(
      path.join(seedRoot, "agent", "game_ls20", "level_current", "meta.json"),
      JSON.stringify({ level: 2 }, null, 2),
      "utf8",
    );
    await fs.writeFile(
      path.join(seedRoot, "agent", "game_ls20", "level_current", "initial_state.hex"),
      "0\n",
      "utf8",
    );
    await fs.writeFile(
      path.join(seedRoot, "agent", "game_ls20", "level_current", "current_state.hex"),
      "1\n",
      "utf8",
    );
    await fs.writeFile(
      path.join(seedRoot, "agent", "game_ls20", "level_current", "turn_0001", "meta.json"),
      JSON.stringify({
        tool_turn: 1,
        action_input_name: "ACTION1",
        changed_pixels: 1,
        state_before_action: "NOT_FINISHED",
        state_after_action: "NOT_FINISHED",
      }, null, 2),
      "utf8",
    );
    await fs.writeFile(path.join(seedRoot, "agent", "game_ls20", "level_current", "turn_0001", "after_state.hex"), "1\n", "utf8");

    const detail = await readFluxRunDetail(runId);
    expect(detail).not.toBeNull();
    expect(detail?.currentAttemptId).toBe("seed_rev_live");
    expect(detail?.currentLevel).toBe(2);
    expect(detail?.currentState?.current_level).toBe(2);
    expect(detail?.selectedGameDir?.includes("seed_rev_live")).toBe(true);
    expect(detail?.currentModelRevisionId).toBe("model_rev_live");
    expect(detail?.lastAttestedSeedRevisionId).toBe("seed_rev_live");
    expect(detail?.lastInterruptPolicy).toBe("queue_and_interrupt");
  });

  test("builds state frames from per-action sequence artifacts including reset steps", async () => {
    const runId = `ui-flux-sequences-${Date.now()}`;
    createdRuns.push(runId);
    const runRoot = path.join(RUNS_DIR, runId);
    const attemptRoot = path.join(runRoot, "flux_instances", "attempt_live");
    const gameRoot = path.join(attemptRoot, "agent", "game_ls20");
    const levelCurrentRoot = path.join(gameRoot, "level_current");
    const level2Root = path.join(gameRoot, "level_2");

    await fs.mkdir(path.join(runRoot, "flux", "seed"), { recursive: true });
    await fs.mkdir(path.join(runRoot, "flux", "model", "current"), { recursive: true });
    await fs.mkdir(path.join(runRoot, ".ai-flux", "sessions", "solver", "solver_attempt_live"), { recursive: true });
    await fs.mkdir(path.join(attemptRoot, "supervisor", "arc"), { recursive: true });
    await fs.mkdir(path.join(levelCurrentRoot, "sequences"), { recursive: true });
    await fs.mkdir(path.join(level2Root, "sequences", "seq_0001", "actions", "step_0001_action_000029_action1"), { recursive: true });
    await fs.mkdir(path.join(level2Root, "sequences", "seq_0002", "actions", "step_0001_action_000031_action4"), { recursive: true });

    await fs.writeFile(path.join(runRoot, "flux_runtime.json"), JSON.stringify({ game_id: "ls20" }, null, 2), "utf8");
    await fs.writeFile(
      path.join(runRoot, "flux", "state.json"),
      JSON.stringify({
        version: 1,
        workspaceRoot: runRoot,
        configPath: path.join(runRoot, "flux.yaml"),
        pid: process.pid,
        startedAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        status: "running",
        stopRequested: false,
        active: {
          solver: {
            sessionId: "solver_attempt_live",
            status: "running",
            attemptId: "attempt_live",
            instanceId: "attempt_live",
          },
          modeler: { status: "idle" },
          bootstrapper: { status: "idle" },
        },
      }, null, 2),
      "utf8",
    );
    await fs.writeFile(
      path.join(runRoot, ".ai-flux", "sessions", "solver", "solver_attempt_live", "session.json"),
      JSON.stringify({
        sessionId: "solver_attempt_live",
        sessionType: "solver",
        status: "running",
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        provider: "claude",
        model: "claude-opus-4-6",
      }, null, 2),
      "utf8",
    );
    await fs.writeFile(
      path.join(attemptRoot, "supervisor", "arc", "state.json"),
      JSON.stringify({
        current_level: 2,
        levels_completed: 1,
        state: "NOT_FINISHED",
        win_levels: 7,
      }, null, 2),
      "utf8",
    );
    await fs.writeFile(path.join(levelCurrentRoot, "meta.json"), JSON.stringify({ level: 2 }, null, 2), "utf8");
    await fs.writeFile(path.join(levelCurrentRoot, "initial_state.hex"), "0\n", "utf8");
    await fs.writeFile(path.join(levelCurrentRoot, "current_state.hex"), "3\n", "utf8");
    await fs.writeFile(path.join(level2Root, "initial_state.hex"), "0\n", "utf8");

    await fs.writeFile(
      path.join(level2Root, "sequences", "seq_0001.json"),
      JSON.stringify({
        level: 2,
        sequence_id: "seq_0001",
        sequence_number: 23,
        start_action_index: 29,
        end_action_index: 30,
        end_reason: "reset_level",
        action_count: 1,
        actions: [{
          action_index: 29,
          action_name: "ACTION1",
          state_before: "NOT_FINISHED",
          state_after: "NOT_FINISHED",
          files: {
            before_state_hex: "sequences/seq_0001/actions/step_0001_action_000029_action1/before_state.hex",
            after_state_hex: "sequences/seq_0001/actions/step_0001_action_000029_action1/after_state.hex",
            meta_json: "sequences/seq_0001/actions/step_0001_action_000029_action1/meta.json",
          },
        }],
      }, null, 2),
      "utf8",
    );
    await fs.writeFile(
      path.join(level2Root, "sequences", "seq_0001", "actions", "step_0001_action_000029_action1", "before_state.hex"),
      "0\n",
      "utf8",
    );
    await fs.writeFile(
      path.join(level2Root, "sequences", "seq_0001", "actions", "step_0001_action_000029_action1", "after_state.hex"),
      "1\n",
      "utf8",
    );
    await fs.writeFile(
      path.join(level2Root, "sequences", "seq_0001", "actions", "step_0001_action_000029_action1", "meta.json"),
      "{}",
      "utf8",
    );

    await fs.writeFile(
      path.join(level2Root, "sequences", "seq_0002.json"),
      JSON.stringify({
        level: 2,
        sequence_id: "seq_0002",
        sequence_number: 24,
        start_action_index: 31,
        end_action_index: 31,
        end_reason: "open",
        action_count: 1,
        actions: [{
          action_index: 31,
          action_name: "ACTION4",
          state_before: "NOT_FINISHED",
          state_after: "NOT_FINISHED",
          files: {
            before_state_hex: "sequences/seq_0002/actions/step_0001_action_000031_action4/before_state.hex",
            after_state_hex: "sequences/seq_0002/actions/step_0001_action_000031_action4/after_state.hex",
            meta_json: "sequences/seq_0002/actions/step_0001_action_000031_action4/meta.json",
          },
        }],
      }, null, 2),
      "utf8",
    );
    await fs.writeFile(
      path.join(level2Root, "sequences", "seq_0002", "actions", "step_0001_action_000031_action4", "before_state.hex"),
      "2\n",
      "utf8",
    );
    await fs.writeFile(
      path.join(level2Root, "sequences", "seq_0002", "actions", "step_0001_action_000031_action4", "after_state.hex"),
      "3\n",
      "utf8",
    );
    await fs.writeFile(
      path.join(level2Root, "sequences", "seq_0002", "actions", "step_0001_action_000031_action4", "meta.json"),
      "{}",
      "utf8",
    );

    const detail = await readFluxRunDetail(runId);
    expect(detail).not.toBeNull();
    expect(detail?.frames.map((frame) => frame.label)).toEqual([
      "Initial",
      "29. ACTION1 (sequence 23)",
      "30. RESET (sequence 23)",
      "31. ACTION4 (sequence 24)",
      "Current",
    ]);
    expect(detail?.actions.map((action) => `${action.step}. ${action.actionLabel}`)).toEqual([
      "29. ACTION1 (sequence 23)",
      "30. RESET (sequence 23)",
      "31. ACTION4 (sequence 24)",
    ]);
  });
});
