import { afterEach, describe, expect, test } from "bun:test";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { cleanupLaunchTempArtifacts, readFluxRunDetail } from "@/lib/flux.server";
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
    ]);
    expect(detail?.actions.map((action) => `${action.step}. ${action.actionLabel}`)).toEqual([
      "29. ACTION1 (sequence 23)",
      "30. RESET (sequence 23)",
      "31. ACTION4 (sequence 24)",
    ]);
  });

  test("cleanupLaunchTempArtifacts removes only stale known temp roots under inode pressure", async () => {
    const tmpRoot = await fs.mkdtemp(path.join(os.tmpdir(), "ui-flux-cleanup-"));
    try {
      const staleFlow = path.join(tmpRoot, "flux-flow-e2e-stale");
      const staleHarness = path.join(tmpRoot, "harnessdebug-frontier");
      const recentFlow = path.join(tmpRoot, "flux-flow-e2e-recent");
      const unrelated = path.join(tmpRoot, "keep-me");
      const pytestRoot = path.join(tmpRoot, "pytest-of-dvroom");
      const stalePytestChild = path.join(pytestRoot, "pytest-101");
      const recentPytestChild = path.join(pytestRoot, "pytest-202");

      await fs.mkdir(staleFlow, { recursive: true });
      await fs.mkdir(staleHarness, { recursive: true });
      await fs.mkdir(recentFlow, { recursive: true });
      await fs.mkdir(unrelated, { recursive: true });
      await fs.mkdir(stalePytestChild, { recursive: true });
      await fs.mkdir(recentPytestChild, { recursive: true });

      const nowMs = Date.now();
      const staleMs = nowMs - (16 * 60 * 1000);
      const recentMs = nowMs - (5 * 60 * 1000);
      await fs.utimes(staleFlow, staleMs / 1000, staleMs / 1000);
      await fs.utimes(staleHarness, staleMs / 1000, staleMs / 1000);
      await fs.utimes(stalePytestChild, staleMs / 1000, staleMs / 1000);
      await fs.utimes(recentFlow, recentMs / 1000, recentMs / 1000);
      await fs.utimes(recentPytestChild, recentMs / 1000, recentMs / 1000);
      await fs.utimes(unrelated, staleMs / 1000, staleMs / 1000);

      const result = await cleanupLaunchTempArtifacts(tmpRoot, nowMs, 0);
      expect(result.removed).toBe(3);
      expect(await fs.stat(recentFlow).then(() => true).catch(() => false)).toBe(true);
      expect(await fs.stat(recentPytestChild).then(() => true).catch(() => false)).toBe(true);
      expect(await fs.stat(unrelated).then(() => true).catch(() => false)).toBe(true);
      expect(await fs.stat(staleFlow).then(() => true).catch(() => false)).toBe(false);
      expect(await fs.stat(staleHarness).then(() => true).catch(() => false)).toBe(false);
      expect(await fs.stat(stalePytestChild).then(() => true).catch(() => false)).toBe(false);
    } finally {
      await fs.rm(tmpRoot, { recursive: true, force: true });
    }
  });

  test("uses durable model workspace for coverage counts even when the active attempt surface is thin", async () => {
    const runId = `ui-flux-coverage-${Date.now()}`;
    createdRuns.push(runId);
    const runRoot = path.join(RUNS_DIR, runId);
    const attemptRoot = path.join(runRoot, "flux_instances", "attempt_live");
    const attemptGame = path.join(attemptRoot, "agent", "game_ls20");
    const durableGame = path.join(runRoot, "agent", "game_ls20");

    await fs.mkdir(path.join(runRoot, "flux"), { recursive: true });
    await fs.mkdir(path.join(runRoot, "flux", "model", "current"), { recursive: true });
    await fs.mkdir(path.join(runRoot, ".ai-flux", "sessions", "solver", "solver_attempt_live"), { recursive: true });
    await fs.mkdir(path.join(attemptRoot, "supervisor", "arc"), { recursive: true });
    await fs.mkdir(path.join(attemptGame, "level_current", "sequence_compare"), { recursive: true });
    await fs.mkdir(path.join(attemptGame, "level_current", "sequences"), { recursive: true });
    await fs.mkdir(path.join(durableGame, "level_1", "sequences"), { recursive: true });

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
        current_level: 1,
        levels_completed: 0,
        state: "NOT_FINISHED",
        win_levels: 7,
      }, null, 2),
      "utf8",
    );
    await fs.writeFile(path.join(attemptGame, "level_current", "meta.json"), JSON.stringify({ level: 1 }, null, 2), "utf8");
    await fs.writeFile(path.join(attemptGame, "level_current", "initial_state.hex"), "0\n", "utf8");
    await fs.writeFile(path.join(attemptGame, "level_current", "current_state.hex"), "1\n", "utf8");
    await fs.writeFile(
      path.join(attemptGame, "level_current", "sequence_compare", "current_compare.json"),
      JSON.stringify({
        level: 1,
        all_match: true,
        requested_sequences: 1,
        compared_sequences: 1,
        diverged_sequences: 0,
        reports: [{ level: 1, sequence_id: "seq_0001", matched: true }],
      }, null, 2),
      "utf8",
    );
    await fs.writeFile(
      path.join(attemptGame, "level_current", "sequences", "seq_0001.json"),
      JSON.stringify({ level: 1, sequence_id: "seq_0001" }, null, 2),
      "utf8",
    );

    await fs.writeFile(
      path.join(durableGame, "level_1", "sequences", "seq_0001.json"),
      JSON.stringify({ level: 1, sequence_id: "seq_0001" }, null, 2),
      "utf8",
    );
    await fs.writeFile(
      path.join(durableGame, "level_1", "sequences", "seq_0002.json"),
      JSON.stringify({ level: 1, sequence_id: "seq_0002" }, null, 2),
      "utf8",
    );
    await fs.writeFile(
      path.join(durableGame, "current_compare.json"),
      JSON.stringify({
        level: 1,
        all_match: false,
        requested_sequences: 2,
        compared_sequences: 2,
        diverged_sequences: 1,
        reports: [
          { level: 1, sequence_id: "seq_0001", matched: true },
          { level: 1, sequence_id: "seq_0002", matched: false, divergence_step: 3, divergence_reason: "intermediate_frame_mismatch" },
        ],
      }, null, 2),
      "utf8",
    );
    await fs.writeFile(
      path.join(runRoot, "flux", "model", "current", "meta.json"),
      JSON.stringify({
        revisionId: "rev_accepted",
        summary: {
          level: 1,
          allMatch: false,
          coveredSequenceIds: ["level_1:seq_0001", "level_1:seq_0002"],
          contiguousMatchedSequences: 2,
          firstFailingSequenceId: "seq_0003",
          firstFailingStep: 1,
          firstFailingReason: "intermediate_frame_mismatch",
          frontierDiscovered: false,
          compareKind: "accepted",
        },
      }, null, 2),
      "utf8",
    );

    const detail = await readFluxRunDetail(runId);
    expect(detail).not.toBeNull();
    expect(detail?.selectedGameDir?.includes("attempt_live")).toBe(true);
    expect(detail?.generatedSequenceCount).toBe(2);
    expect(detail?.acceptedCoverageLevel).toBe(1);
    expect(detail?.acceptedCoverageMatchedSequences).toBe(2);
    expect(detail?.acceptedCoverageHighestSequenceId).toBe("seq_0002");
  });

  test("prefers active modeler evidence bundle for generated sequence counts and active slot status over stale session status", async () => {
    const runId = `ui-flux-modeler-active-${Date.now()}`;
    createdRuns.push(runId);
    const runRoot = path.join(RUNS_DIR, runId);
    const durableGame = path.join(runRoot, "agent", "game_ls20");
    const activeBundle = path.join(runRoot, "flux", "evidence_bundles", "bundle_live");

    await fs.mkdir(path.join(runRoot, "flux", "model", "current"), { recursive: true });
    await fs.mkdir(path.join(runRoot, "flux", "invocations", "q_model_live"), { recursive: true });
    await fs.mkdir(path.join(runRoot, "flux", "queues"), { recursive: true });
    await fs.mkdir(path.join(runRoot, ".ai-flux", "sessions", "modeler", "modeler_run"), { recursive: true });
    await fs.mkdir(path.join(durableGame, "level_1", "sequences"), { recursive: true });
    await fs.mkdir(path.join(activeBundle, "workspace", "game_ls20", "level_1", "sequences"), { recursive: true });
    await fs.mkdir(path.join(activeBundle, "workspace", "game_ls20", "level_2", "sequences"), { recursive: true });

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
          solver: { status: "idle" },
          modeler: {
            sessionId: "modeler_run",
            invocationId: "q_model_live",
            status: "running",
          },
          bootstrapper: { status: "idle" },
        },
      }, null, 2),
      "utf8",
    );
    await fs.writeFile(
      path.join(runRoot, ".ai-flux", "sessions", "modeler", "modeler_run", "session.json"),
      JSON.stringify({
        sessionId: "modeler_run",
        sessionType: "modeler",
        status: "idle",
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        provider: "codex",
        model: "gpt-5.4",
      }, null, 2),
      "utf8",
    );
    await fs.writeFile(
      path.join(runRoot, "flux", "invocations", "q_model_live", "input.json"),
      JSON.stringify({
        invocationId: "q_model_live",
        payload: {
          evidenceBundlePath: activeBundle,
          evidenceWatermark: "wm_live",
        },
      }, null, 2),
      "utf8",
    );
    await fs.writeFile(
      path.join(runRoot, "flux", "queues", "modeler.json"),
      JSON.stringify({ sessionType: "modeler", updatedAt: new Date().toISOString(), items: [] }, null, 2),
      "utf8",
    );
    await fs.writeFile(
      path.join(runRoot, "flux", "model", "current", "meta.json"),
      JSON.stringify({
        revisionId: "model_rev_live",
        summary: {
          level: 1,
          allMatch: true,
          coveredSequenceIds: ["level_1:seq_0001", "level_1:seq_0002"],
          contiguousMatchedSequences: 2,
          firstFailingSequenceId: null,
          firstFailingStep: null,
          firstFailingReason: null,
          frontierDiscovered: false,
          compareKind: "accepted",
        },
      }, null, 2),
      "utf8",
    );
    await fs.writeFile(path.join(durableGame, "level_1", "sequences", "seq_0001.json"), JSON.stringify({ level: 1, sequence_id: "seq_0001" }, null, 2), "utf8");
    await fs.writeFile(path.join(durableGame, "level_1", "sequences", "seq_0002.json"), JSON.stringify({ level: 1, sequence_id: "seq_0002" }, null, 2), "utf8");
    await fs.writeFile(path.join(activeBundle, "workspace", "game_ls20", "level_1", "sequences", "seq_0001.json"), JSON.stringify({ level: 1, sequence_id: "seq_0001" }, null, 2), "utf8");
    await fs.writeFile(path.join(activeBundle, "workspace", "game_ls20", "level_1", "sequences", "seq_0002.json"), JSON.stringify({ level: 1, sequence_id: "seq_0002" }, null, 2), "utf8");
    await fs.writeFile(path.join(activeBundle, "workspace", "game_ls20", "level_1", "sequences", "seq_0003.json"), JSON.stringify({ level: 1, sequence_id: "seq_0003" }, null, 2), "utf8");
    await fs.writeFile(path.join(activeBundle, "workspace", "game_ls20", "level_2", "sequences", "seq_0001.json"), JSON.stringify({ level: 2, sequence_id: "seq_0001" }, null, 2), "utf8");

    const detail = await readFluxRunDetail(runId);
    expect(detail).not.toBeNull();
    expect(detail?.generatedSequenceCount).toBe(4);
    expect(detail?.acceptedCoverageMatchedSequences).toBe(2);
    expect(detail?.sessionHistory.modeler[0]?.status).toBe("running");
    expect(detail?.currentModelerTargetLevel).toBe(1);
    expect(detail?.currentModelerTargetSequenceId).toBe("seq_0003");
    expect(detail?.currentModelerTargetReason).toBe("awaiting compare");
  });

  test("hides queued work and current modeler target once the run is stopped", async () => {
    const runId = `ui-flux-stopped-${Date.now()}`;
    createdRuns.push(runId);
    const runRoot = path.join(RUNS_DIR, runId);

    await fs.mkdir(path.join(runRoot, "flux", "queues"), { recursive: true });
    await fs.mkdir(path.join(runRoot, "flux", "model", "current"), { recursive: true });
    await fs.mkdir(path.join(runRoot, ".ai-flux", "sessions", "modeler", "modeler_run"), { recursive: true });

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
        status: "stopped",
        stopRequested: true,
        active: {
          solver: { status: "idle" },
          modeler: { sessionId: "modeler_run", invocationId: "q_old", status: "idle" },
          bootstrapper: { status: "idle" },
        },
      }, null, 2),
      "utf8",
    );
    await fs.writeFile(
      path.join(runRoot, "flux", "queues", "modeler.json"),
      JSON.stringify({
        sessionType: "modeler",
        updatedAt: new Date().toISOString(),
        items: [{ id: "q_stale", sessionType: "modeler", createdAt: new Date().toISOString(), reason: "solver_stopped", payload: { evidenceBundleId: "bundle_x" } }],
      }, null, 2),
      "utf8",
    );
    await fs.writeFile(
      path.join(runRoot, ".ai-flux", "sessions", "modeler", "modeler_run", "session.json"),
      JSON.stringify({
        sessionId: "modeler_run",
        sessionType: "modeler",
        status: "idle",
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        provider: "codex",
        model: "gpt-5.4",
      }, null, 2),
      "utf8",
    );
    await fs.writeFile(
      path.join(runRoot, "flux", "events.jsonl"),
      JSON.stringify({
        kind: "modeler.acceptance_failed",
        summary: "compare mismatch at level 1 sequence seq_0005 step 13: state_transition_mismatch",
      }) + "\n",
      "utf8",
    );

    const detail = await readFluxRunDetail(runId);
    expect(detail).not.toBeNull();
    expect(detail?.queues.modeler.length).toBe(0);
    expect(detail?.queues.modeler.reason).toBeNull();
    expect(detail?.currentModelerTargetSequenceId).toBeNull();
    expect(detail?.currentModelerTargetLevel).toBeNull();
  });

  test("preserves failed session status and normalizes JSON stop reasons", async () => {
    const runId = `ui-flux-failed-session-${Date.now()}`;
    createdRuns.push(runId);
    const runRoot = path.join(RUNS_DIR, runId);

    await fs.mkdir(path.join(runRoot, "flux"), { recursive: true });
    await fs.mkdir(path.join(runRoot, ".ai-flux", "sessions", "bootstrapper", "bootstrapper_run"), { recursive: true });
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
          solver: { status: "idle" },
          modeler: { status: "idle" },
          bootstrapper: { sessionId: "bootstrapper_run", invocationId: "q_boot", status: "idle" },
        },
      }, null, 2),
      "utf8",
    );
    await fs.writeFile(
      path.join(runRoot, ".ai-flux", "sessions", "bootstrapper", "bootstrapper_run", "session.json"),
      JSON.stringify({
        sessionId: "bootstrapper_run",
        sessionType: "bootstrapper",
        status: "failed",
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        provider: "codex",
        model: "gpt-5.4",
        stopReason: "{\"detail\":\"Bad Request\"}",
      }, null, 2),
      "utf8",
    );

    const detail = await readFluxRunDetail(runId);
    expect(detail).not.toBeNull();
    expect(detail?.sessionHistory.bootstrapper[0]?.status).toBe("failed");
    expect(detail?.sessionHistory.bootstrapper[0]?.stopReason).toBe("Bad Request");
  });
});
