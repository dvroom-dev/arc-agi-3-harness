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

async function listJsonFiles(dirPath: string): Promise<string[]> {
  const entries = await fs.readdir(dirPath, { withFileTypes: true }).catch(() => []);
  return entries
    .filter((entry) => entry.isFile() && entry.name.endsWith(".json"))
    .map((entry) => path.join(dirPath, entry.name))
    .sort((left, right) => left.localeCompare(right));
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

async function readActiveSessionRecords(runRoot: string, state: JsonRecord | null): Promise<Partial<Record<FluxSessionType, JsonRecord | null>>> {
  const activeRaw = (state?.active as JsonRecord | undefined) ?? {};
  const records: Partial<Record<FluxSessionType, JsonRecord | null>> = {};
  for (const sessionType of SESSION_TYPES) {
    const payload = (activeRaw[sessionType] as JsonRecord | undefined) ?? {};
    const sessionId = typeof payload.sessionId === "string" ? String(payload.sessionId) : null;
    if (!sessionId) {
      records[sessionType] = null;
      continue;
    }
    records[sessionType] = await readJson<JsonRecord>(
      path.join(runRoot, ".ai-flux", "sessions", sessionType, sessionId, "session.json"),
    );
  }
  return records;
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
  const durableAgentDir = path.join(root, "agent");
  const durableEntries = await fs.readdir(durableAgentDir, { withFileTypes: true }).catch(() => []);
  const durableGame = durableEntries.find((entry) => entry.isDirectory() && entry.name.startsWith("game_"));
  if (durableGame) {
    return { gameDir: path.join(durableAgentDir, durableGame.name), attemptId: null };
  }
  return { gameDir: null, attemptId: null };
}

async function readFrameSnapshots(gameDir: string): Promise<{ frames: FluxFrameSnapshot[]; actions: FluxActionSummary[]; currentLevel: number | null }> {
  const levelCurrentDir = path.join(gameDir, "level_current");
  const meta = await readJson<JsonRecord>(path.join(levelCurrentDir, "meta.json"));
  const currentLevel = typeof meta?.level === "number" ? Number(meta.level) : null;
  const initialHex = await readText(path.join(levelCurrentDir, "initial_state.hex"));
  const currentHex = await readText(path.join(levelCurrentDir, "current_state.hex"));
  const frames: FluxFrameSnapshot[] = [];
  const actions: FluxActionSummary[] = [];
  let lastActionLabel: string | null = null;
  if (initialHex) {
    frames.push({
      id: "initial",
      label: "Initial",
      grid: parseHexGrid(initialHex),
      actionLabel: null,
      lastActionLabel: null,
      turnDir: null,
      changedPixels: 0,
      stepCount: 0,
    });
  }
  const levelDir = currentLevel ? path.join(gameDir, `level_${currentLevel}`) : levelCurrentDir;
  const sequenceRoot = path.join(levelDir, "sequences");
  const sequenceFiles = await listJsonFiles(sequenceRoot);
  type ActionRecord = {
    actionIndex: number;
    actionLabel: string;
    changedPixels: number;
    turnDir: string;
    stateBefore: string;
    stateAfter: string;
    afterGrid: number[][];
  };
  const actionRecords: ActionRecord[] = [];
  for (const sequenceFile of sequenceFiles) {
    const sequence = await readJson<JsonRecord>(sequenceFile);
    const sequenceActions = Array.isArray(sequence?.actions) ? sequence.actions : [];
    for (const action of sequenceActions) {
      if (!action || typeof action !== "object" || Array.isArray(action)) continue;
      const record = action as JsonRecord;
      const actionIndex = typeof record.action_index === "number"
        ? Number(record.action_index)
        : (typeof record.local_step === "number" ? Number(record.local_step) : actionRecords.length + 1);
      const actionLabel = typeof record.action_name === "string" ? String(record.action_name) : "UNKNOWN";
      const files = (record.files && typeof record.files === "object" && !Array.isArray(record.files))
        ? record.files as JsonRecord
        : {};
      const afterStatePath = typeof files.after_state_hex === "string"
        ? path.join(levelDir, String(files.after_state_hex))
        : null;
      const afterHex = afterStatePath ? await readText(afterStatePath) : null;
      if (!afterHex) continue;
      const beforeHex = typeof files.before_state_hex === "string"
        ? await readText(path.join(levelDir, String(files.before_state_hex)))
        : null;
      const beforeGrid = beforeHex ? parseHexGrid(beforeHex) : null;
      const afterGrid = parseHexGrid(afterHex);
      const rows = Math.max(beforeGrid?.length ?? 0, afterGrid.length);
      const cols = Math.max(
        ...Array.from({ length: rows }, (_, index) => Math.max(beforeGrid?.[index]?.length ?? 0, afterGrid[index]?.length ?? 0)),
        0,
      );
      let changedPixels = 0;
      for (let row = 0; row < rows; row += 1) {
        for (let col = 0; col < cols; col += 1) {
          const beforeValue = beforeGrid?.[row]?.[col] ?? null;
          const afterValue = afterGrid[row]?.[col] ?? null;
          if (beforeValue !== afterValue) changedPixels += 1;
        }
      }
      const turnDir = typeof record.tool_turn === "number"
        ? `level_${currentLevel ?? 1}/turn_${String(Number(record.tool_turn)).padStart(4, "0")}`
        : path.relative(gameDir, path.dirname(afterStatePath ?? levelDir));
      actionRecords.push({
        actionIndex,
        actionLabel,
        changedPixels,
        turnDir,
        stateBefore: typeof record.state_before === "string" ? String(record.state_before) : "",
        stateAfter: typeof record.state_after === "string" ? String(record.state_after) : "",
        afterGrid,
      });
    }
  }
  actionRecords.sort((left, right) => left.actionIndex - right.actionIndex);
  for (const action of actionRecords) {
    lastActionLabel = action.actionLabel;
    actions.push({
      step: actions.length + 1,
      actionLabel: action.actionLabel,
      changedPixels: action.changedPixels,
      turnDir: action.turnDir,
      stateBefore: action.stateBefore,
      stateAfter: action.stateAfter,
    });
    frames.push({
      id: `action-${action.actionIndex}`,
      label: `${actions.length}. ${action.actionLabel}`,
      grid: action.afterGrid,
      actionLabel: action.actionLabel,
      lastActionLabel,
      turnDir: action.turnDir,
      changedPixels: action.changedPixels,
      stepCount: actions.length,
    });
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
        actionLabel: lastActionLabel,
        lastActionLabel,
        turnDir: null,
        changedPixels: 0,
        stepCount: actions.length,
      });
    }
  }

  return { frames, actions, currentLevel };
}

function toRunSummary(
  runId: string,
  state: JsonRecord | null,
  runtimeMeta: JsonRecord | null,
  activeSessionRecords: Partial<Record<FluxSessionType, JsonRecord | null>> = {},
  latestSessionSummaries: Partial<Record<FluxSessionType, FluxSessionSummary[]>> = {},
): FluxRunSummary {
  const activeRaw = (state?.active as JsonRecord | undefined) ?? {};
  const status = typeof state?.status === "string" ? String(state.status) : "missing";
  const pid = typeof state?.pid === "number" ? Number(state.pid) : null;
  const isLive = status === "running" && isPidAlive(pid);
  const active = Object.fromEntries(
    SESSION_TYPES.map((sessionType) => {
      const payload = (activeRaw[sessionType] as JsonRecord | undefined) ?? {};
      const sessionRecord = activeSessionRecords[sessionType] ?? null;
      const sessionStatus = typeof sessionRecord?.status === "string"
        ? String(sessionRecord.status)
        : (typeof payload.status === "string" ? String(payload.status) : "unknown");
      const latestRunningSession = (latestSessionSummaries[sessionType] ?? []).find((session) => session.status === "running") ?? null;
      const resolvedSessionId = latestRunningSession && sessionStatus !== "running"
        ? latestRunningSession.sessionId
        : (typeof payload.sessionId === "string" ? String(payload.sessionId) : null);
      const resolvedStatus = latestRunningSession && sessionStatus !== "running"
        ? latestRunningSession.status
        : sessionStatus;
      return [sessionType, {
        status: isLive ? resolvedStatus : "idle",
        sessionId: resolvedSessionId,
      }];
    }),
  ) as FluxRunSummary["active"];
  return {
    runId,
    gameId: typeof runtimeMeta?.game_id === "string" ? String(runtimeMeta.game_id) : null,
    updatedAt: typeof state?.updatedAt === "string" ? String(state.updatedAt) : null,
    startedAt: typeof state?.startedAt === "string" ? String(state.startedAt) : null,
    status,
    liveStatus: status === "running" ? (isLive ? "running" : "stale") : (status === "missing" ? "missing" : "stopped"),
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
    const activeSessionRecords = await readActiveSessionRecords(root, fluxState);
    const latestSessionSummaries = Object.fromEntries(await Promise.all(
      SESSION_TYPES.map(async (sessionType) => [sessionType, await listSessionSummaries(root, sessionType)]),
    )) as Partial<Record<FluxSessionType, FluxSessionSummary[]>>;
    return toRunSummary(entry.name, fluxState, runtimeMeta, activeSessionRecords, latestSessionSummaries);
  }));
  return runs.filter(Boolean).sort((left, right) => (right?.updatedAt || "").localeCompare(left?.updatedAt || "")) as FluxRunSummary[];
}

export async function readFluxRunDetail(runId: string): Promise<FluxRunDetail | null> {
  const root = runDir(runId);
  const state = await readJson<JsonRecord>(path.join(root, "flux", "state.json"));
  if (!state) return null;
  const runtimeMeta = await readJson<JsonRecord>(path.join(root, "flux_runtime.json"));
  const activeSessionRecords = await readActiveSessionRecords(root, state);
  const sessionHistory = Object.fromEntries(await Promise.all(SESSION_TYPES.map(async (sessionType) => {
    return [sessionType, await listSessionSummaries(root, sessionType)];
  }))) as FluxRunDetail["sessionHistory"];
  const summary = toRunSummary(runId, state, runtimeMeta, activeSessionRecords, sessionHistory);
  const currentState = await readJson<JsonRecord>(path.join(root, "supervisor", "arc", "state.json"));
  const queues = Object.fromEntries(await Promise.all(SESSION_TYPES.map(async (sessionType) => {
    const queue = await readJson<{ items?: unknown[] }>(path.join(root, "flux", "queues", `${sessionType}.json`));
    return [sessionType, { length: Array.isArray(queue?.items) ? queue.items.length : 0 }];
  }))) as FluxRunDetail["queues"];
  const { gameDir, attemptId } = await pickGameDirForRun(runId, state);
  const timeline = gameDir ? await readFrameSnapshots(gameDir) : { frames: [], actions: [], currentLevel: null };
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

function safeRunIdPrefix(value: string): string {
  const normalized = String(value || "")
    .trim()
    .replace(/[^A-Za-z0-9_.-]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return normalized || "flux-ui";
}

function uniqueRunId(prefix: string): string {
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  return `${safeRunIdPrefix(prefix)}-${stamp}`;
}

export async function startFluxRun(input: FluxRunStartRequest): Promise<{ runId: string }> {
  const runId = uniqueRunId(input.sessionName);
  spawnDetached("python", [
    HARNESS_FLUX_ENTRYPOINT,
    "--game-id",
    input.gameId,
    "--operation-mode",
    input.operationMode,
    "--session-name",
    runId,
    "--provider",
    input.provider,
  ], path.dirname(HARNESS_FLUX_ENTRYPOINT));
  return { runId };
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
