import type { ConversationBlock } from "@/lib/conversation";
import { findConversationId } from "@/lib/agentConversationData.server";
import {
  loadStoredConversationBranches,
  sliceBranchDocumentSeed,
} from "@/lib/agentConversationStore.server";
import {
  countBranchActivity,
  eventsInWindow,
  interventionBlock,
  loadInterventions,
  loadRawEvents,
  rawEventToBlocks,
} from "@/lib/agentConversationEvents.server";
import {
  loadConversationForkBranchFallback,
  activeSessionInfo,
} from "@/lib/agentConversationSession.server";
import { filterVisibleAgentBranches } from "@/lib/agentConversationBranches";
import type { AgentConversationBranch } from "@/lib/types";

interface AgentConversationDocument {
  blocks: ConversationBlock[];
  source: string | null;
  totalLines: number;
  totalEvents: number;
  shownEvents: number;
  hiddenEvents: number;
}

function parseTime(value: string | null | undefined): number | null {
  if (!value) return null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function sliceBlocks(
  blocks: ConversationBlock[],
  options: { hiddenEvents?: number; maxEvents?: number }
) {
  const totalEvents = blocks.length;
  const hiddenEvents = Math.max(
    0,
    Math.min(totalEvents, options.hiddenEvents ?? Math.max(0, totalEvents - (options.maxEvents ?? totalEvents)))
  );
  const shownBlocks = blocks.slice(hiddenEvents);
  return {
    blocks: shownBlocks,
    totalEvents,
    shownEvents: shownBlocks.length,
    hiddenEvents,
  };
}

export async function listAgentConversationBranches(
  runId: string
): Promise<{ branches: AgentConversationBranch[] }> {
  const conversationId = await findConversationId(runId);
  if (!conversationId) {
    return loadConversationForkBranchFallback(runId);
  }
  const [storedBranches, rawEvents, interventions] = await Promise.all([
    loadStoredConversationBranches(runId, conversationId),
    loadRawEvents(runId, conversationId),
    loadInterventions(runId, conversationId),
  ]);
  const activeSession = await activeSessionInfo(runId);
  if (storedBranches.length === 0) {
    return loadConversationForkBranchFallback(runId);
  }
  const branchByForkId = new Map(storedBranches.map((fork) => [fork.forkId, fork]));
  const effectiveActiveForkId = (() => {
    if (!activeSession.forkId) return null;
    const sessionBranch = branchByForkId.get(activeSession.forkId);
    if (!sessionBranch || sessionBranch.actionSummary !== "fork (hard)") return activeSession.forkId;
    const childStart = storedBranches.find(
      (candidate) =>
        candidate.parentId === sessionBranch.forkId &&
        candidate.mode === sessionBranch.mode &&
        candidate.actionSummary === "supervise:start"
    );
    return childStart?.forkId ?? activeSession.forkId;
  })();

  const baseBranches = storedBranches.map((fork) => {
    const { eventWindow } = eventsInWindow(rawEvents, interventions, fork.createdAt, fork.nextCreatedAt);
    const activity = countBranchActivity(eventWindow);
    return {
      key: fork.key,
      mode: fork.mode ?? null,
      label: fork.mode ?? "agent",
      conversationId: fork.conversationId,
      forkId: fork.forkId,
      parentId: fork.parentId,
      createdAt: fork.createdAt,
      active: fork.forkId === effectiveActiveForkId || (!effectiveActiveForkId && fork.active),
      actionSummary: fork.actionSummary,
      assistantTurns: activity.assistantTurns,
      toolCallCount: activity.toolCallCount,
      toolResultCount: activity.toolResultCount,
      initialUserPreview: fork.initialUserPreview,
      lastAssistantPreview: activity.lastAssistantPreview,
    };
  });

  const mergedBranches = [...baseBranches];

  const visibleBranches = filterVisibleAgentBranches(mergedBranches);

  if (visibleBranches.length === 0) {
    return loadConversationForkBranchFallback(runId);
  }

  visibleBranches.sort((a, b) => (parseTime(a.createdAt) ?? 0) - (parseTime(b.createdAt) ?? 0));
  const modeCounts = new Map<string, number>();
  for (const branch of visibleBranches) {
    const mode = branch.mode?.trim() || "agent";
    modeCounts.set(mode, (modeCounts.get(mode) ?? 0) + 1);
  }
  const seenPerMode = new Map<string, number>();
  const branches = visibleBranches.map((branch) => {
    const mode = branch.mode?.trim() || "agent";
    const nextIndex = (seenPerMode.get(mode) ?? 0) + 1;
    seenPerMode.set(mode, nextIndex);
    const totalForMode = modeCounts.get(mode) ?? 1;
    return {
      ...branch,
      label: totalForMode > 1 ? `${mode} (${nextIndex})` : mode,
      active: branch.active,
    } satisfies AgentConversationBranch;
  });

  return { branches };
}

async function readAgentBranchSkeletonDocument(
  runId: string,
  branchKey: string,
  options: { hiddenEvents?: number; maxEvents?: number }
): Promise<AgentConversationDocument> {
  const conversationId = await findConversationId(runId);
  if (!conversationId) {
    return {
      blocks: [],
      source: null,
      totalLines: 0,
      totalEvents: 0,
      shownEvents: 0,
      hiddenEvents: 0,
    };
  }
  try {
    const [storedBranches, rawEvents, interventions] = await Promise.all([
      loadStoredConversationBranches(runId, conversationId),
      loadRawEvents(runId, conversationId),
      loadInterventions(runId, conversationId),
    ]);
    const branch = storedBranches.find((entry) => entry.key === branchKey);
    if (!branch) throw new Error("branch not found");
    const seedBlocks = sliceBranchDocumentSeed(branch.documentText);
    const { eventWindow, interventionWindow } = eventsInWindow(
      rawEvents,
      interventions,
      branch.createdAt,
      branch.nextCreatedAt
    );
    const eventBlocks = [
      ...eventWindow.flatMap((event) => rawEventToBlocks(event)),
      ...interventionWindow.map((entry) => interventionBlock(entry)),
    ];
    const windowed = sliceBlocks(eventBlocks, options);
    const seedEventCount = seedBlocks.filter((block) => block.kind !== "frontmatter").length;
    return {
      blocks: [...seedBlocks, ...windowed.blocks],
      source: `${branch.mode || "agent"} branch`,
      totalLines:
        branch.documentText.split("\n").length +
        eventBlocks.reduce((sum, block) => sum + block.content.split("\n").length, 0),
      totalEvents: seedEventCount + windowed.totalEvents,
      shownEvents: seedEventCount + windowed.shownEvents,
      hiddenEvents: windowed.hiddenEvents,
    };
  } catch {
    return {
      blocks: [],
      source: null,
      totalLines: 0,
      totalEvents: 0,
      shownEvents: 0,
      hiddenEvents: 0,
    };
  }
}

export async function readAgentConversationDocument(
  runId: string,
  options: { hiddenEvents?: number; maxEvents?: number; branchKey?: string }
): Promise<AgentConversationDocument> {
  if (options.branchKey) {
    return readAgentBranchSkeletonDocument(runId, options.branchKey, options);
  }
  const conversationId = await findConversationId(runId);
  if (!conversationId) {
    return {
      blocks: [],
      source: null,
      totalLines: 0,
      totalEvents: 0,
      shownEvents: 0,
      hiddenEvents: 0,
    };
  }
  const [storedBranches, rawEvents, interventions] = await Promise.all([
    loadStoredConversationBranches(runId, conversationId),
    loadRawEvents(runId, conversationId),
    loadInterventions(runId, conversationId),
  ]);
  const active = storedBranches.find((branch) => branch.active) ?? storedBranches.at(-1) ?? null;
  const seedBlocks = active ? sliceBranchDocumentSeed(active.documentText) : [];
  const { eventWindow, interventionWindow } = active
    ? eventsInWindow(rawEvents, interventions, active.createdAt, active.nextCreatedAt)
    : { eventWindow: rawEvents, interventionWindow: interventions };

  const combined: Array<
    | { ts: string; type: "event"; payload: RawEventEntry }
    | { ts: string; type: "intervention"; payload: InterventionEntry }
  > = [
    ...eventWindow.map((payload) => ({ ts: payload.ts, type: "event" as const, payload })),
    ...interventionWindow.map((payload) => ({ ts: payload.ts, type: "intervention" as const, payload })),
  ].sort((a, b) => (parseTime(a.ts) ?? 0) - (parseTime(b.ts) ?? 0));

  const eventBlocks = combined.flatMap((entry) =>
    entry.type === "event" ? rawEventToBlocks(entry.payload) : [interventionBlock(entry.payload)]
  );
  const windowed = sliceBlocks(eventBlocks, options);
  const seedEventCount = seedBlocks.filter((block) => block.kind !== "frontmatter").length;

  return {
    blocks: [...seedBlocks, ...windowed.blocks],
    source: active?.mode ? `${active.mode} raw events` : "agent raw events",
    totalLines:
      (active?.documentText.split("\n").length ?? 0) +
      eventBlocks.reduce((sum, block) => sum + block.content.split("\n").length, 0),
    totalEvents: seedEventCount + windowed.totalEvents,
    shownEvents: seedEventCount + windowed.shownEvents,
    hiddenEvents: windowed.hiddenEvents,
  };
}
