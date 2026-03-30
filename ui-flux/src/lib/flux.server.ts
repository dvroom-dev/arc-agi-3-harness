import fs from "node:fs/promises";
import path from "node:path";
import { spawn } from "node:child_process";
import { parseHexGrid } from "@/lib/grid";
import { HARNESS_FLUX_ENTRYPOINT, RUNS_DIR, SUPER_FLUX_ENTRYPOINT, runDir } from "@/lib/paths";
import type {
  FluxActionSummary,
  FluxFrameSnapshot,
  FluxPromptPayload,
  FluxRunDetail,
  FluxRunStartRequest,
  FluxRunSummary,
  FluxSessionDetail,
  FluxSessionSummary,
  FluxSessionTimelineEntry,
  FluxSessionType,
} from "@/lib/types";

type JsonRecord = Record<string, unknown>;

const SESSION_TYPES: FluxSessionType[] = ["solver", "modeler", "bootstrapper"];

async function readText(filePath: string): Promise<string | null> {
  try {
    return await fs.readFile(filePath, "utf8");
  } catch {
    return null;
  }
}

async function readJson<T = JsonRecord>(filePath: string): Promise<T | null> {
  const raw = await readText(filePath);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}

async function readJsonLines(filePath: string): Promise<JsonRecord[]> {
  const raw = await readText(filePath);
  if (!raw) return [];
  const lines = raw.split("\n").map((line) => line.trim()).filter(Boolean);
  const items: JsonRecord[] = [];
  for (const line of lines) {
    try {
      const parsed = JSON.parse(line);
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        items.push(parsed as JsonRecord);
      }
    } catch {
      continue;
    }
  }
  return items;
}

function isPidAlive(pid: number | null): boolean {
  if (!pid || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

function normalizeSessionSummary(payload: JsonRecord | null, sessionType: FluxSessionType, sessionId: string): FluxSessionSummary {
  return {
    sessionId,
    sessionType,
    status: typeof payload?.status === "string" ? String(payload.status) : "unknown",
    createdAt: typeof payload?.createdAt === "string" ? String(payload.createdAt) : null,
    updatedAt: typeof payload?.updatedAt === "string" ? String(payload.updatedAt) : null,
    provider: typeof payload?.provider === "string" ? String(payload.provider) : null,
    model: typeof payload?.model === "string" ? String(payload.model) : null,
    stopReason: typeof payload?.stopReason === "string" ? String(payload.stopReason) : null,
    latestAssistantText: typeof payload?.latestAssistantText === "string" ? String(payload.latestAssistantText) : null,
  };
}

async function listSessionSummaries(baseDir: string, sessionType: FluxSessionType): Promise<FluxSessionSummary[]> {
  const sessionRoot = path.join(baseDir, ".ai-flux", "sessions", sessionType);
  const entries = await fs.readdir(sessionRoot, { withFileTypes: true }).catch(() => []);
  const sessions = await Promise.all(entries.filter((entry) => entry.isDirectory()).map(async (entry) => {
    const sessionPath = path.join(sessionRoot, entry.name, "session.json");
    return normalizeSessionSummary(await readJson(sessionPath), sessionType, entry.name);
  }));
  return sessions.sort((left, right) => (right.updatedAt || "").localeCompare(left.updatedAt || ""));
}

async function latestAttemptDir(runRoot: string): Promise<string | null> {
  const attemptsRoot = path.join(runRoot, "flux_instances");
  const entries = await fs.readdir(attemptsRoot, { withFileTypes: true }).catch(() => []);
  const attempts = await Promise.all(entries
    .filter((entry) => entry.isDirectory() && entry.name.startsWith("attempt_"))
    .map(async (entry) => {
      const fullPath = path.join(attemptsRoot, entry.name);
      const stats = await fs.stat(fullPath).catch(() => null);
      return stats ? { fullPath, mtimeMs: stats.mtimeMs } : null;
    }));
  const sorted = attempts.filter(Boolean).sort((left, right) => (right?.mtimeMs || 0) - (left?.mtimeMs || 0));
  return sorted[0]?.fullPath ?? null;
}

async function pickGameDirForRun(runId: string, state: JsonRecord | null): Promise<{ gameDir: string | null; attemptId: string | null }> {
  const root = runDir(runId);
  const active = (state?.active as JsonRecord | undefined)?.solver as JsonRecord | undefined;
  const activeAttemptId = typeof active?.attemptId === "string" ? String(active.attemptId) : null;
  if (activeAttemptId) {
    const candidate = path.join(root, "flux_instances", activeAttemptId, "agent");
    const entries = await fs.readdir(candidate, { withFileTypes: true }).catch(() => []);
    const game = entries.find((entry) => entry.isDirectory() && entry.name.startsWith("game_"));
    if (game) {
      return { gameDir: path.join(candidate, game.name), attemptId: activeAttemptId };
    }
  }
  const latestAttempt = await latestAttemptDir(root);
  if (latestAttempt) {
    const agentDir = path.join(latestAttempt, "agent");
    const entries = await fs.readdir(agentDir, { withFileTypes: true }).catch(() => []);
    const game = entries.find((entry) => entry.isDirectory() && entry.name.startsWith("game_"));
    if (game) {
      return { gameDir: path.join(agentDir, game.name), attemptId: path.basename(latestAttempt) };
    }
  }
  return { gameDir: null, attemptId: null };
}

async function readFrameSnapshots(gameDir: string): Promise<{ frames: FluxFrameSnapshot[]; actions: FluxActionSummary[]; currentLevel: number | null }> {
  const levelCurrentDir = path.join(gameDir, "level_current");
  const meta = await readJson<JsonRecord>(path.join(levelCurrentDir, "meta.json"));
  const currentLevel = typeof meta?.level === "number" ? Number(meta.level) : null;
  const initialHex = await readText(path.join(levelCurrentDir, "initial_state.hex"));
  const currentHex = await readText(path.join(levelCurrentDir, "current_state.hex"));
  const turns = await readJsonLines(path.join(levelCurrentDir, "turn_index.jsonl"));

  const frames: FluxFrameSnapshot[] = [];
  const actions: FluxActionSummary[] = [];
  if (initialHex) {
    frames.push({
      id: "initial",
      label: "Initial",
      grid: parseHexGrid(initialHex),
      actionLabel: null,
      turnDir: null,
      changedPixels: 0,
      stepCount: 0,
    });
  }

  for (let index = 0; index < turns.length; index += 1) {
    const turn = turns[index] ?? {};
    const turnDir = typeof turn.turn_dir === "string" ? String(turn.turn_dir) : null;
    const afterHex = turnDir ? await readText(path.join(gameDir, turnDir, "after_state.hex")) : null;
    const actionLabel = typeof turn.action_label === "string" ? String(turn.action_label) : "unknown";
    const changedPixels = typeof turn.changed_pixels === "number" ? Number(turn.changed_pixels) : 0;
    if (typeof turn.steps_executed === "number" && Number(turn.steps_executed) > 0 && turnDir) {
      actions.push({
        step: actions.length + 1,
        actionLabel,
        changedPixels,
        turnDir,
        stateBefore: typeof turn.state_before_action === "string" ? String(turn.state_before_action) : "",
        stateAfter: typeof turn.state_after_action === "string" ? String(turn.state_after_action) : "",
      });
    }
    if (afterHex && turnDir) {
      frames.push({
        id: `turn-${index + 1}`,
        label: actionLabel,
        grid: parseHexGrid(afterHex),
        actionLabel,
        turnDir,
        changedPixels,
        stepCount: typeof turn.steps_executed === "number" ? Number(turn.steps_executed) : 0,
      });
    }
  }

  if (currentHex) {
    const currentGrid = parseHexGrid(currentHex);
    const lastGrid = frames[frames.length - 1]?.grid;
    const sameAsLast = JSON.stringify(lastGrid) === JSON.stringify(currentGrid);
    if (!sameAsLast) {
      frames.push({
        id: "current",
        label: "Current",
        grid: currentGrid,
        actionLabel: null,
        turnDir: null,
        changedPixels: 0,
        stepCount: actions.length,
      });
    }
  }

  return { frames, actions, currentLevel };
}

function toRunSummary(runId: string, state: JsonRecord | null, runtimeMeta: JsonRecord | null): FluxRunSummary {
  const activeRaw = (state?.active as JsonRecord | undefined) ?? {};
  const active = Object.fromEntries(
    SESSION_TYPES.map((sessionType) => {
      const payload = (activeRaw[sessionType] as JsonRecord | undefined) ?? {};
      return [sessionType, {
        status: typeof payload.status === "string" ? String(payload.status) : "unknown",
        sessionId: typeof payload.sessionId === "string" ? String(payload.sessionId) : null,
      }];
    }),
  ) as FluxRunSummary["active"];
  const status = typeof state?.status === "string" ? String(state.status) : "missing";
  const pid = typeof state?.pid === "number" ? Number(state.pid) : null;
  return {
    runId,
    gameId: typeof runtimeMeta?.game_id === "string" ? String(runtimeMeta.game_id) : null,
    updatedAt: typeof state?.updatedAt === "string" ? String(state.updatedAt) : null,
    startedAt: typeof state?.startedAt === "string" ? String(state.startedAt) : null,
    status,
    liveStatus: status === "running" ? (isPidAlive(pid) ? "running" : "stale") : (status === "missing" ? "missing" : "stopped"),
    active,
  };
}

export async function listFluxRuns(): Promise<FluxRunSummary[]> {
  const entries = await fs.readdir(RUNS_DIR, { withFileTypes: true }).catch(() => []);
  const runs = await Promise.all(entries.filter((entry) => entry.isDirectory()).map(async (entry) => {
    const root = path.join(RUNS_DIR, entry.name);
    const fluxState = await readJson<JsonRecord>(path.join(root, "flux", "state.json"));
    if (!fluxState) return null;
    const runtimeMeta = await readJson<JsonRecord>(path.join(root, "flux_runtime.json"));
    return toRunSummary(entry.name, fluxState, runtimeMeta);
  }));
  return runs.filter(Boolean).sort((left, right) => (right?.updatedAt || "").localeCompare(left?.updatedAt || "")) as FluxRunSummary[];
}

export async function readFluxRunDetail(runId: string): Promise<FluxRunDetail | null> {
  const root = runDir(runId);
  const state = await readJson<JsonRecord>(path.join(root, "flux", "state.json"));
  if (!state) return null;
  const runtimeMeta = await readJson<JsonRecord>(path.join(root, "flux_runtime.json"));
  const summary = toRunSummary(runId, state, runtimeMeta);
  const currentState = await readJson<JsonRecord>(path.join(root, "supervisor", "arc", "state.json"));
  const queues = Object.fromEntries(await Promise.all(SESSION_TYPES.map(async (sessionType) => {
    const queue = await readJson<{ items?: unknown[] }>(path.join(root, "flux", "queues", `${sessionType}.json`));
    return [sessionType, { length: Array.isArray(queue?.items) ? queue.items.length : 0 }];
  }))) as FluxRunDetail["queues"];
  const { gameDir, attemptId } = await pickGameDirForRun(runId, state);
  const timeline = gameDir ? await readFrameSnapshots(gameDir) : { frames: [], actions: [], currentLevel: null };
  const sessionHistory = Object.fromEntries(await Promise.all(SESSION_TYPES.map(async (sessionType) => {
    return [sessionType, await listSessionSummaries(root, sessionType)];
  }))) as FluxRunDetail["sessionHistory"];
  return {
    ...summary,
    queues,
    selectedGameDir: gameDir,
    currentState,
    currentLevel: timeline.currentLevel,
    currentAttemptId: attemptId,
    frames: timeline.frames,
    actions: timeline.actions,
    sessionHistory,
  };
}

function summarizeToolEvent(raw: JsonRecord): FluxSessionTimelineEntry | null {
  const event = (raw.event as JsonRecord | undefined) ?? {};
  const item = (event.item as JsonRecord | undefined) ?? {};
  const kind = typeof item.kind === "string" ? String(item.kind) : typeof item.type === "string" ? String(item.type) : "";
  if (!["tool_call", "tool_result"].includes(kind) && item.type !== "commandExecution") return null;
  return {
    kind,
    ts: typeof raw.ts === "string" ? String(raw.ts) : null,
    title: typeof item.summary === "string" ? String(item.summary) : (typeof item.name === "string" ? String(item.name) : kind),
    text: typeof item.text === "string" ? String(item.text) : null,
    raw: raw.event ?? raw,
  };
}

export async function readFluxSessionDetail(runId: string, sessionType: FluxSessionType, sessionId: string): Promise<FluxSessionDetail | null> {
  const root = runDir(runId);
  const sessionRoot = path.join(root, ".ai-flux", "sessions", sessionType, sessionId);
  const session = normalizeSessionSummary(await readJson(path.join(sessionRoot, "session.json")), sessionType, sessionId);
  const messages = await readJsonLines(path.join(sessionRoot, "messages.jsonl"));
  const promptDir = path.join(sessionRoot, "prompts");
  const promptEntries = await fs.readdir(promptDir, { withFileTypes: true }).catch(() => []);
  const prompts: FluxPromptPayload[] = [];
  for (const entry of promptEntries.filter((candidate) => candidate.isFile()).sort((left, right) => left.name.localeCompare(right.name))) {
    prompts.push({
      fileName: entry.name,
      payload: await readJson(path.join(promptDir, entry.name)),
    });
  }
  const rawEvents = await readJsonLines(path.join(sessionRoot, "provider_raw", "events.ndjson"));
  const toolEvents = rawEvents.map(summarizeToolEvent).filter(Boolean) as FluxSessionTimelineEntry[];
  return { session, prompts, messages, toolEvents };
}

function spawnDetached(command: string, args: string[], cwd: string, env?: Record<string, string>) {
  const child = spawn(command, args, {
    cwd,
    env: { ...process.env, ...(env ?? {}) },
    detached: true,
    stdio: "ignore",
  });
  child.unref();
}

export async function startFluxRun(input: FluxRunStartRequest): Promise<{ runId: string }> {
  spawnDetached("python", [
    HARNESS_FLUX_ENTRYPOINT,
    "--game-id",
    input.gameId,
    "--operation-mode",
    input.operationMode,
    "--session-name",
    input.sessionName,
    "--provider",
    input.provider,
  ], path.dirname(HARNESS_FLUX_ENTRYPOINT));
  return { runId: input.sessionName };
}

export async function controlFluxRun(runId: string, action: "stop" | "continue"): Promise<{ ok: true }> {
  const root = runDir(runId);
  if (action === "stop") {
    await new Promise<void>((resolve, reject) => {
      const child = spawn("bun", ["run", SUPER_FLUX_ENTRYPOINT, "stop", "--workspace", root, "--config", path.join(root, "flux.yaml")], {
        cwd: root,
        env: process.env,
        stdio: "ignore",
      });
      child.on("error", reject);
      child.on("exit", (code) => code === 0 ? resolve() : reject(new Error(`flux stop failed: ${code}`)));
    });
    return { ok: true };
  }
  const metaPath = path.join(root, "flux_runtime.json");
  spawnDetached("bun", ["run", SUPER_FLUX_ENTRYPOINT, "run", "--workspace", root, "--config", path.join(root, "flux.yaml")], root, {
    ARC_FLUX_META_PATH: metaPath,
  });
  return { ok: true };
}
