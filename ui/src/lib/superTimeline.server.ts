import fs from "fs/promises";
import path from "path";
import { ctxDir, runDir } from "@/lib/paths";
import {
  aggregateCycleWindow,
  loadRawEvents,
  loadReviewChecks,
} from "@/lib/superTimelineRuntime.server";
import type {
  SuperCycleEntry,
  SuperConversationSummary,
  SuperInterventionEntry,
  SuperModeDuration,
  SuperTimelinePayload,
  SuperToolCount,
} from "@/lib/types";

interface ConversationFork {
  id: string;
  parentId: string | null;
  createdAt: string | null;
  actionSummary: string | null;
  forkSummary: string | null;
  reason: string | null;
  providerName: string | null;
  model: string | null;
  supervisorModel: string | null;
  mode: string | null;
}

interface RunHistoryForkSummaryFile {
  key?: string;
  conversationId?: string;
  forkId?: string;
  parentId?: string;
  createdAt?: string;
  mode?: string;
  actionSummary?: string;
  initialUserPreview?: string;
  lastAssistantPreview?: string;
  userTurns?: number;
  assistantTurns?: number;
  toolCallCount?: number;
  toolResultCount?: number;
  toolCounts?: Array<{ name?: string; count?: number }>;
  skeletonPath?: string;
}

function parseTime(value: string | null | undefined): number | null {
  if (!value) return null;
  const ts = Date.parse(value);
  return Number.isFinite(ts) ? ts : null;
}

function parseModeFromText(text: string): string | null {
  const match = text.match(/^mode:\s*(.+)$/m);
  return match?.[1]?.trim() || null;
}

function parseModeFromForkPayload(payload: Record<string, unknown>): string | null {
  if (typeof payload.documentText === "string") {
    return parseModeFromText(payload.documentText);
  }

  const patch = payload.patch;
  if (!patch || typeof patch !== "object" || !Array.isArray((patch as { ops?: unknown[] }).ops)) {
    return null;
  }

  for (const op of (patch as { ops: unknown[] }).ops) {
    if (!op || typeof op !== "object") continue;
    const lines = (op as { lines?: unknown }).lines;
    if (!Array.isArray(lines)) continue;
    const mode = parseModeFromText(lines.join("\n"));
    if (mode) return mode;
  }

  return null;
}

async function preferredConversationId(runId: string): Promise<string | null> {
  const sessionFile = path.join(ctxDir(runId), "session.md");
  try {
    const text = await fs.readFile(sessionFile, "utf-8");
    return text.match(/^conversation_id:\s*(.+)$/m)?.[1]?.trim() || null;
  } catch {
    return null;
  }
}

async function loadConversationForks(runId: string): Promise<{
  conversationId: string | null;
  forks: ConversationFork[];
}> {
  const conversationsDir = path.join(runDir(runId), ".ai-supervisor", "conversations");
  const preferredId = await preferredConversationId(runId);
  let conversationIds: string[] = [];
  try {
    conversationIds = (await fs.readdir(conversationsDir, { withFileTypes: true }))
      .filter((entry) => entry.isDirectory())
      .map((entry) => entry.name)
      .sort();
  } catch {
    return { conversationId: null, forks: [] };
  }

  const orderedIds = preferredId
    ? [preferredId, ...conversationIds.filter((id) => id !== preferredId)]
    : conversationIds;

  for (const conversationId of orderedIds) {
    const indexPath = path.join(conversationsDir, conversationId, "index.json");
    const forksDir = path.join(conversationsDir, conversationId, "forks");
    try {
      const indexPayload = JSON.parse(await fs.readFile(indexPath, "utf-8")) as {
        forks?: unknown[];
      };
      if (!Array.isArray(indexPayload.forks)) continue;

      const forks: ConversationFork[] = [];
      for (const rawFork of indexPayload.forks) {
        if (!rawFork || typeof rawFork !== "object") continue;
        const fork = rawFork as Record<string, unknown>;
        const id = typeof fork.id === "string" ? fork.id : "";
        if (!id) continue;

        let mode = parseModeFromForkPayload(fork);
        if (!mode) {
          try {
            const forkPayload = JSON.parse(
              await fs.readFile(path.join(forksDir, `${id}.json`), "utf-8")
            ) as Record<string, unknown>;
            mode = parseModeFromForkPayload(forkPayload);
          } catch {
            mode = null;
          }
        }

        forks.push({
          id,
          parentId: typeof fork.parentId === "string" ? fork.parentId : null,
          createdAt: typeof fork.createdAt === "string" ? fork.createdAt : null,
          actionSummary: typeof fork.actionSummary === "string" ? fork.actionSummary : null,
          forkSummary: typeof fork.forkSummary === "string" ? fork.forkSummary : null,
          reason:
            Array.isArray(fork.actions) &&
            fork.actions[0] &&
            typeof fork.actions[0] === "object" &&
            typeof (fork.actions[0] as { reasoning?: unknown }).reasoning === "string"
              ? ((fork.actions[0] as { reasoning: string }).reasoning || null)
              : null,
          providerName: typeof fork.providerName === "string" ? fork.providerName : null,
          model: typeof fork.model === "string" ? fork.model : null,
          supervisorModel: typeof fork.supervisorModel === "string" ? fork.supervisorModel : null,
          mode,
        });
      }

      forks.sort((a, b) => (parseTime(a.createdAt) ?? 0) - (parseTime(b.createdAt) ?? 0));

      return { conversationId, forks };
    } catch {
      // Try next conversation.
    }
  }

  return { conversationId: null, forks: [] };
}

async function loadRunHistorySummaries(runId: string): Promise<SuperConversationSummary[]> {
  const indexPath = path.join(runDir(runId), ".ai-supervisor", "supervisor", "run_history", "index.json");
  try {
    const payload = JSON.parse(await fs.readFile(indexPath, "utf-8")) as {
      forks?: RunHistoryForkSummaryFile[];
    };
    if (!Array.isArray(payload.forks)) return [];
    return payload.forks
      .map((fork): SuperConversationSummary | null => {
        if (!fork || typeof fork !== "object") return null;
        const key = typeof fork.key === "string" ? fork.key : "";
        const conversationId = typeof fork.conversationId === "string" ? fork.conversationId : "";
        const forkId = typeof fork.forkId === "string" ? fork.forkId : "";
        const createdAt = typeof fork.createdAt === "string" ? fork.createdAt : "";
        if (!key || !conversationId || !forkId || !createdAt) return null;
        return {
          key,
          conversationId,
          forkId,
          parentId: typeof fork.parentId === "string" ? fork.parentId : null,
          createdAt,
          mode: typeof fork.mode === "string" ? fork.mode : null,
          actionSummary: typeof fork.actionSummary === "string" ? fork.actionSummary : null,
          initialUserPreview:
            typeof fork.initialUserPreview === "string" ? fork.initialUserPreview : null,
          lastAssistantPreview:
            typeof fork.lastAssistantPreview === "string" ? fork.lastAssistantPreview : null,
          userTurns: Number.isFinite(fork.userTurns) ? Number(fork.userTurns) : 0,
          assistantTurns: Number.isFinite(fork.assistantTurns) ? Number(fork.assistantTurns) : 0,
          toolCallCount: Number.isFinite(fork.toolCallCount) ? Number(fork.toolCallCount) : 0,
          toolResultCount: Number.isFinite(fork.toolResultCount) ? Number(fork.toolResultCount) : 0,
          toolCounts: Array.isArray(fork.toolCounts)
            ? fork.toolCounts
                .map((entry) => ({
                  name: typeof entry?.name === "string" ? entry.name : "",
                  count: Number.isFinite(entry?.count) ? Number(entry?.count) : 0,
                }))
                .filter((entry) => entry.name)
            : [],
          skeletonPath: typeof fork.skeletonPath === "string" ? fork.skeletonPath : "",
        };
      })
      .filter((entry): entry is SuperConversationSummary => Boolean(entry))
      .sort((a, b) => (parseTime(a.createdAt) ?? 0) - (parseTime(b.createdAt) ?? 0));
  } catch {
    return [];
  }
}

function toToolCounts(map: Map<string, number>): SuperToolCount[] {
  return Array.from(map.entries())
    .map(([name, count]) => ({ name, count }))
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
}

export async function buildSuperTimeline(runId: string): Promise<SuperTimelinePayload> {
  const { conversationId, forks } = await loadConversationForks(runId);
  const { events: rawEvents, sessionMetadata } = await loadRawEvents(runId, conversationId, parseTime);
  const reviewChecksByReason = await loadReviewChecks(runId, conversationId);
  const conversationSummaries = await loadRunHistorySummaries(runId);
  const startForks = forks.filter((fork) => fork.actionSummary === "supervise:start");
  const entries: (SuperCycleEntry | SuperInterventionEntry)[] = [];
  const modeTotals = new Map<string, number>();

  for (let index = 0; index < forks.length; index += 1) {
    const fork = forks[index];
    const nextFork = forks[index + 1] ?? null;

    if (fork.actionSummary === "supervise:start") {
      const cycle = aggregateCycleWindow(
        fork.createdAt,
        nextFork?.createdAt ?? null,
        fork.providerName,
        fork.model,
        rawEvents,
        sessionMetadata,
        parseTime
      );

      if (fork.mode && cycle.durationMs != null) {
        modeTotals.set(fork.mode, (modeTotals.get(fork.mode) ?? 0) + cycle.durationMs);
      }

      entries.push({
        id: fork.id,
        kind: "cycle",
        startedAt: cycle.startedAt,
        endedAt: cycle.endedAt,
        durationMs: cycle.durationMs,
        mode: fork.mode,
        provider: cycle.provider,
        model: cycle.model,
        sessionId: cycle.sessionId,
        enabledTools: cycle.enabledTools,
        totalEvents: cycle.totalEvents,
        toolCallCount: cycle.toolCallCount,
        toolResultCount: cycle.toolResultCount,
        toolErrorCount: cycle.toolErrorCount,
        assistantTextCount: cycle.assistantTextCount,
        userTextCount: cycle.userTextCount,
        firstToolLatencyMs: cycle.firstToolLatencyMs,
        lastEventAt: cycle.lastEventAt,
        toolCounts: toToolCounts(cycle.toolCounts),
      });
      continue;
    }

    const prevStart = [...startForks].reverse().find((candidate) => {
      const candidateTs = parseTime(candidate.createdAt);
      const currentTs = parseTime(fork.createdAt);
      return candidateTs != null && currentTs != null && candidateTs <= currentTs;
    });
    const nextStart = startForks.find((candidate) => {
      const candidateTs = parseTime(candidate.createdAt);
      const currentTs = parseTime(fork.createdAt);
      return candidateTs != null && currentTs != null && candidateTs > currentTs;
    });

    const prevStartTs = parseTime(prevStart?.createdAt);
    const nextStartTs = parseTime(nextStart?.createdAt);
    const currentTs = parseTime(fork.createdAt);
    const reviewChecks = fork.reason ? reviewChecksByReason.get(fork.reason) : undefined;

    entries.push({
      id: fork.id,
      kind: "intervention",
      at: fork.createdAt ?? "",
      actionSummary: fork.actionSummary,
      forkSummary: fork.forkSummary,
      reason: fork.reason,
      ruleChecks: reviewChecks?.ruleChecks ?? null,
      violationChecks: reviewChecks?.violationChecks ?? null,
      provider: fork.providerName,
      model: fork.model,
      supervisorModel: fork.supervisorModel,
      prevMode: prevStart?.mode ?? null,
      nextMode: nextStart?.mode ?? null,
      elapsedSincePrevCycleMs:
        prevStartTs != null && currentTs != null ? Math.max(0, currentTs - prevStartTs) : null,
      gapToNextCycleMs:
        nextStartTs != null && currentTs != null ? Math.max(0, nextStartTs - currentTs) : null,
    });
  }

  const cycleEntries = entries.filter((entry): entry is SuperCycleEntry => entry.kind === "cycle");
  const interventionEntries = entries.filter(
    (entry): entry is SuperInterventionEntry => entry.kind === "intervention"
  );
  const totalDurationMs = cycleEntries.reduce(
    (sum, entry) => sum + (entry.durationMs ?? 0),
    0
  );
  const totalToolCalls = cycleEntries.reduce((sum, entry) => sum + entry.toolCallCount, 0);
  const totalToolErrors = cycleEntries.reduce((sum, entry) => sum + entry.toolErrorCount, 0);
  const modeDurations: SuperModeDuration[] = Array.from(modeTotals.entries())
    .map(([mode, durationMs]) => ({ mode, durationMs }))
    .sort((a, b) => b.durationMs - a.durationMs || a.mode.localeCompare(b.mode));

  return {
    runId,
    conversationId,
    active: conversationId != null && cycleEntries.length > 0 && !cycleEntries.at(-1)?.endedAt,
    totalCycles: cycleEntries.length,
    totalInterventions: interventionEntries.length,
    totalDurationMs,
    totalToolCalls,
    totalToolErrors,
    modeDurations,
    conversationSummaries,
    entries,
  };
}
