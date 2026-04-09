import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import { readFrameSnapshots } from "@/lib/flux.frames";
import { HARNESS_FLUX_ENTRYPOINT, RUNS_DIR, SUPER_FLUX_ENTRYPOINT, runDir } from "@/lib/paths";
import type {
  FluxPromptPayload,
  FluxQueuePreview,
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
const TMP_INODE_CLEANUP_THRESHOLD = 85;
const TMP_CLEANUP_STALE_MS = 15 * 60 * 1000;
const TMP_CLEANUP_PREFIXES = [
  "flux-flow-e2e-",
  "flux-modeler-",
  "flux-orchestrator-",
  "harnessdebug-",
  "super-v2-manual-",
];

async function readCommandStdout(command: string, args: string[]): Promise<string> {
  return await new Promise<string>((resolve, reject) => {
    const child = spawn(command, args, { stdio: ["ignore", "pipe", "pipe"] });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => {
      stdout += String(chunk);
    });
    child.stderr.on("data", (chunk) => {
      stderr += String(chunk);
    });
    child.on("error", reject);
    child.on("exit", (code) => {
      if (code === 0) {
        resolve(stdout);
        return;
      }
      reject(new Error(stderr.trim() || `${command} exited with code ${code ?? -1}`));
    });
  });
}

async function readTmpInodeUsePercent(tmpRoot: string): Promise<number | null> {
  try {
    const stdout = await readCommandStdout("df", ["-iP", tmpRoot]);
    const lines = stdout.trim().split("\n");
    const line = lines[lines.length - 1] ?? "";
    const columns = line.trim().split(/\s+/);
    const useToken = columns.find((token) => token.endsWith("%")) ?? "";
    const parsed = Number.parseInt(useToken.replace("%", ""), 10);
    return Number.isFinite(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

async function removeStaleTempEntry(entryPath: string, staleBeforeMs: number): Promise<number> {
  try {
    const stat = await fs.stat(entryPath);
    if (stat.mtimeMs >= staleBeforeMs) return 0;
    await fs.rm(entryPath, { recursive: true, force: true });
    return 1;
  } catch {
    return 0;
  }
}

export async function cleanupLaunchTempArtifacts(
  tmpRoot = os.tmpdir(),
  nowMs = Date.now(),
  minInodeUsePercent = TMP_INODE_CLEANUP_THRESHOLD,
): Promise<{ removed: number; inodeUsePercent: number | null }> {
  const inodeUsePercent = await readTmpInodeUsePercent(tmpRoot);
  if (inodeUsePercent === null || inodeUsePercent < minInodeUsePercent) {
    return { removed: 0, inodeUsePercent };
  }
  const staleBeforeMs = nowMs - TMP_CLEANUP_STALE_MS;
  let removed = 0;
  const entries = await fs.readdir(tmpRoot, { withFileTypes: true }).catch(() => []);
  for (const entry of entries) {
    if (!entry.isDirectory()) continue;
    const entryPath = path.join(tmpRoot, entry.name);
    if (TMP_CLEANUP_PREFIXES.some((prefix) => entry.name.startsWith(prefix))) {
      removed += await removeStaleTempEntry(entryPath, staleBeforeMs);
      continue;
    }
    if (entry.name.startsWith("pytest-of-")) {
      const childEntries = await fs.readdir(entryPath, { withFileTypes: true }).catch(() => []);
      for (const child of childEntries) {
        if (!child.isDirectory()) continue;
        removed += await removeStaleTempEntry(path.join(entryPath, child.name), staleBeforeMs);
      }
    }
  }
  return { removed, inodeUsePercent };
}

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
    promptCount: 0,
    userMessageCount: 0,
    assistantMessageCount: 0,
  };
}

async function readSessionActivityCounts(sessionRoot: string): Promise<{
  promptCount: number;
  userMessageCount: number;
  assistantMessageCount: number;
}> {
  const promptDir = path.join(sessionRoot, "prompts");
  const promptEntries = await fs.readdir(promptDir, { withFileTypes: true }).catch(() => []);
  const promptCount = promptEntries.filter((entry) => entry.isFile()).length;
  const messages = await readJsonLines(path.join(sessionRoot, "messages.jsonl"));
  let userMessageCount = 0;
  let assistantMessageCount = 0;
  for (const message of messages) {
    const kind = typeof message.kind === "string" ? String(message.kind) : "";
    if (kind === "user") userMessageCount += 1;
    if (kind === "assistant") assistantMessageCount += 1;
  }
  return { promptCount, userMessageCount, assistantMessageCount };
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

async function readAttemptArcState(attemptRoot: string | null): Promise<JsonRecord | null> {
  if (!attemptRoot) return null;
  return await readJson<JsonRecord>(path.join(attemptRoot, "supervisor", "arc", "state.json"));
}

async function listSessionSummaries(baseDir: string, sessionType: FluxSessionType): Promise<FluxSessionSummary[]> {
  return listSessionSummariesWithOptions(baseDir, sessionType, { includeActivityCounts: true });
}

async function listSessionSummariesWithOptions(
  baseDir: string,
  sessionType: FluxSessionType,
  options: { includeActivityCounts: boolean },
): Promise<FluxSessionSummary[]> {
  const sessionRoot = path.join(baseDir, ".ai-flux", "sessions", sessionType);
  const entries = await fs.readdir(sessionRoot, { withFileTypes: true }).catch(() => []);
  const sessions = await Promise.all(entries.filter((entry) => entry.isDirectory()).map(async (entry) => {
    const perSessionRoot = path.join(sessionRoot, entry.name);
    const sessionPath = path.join(perSessionRoot, "session.json");
    const summary = normalizeSessionSummary(await readJson(sessionPath), sessionType, entry.name);
    if (!options.includeActivityCounts) {
      return summary;
    }
    return { ...summary, ...(await readSessionActivityCounts(perSessionRoot)) };
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

async function pickGameDirForRun(runId: string, state: JsonRecord | null): Promise<{ gameDir: string | null; attemptId: string | null; attemptRoot: string | null }> {
  const root = runDir(runId);
  const active = (state?.active as JsonRecord | undefined)?.solver as JsonRecord | undefined;
  const activeAttemptId = typeof active?.attemptId === "string" ? String(active.attemptId) : null;
  const activeInstanceId = typeof active?.instanceId === "string" ? String(active.instanceId) : null;
  const preferredInstanceId = activeInstanceId || activeAttemptId;
  if (preferredInstanceId) {
    const candidateRoot = path.join(root, "flux_instances", preferredInstanceId);
    const candidate = path.join(candidateRoot, "agent");
    const entries = await fs.readdir(candidate, { withFileTypes: true }).catch(() => []);
    const game = entries.find((entry) => entry.isDirectory() && entry.name.startsWith("game_"));
    if (game) {
      return {
        gameDir: path.join(candidate, game.name),
        attemptId: preferredInstanceId,
        attemptRoot: candidateRoot,
      };
    }
  }
  const latestAttempt = await latestAttemptDir(root);
  if (latestAttempt) {
    const agentDir = path.join(latestAttempt, "agent");
    const entries = await fs.readdir(agentDir, { withFileTypes: true }).catch(() => []);
    const game = entries.find((entry) => entry.isDirectory() && entry.name.startsWith("game_"));
    if (game) {
      return {
        gameDir: path.join(agentDir, game.name),
        attemptId: path.basename(latestAttempt),
        attemptRoot: latestAttempt,
      };
    }
  }
  const durableAgentDir = path.join(root, "agent");
  const durableEntries = await fs.readdir(durableAgentDir, { withFileTypes: true }).catch(() => []);
  const durableGame = durableEntries.find((entry) => entry.isDirectory() && entry.name.startsWith("game_"));
  if (durableGame) {
    return { gameDir: path.join(durableAgentDir, durableGame.name), attemptId: null, attemptRoot: null };
  }
  return { gameDir: null, attemptId: null, attemptRoot: null };
}


function summarizeQueueItem(queue: { items?: unknown[] } | null): FluxQueuePreview {
  const items = Array.isArray(queue?.items) ? queue.items : [];
  const head = items[0] && typeof items[0] === "object" && !Array.isArray(items[0]) ? items[0] as JsonRecord : null;
  const payload = head?.payload && typeof head.payload === "object" && !Array.isArray(head.payload)
    ? head.payload as JsonRecord
    : null;
  return {
    length: items.length,
    reason: typeof head?.reason === "string" ? String(head.reason) : null,
    dedupeKey: typeof head?.dedupeKey === "string" ? String(head.dedupeKey) : null,
    interruptPolicy: typeof payload?.interruptPolicy === "string" ? String(payload.interruptPolicy) : null,
    baselineModelRevisionId: typeof payload?.baselineModelRevisionId === "string" ? String(payload.baselineModelRevisionId) : null,
    modelRevisionId: typeof payload?.modelRevisionId === "string" ? String(payload.modelRevisionId) : null,
    seedRevisionId: typeof payload?.seedRevisionId === "string" ? String(payload.seedRevisionId) : null,
    seedDeltaKind: typeof payload?.seedDeltaKind === "string" ? String(payload.seedDeltaKind) : null,
    evidenceBundleId: typeof payload?.evidenceBundleId === "string" ? String(payload.evidenceBundleId) : null,
  };
}

function toRunSummary(
  runId: string,
  state: JsonRecord | null,
  runtimeMeta: JsonRecord | null,
  gameState: JsonRecord | null,
  activeSessionRecords: Partial<Record<FluxSessionType, JsonRecord | null>> = {},
  latestSessionSummaries: Partial<Record<FluxSessionType, FluxSessionSummary[]>> = {},
): FluxRunSummary {
  const activeRaw = (state?.active as JsonRecord | undefined) ?? {};
  const status = typeof state?.status === "string" ? String(state.status) : "missing";
  const pid = typeof state?.pid === "number" ? Number(state.pid) : null;
  const gameStatus = typeof gameState?.state === "string" ? String(gameState.state) : null;
  const levelsCompleted = typeof gameState?.levels_completed === "number" ? Number(gameState.levels_completed) : null;
  const winLevels = typeof gameState?.win_levels === "number" ? Number(gameState.win_levels) : null;
  const solved = gameStatus === "WIN" || (levelsCompleted !== null && winLevels !== null && winLevels > 0 && levelsCompleted >= winLevels);
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
      const effectiveStatus = solved ? "idle" : (isLive ? resolvedStatus : "idle");
      return [sessionType, {
        status: effectiveStatus,
        sessionId: resolvedSessionId,
      }];
    }),
  ) as FluxRunSummary["active"];
  return {
    runId,
    gameId: typeof runtimeMeta?.game_id === "string" ? String(runtimeMeta.game_id) : null,
    updatedAt: typeof state?.updatedAt === "string" ? String(state.updatedAt) : null,
    startedAt: typeof state?.startedAt === "string" ? String(state.startedAt) : null,
    status: solved ? "WIN" : status,
    liveStatus: solved ? "stopped" : (status === "running" ? (isLive ? "running" : "stale") : (status === "missing" ? "missing" : "stopped")),
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
    const { attemptRoot } = await pickGameDirForRun(entry.name, fluxState);
    const gameState = await readAttemptArcState(attemptRoot);
    const activeSessionRecords = await readActiveSessionRecords(root, fluxState);
    return toRunSummary(entry.name, fluxState, runtimeMeta, gameState, activeSessionRecords, {});
  }));
  return runs.filter(Boolean).sort((left, right) => (right?.updatedAt || "").localeCompare(left?.updatedAt || "")) as FluxRunSummary[];
}

export async function readFluxRunDetail(runId: string): Promise<FluxRunDetail | null> {
  const root = runDir(runId);
  const state = await readJson<JsonRecord>(path.join(root, "flux", "state.json"));
  if (!state) return null;
  const runtimeMeta = await readJson<JsonRecord>(path.join(root, "flux_runtime.json"));
  const seedMeta = await readJson<JsonRecord>(path.join(root, "flux", "seed", "current_meta.json"));
  const currentModelMeta = await readJson<JsonRecord>(path.join(root, "flux", "model", "current", "meta.json"));
  const activeSessionRecords = await readActiveSessionRecords(root, state);
  const sessionHistory = Object.fromEntries(await Promise.all(SESSION_TYPES.map(async (sessionType) => {
    return [sessionType, await listSessionSummaries(root, sessionType)];
  }))) as FluxRunDetail["sessionHistory"];
  const { gameDir, attemptId, attemptRoot } = await pickGameDirForRun(runId, state);
  const currentState = await readAttemptArcState(attemptRoot)
    ?? await readJson<JsonRecord>(path.join(root, "supervisor", "arc", "state.json"));
  const summary = toRunSummary(runId, state, runtimeMeta, currentState, activeSessionRecords, sessionHistory);
  const queues = Object.fromEntries(await Promise.all(SESSION_TYPES.map(async (sessionType) => {
    const queue = await readJson<{ items?: unknown[] }>(path.join(root, "flux", "queues", `${sessionType}.json`));
    return [sessionType, summarizeQueueItem(queue)];
  }))) as FluxRunDetail["queues"];
  const timeline = gameDir ? await readFrameSnapshots(gameDir) : { frames: [], actions: [], currentLevel: null };
  return {
    ...summary,
    queues,
    selectedGameDir: gameDir,
    currentState,
    currentLevel: timeline.currentLevel,
    currentAttemptId: attemptId,
    currentModelRevisionId: typeof currentModelMeta?.revisionId === "string" ? String(currentModelMeta.revisionId) : null,
    lastBootstrapperModelRevisionId: typeof seedMeta?.lastBootstrapperModelRevisionId === "string" ? String(seedMeta.lastBootstrapperModelRevisionId) : null,
    lastQueuedBootstrapModelRevisionId: typeof seedMeta?.lastQueuedBootstrapModelRevisionId === "string" ? String(seedMeta.lastQueuedBootstrapModelRevisionId) : null,
    lastAttestedSeedRevisionId: typeof seedMeta?.lastAttestedSeedRevisionId === "string" ? String(seedMeta.lastAttestedSeedRevisionId) : null,
    lastAttestedSeedHash: typeof seedMeta?.lastAttestedSeedHash === "string" ? String(seedMeta.lastAttestedSeedHash) : null,
    lastInterruptPolicy: typeof seedMeta?.lastInterruptPolicy === "string" ? String(seedMeta.lastInterruptPolicy) : null,
    lastSeedDeltaKind: typeof seedMeta?.lastSeedDeltaKind === "string" ? String(seedMeta.lastSeedDeltaKind) : null,
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
  await cleanupLaunchTempArtifacts();
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
