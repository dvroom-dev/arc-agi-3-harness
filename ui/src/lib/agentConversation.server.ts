import type { ConversationBlock } from "@/lib/conversation";
import { findConversationId } from "@/lib/agentConversationData.server";
import {
  loadConversationBranchDocument,
  loadStoredConversationBranchSummaries,
  sliceBranchDocumentSeed,
} from "@/lib/agentConversationStore.server";
import {
  eventsInWindow,
  interventionBlock,
  loadInterventions,
  loadRawEvents,
  rawEventsToTimedBlocks,
  type InterventionEntry,
} from "@/lib/agentConversationEvents.server";
import { compactConversationBlocks, trimSeedOverlap } from "@/lib/conversation";
import {
  loadConversationForkBranchFallback,
  activeSessionInfo,
} from "@/lib/agentConversationSession.server";
import {
  buildAgentConversationEpisodes,
  findAgentConversationEpisode,
} from "@/lib/agentConversationBranches";
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

function resolveEffectiveActiveForkId(
  storedBranches: Array<{
    forkId: string;
    parentId: string | null;
    mode: string | null;
    active: boolean;
    actionSummary: string | null;
  }>,
  activeSession: { forkId: string | null }
): string | null {
  const storeActiveForkId = storedBranches.find((branch) => branch.active)?.forkId ?? null;
  if (storeActiveForkId) {
    return storeActiveForkId;
  }
  if (!activeSession.forkId) return null;
  const branchByForkId = new Map(storedBranches.map((fork) => [fork.forkId, fork]));
  const sessionBranch = branchByForkId.get(activeSession.forkId);
  if (!sessionBranch || sessionBranch.actionSummary !== "fork (hard)") {
    return activeSession.forkId;
  }
  const childStart = storedBranches.find(
    (candidate) =>
      candidate.parentId === sessionBranch.forkId &&
      candidate.mode === sessionBranch.mode &&
      candidate.actionSummary === "supervise:start"
  );
  return childStart?.forkId ?? activeSession.forkId;
}

export async function listAgentConversationBranches(
  runId: string
): Promise<{ branches: AgentConversationBranch[] }> {
  const conversationId = await findConversationId(runId);
  if (!conversationId) {
    return loadConversationForkBranchFallback(runId);
  }
  const [storedBranches] = await Promise.all([
    loadStoredConversationBranchSummaries(runId, conversationId),
  ]);
  const activeSession = await activeSessionInfo(runId);
  if (storedBranches.length === 0) {
    return loadConversationForkBranchFallback(runId);
  }
  const effectiveActiveForkId = resolveEffectiveActiveForkId(storedBranches, activeSession);

  const baseBranches = storedBranches.map((fork) => {
    return {
      key: fork.key,
      mode: fork.mode ?? null,
      label: fork.mode ?? "agent",
      conversationId: fork.conversationId,
      forkId: fork.forkId,
      parentId: fork.parentId,
      createdAt: fork.createdAt,
      active: fork.forkId === effectiveActiveForkId || (!effectiveActiveForkId && fork.active),
      head: fork.head,
      actionSummary: fork.actionSummary,
      assistantTurns: fork.assistantTurns,
      toolCallCount: fork.toolCallCount,
      toolResultCount: fork.toolResultCount,
      initialUserPreview: fork.initialUserPreview,
      lastAssistantPreview: fork.lastAssistantPreview,
    };
  });

  const episodes = buildAgentConversationEpisodes(baseBranches);

  if (episodes.length === 0) {
    return loadConversationForkBranchFallback(runId);
  }

  return { branches: episodes };
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
      loadStoredConversationBranchSummaries(runId, conversationId),
      loadRawEvents(runId, conversationId),
      loadInterventions(runId, conversationId),
    ]);
    const baseBranches = storedBranches.map((fork) => {
      return {
        key: fork.key,
        mode: fork.mode ?? null,
        active: fork.active,
        head: fork.head,
        conversationId: fork.conversationId,
        forkId: fork.forkId,
        parentId: fork.parentId,
        createdAt: fork.createdAt,
        actionSummary: fork.actionSummary,
        assistantTurns: fork.assistantTurns,
        toolCallCount: fork.toolCallCount,
        toolResultCount: fork.toolResultCount,
        initialUserPreview: fork.initialUserPreview,
        lastAssistantPreview: fork.lastAssistantPreview,
      };
    });
    const episode = findAgentConversationEpisode(buildAgentConversationEpisodes(baseBranches), branchKey);
    if (!episode) throw new Error("branch not found");
    const groupedBranches = storedBranches
      .filter((entry) => episode.memberForkIds.includes(entry.forkId))
      .sort((a, b) => (parseTime(a.createdAt) ?? 0) - (parseTime(b.createdAt) ?? 0));
    const branch = groupedBranches.at(-1);
    if (!branch) throw new Error("branch not found");
    const branchDocument = await loadConversationBranchDocument(runId, conversationId, branch.forkId);
    const seedBlocks = compactConversationBlocks(sliceBranchDocumentSeed(branchDocument));
    const eventBlocks: ConversationBlock[] = [];
    for (const groupBranch of groupedBranches) {
      const { eventWindow, interventionWindow } = eventsInWindow(
        rawEvents,
        interventions,
        groupBranch.createdAt,
        groupBranch.nextCreatedAt
      );
      eventBlocks.push(
        ...[
          ...rawEventsToTimedBlocks(eventWindow),
          ...interventionWindow.map((entry) => ({
            ts: entry.ts,
            blocks: [interventionBlock(entry)],
          })),
        ]
          .sort((a, b) => (parseTime(a.ts) ?? 0) - (parseTime(b.ts) ?? 0))
          .flatMap((entry) => entry.blocks)
      );
    }
    const dedupedEventBlocks = trimSeedOverlap(seedBlocks, eventBlocks);
    const windowed = sliceBlocks(dedupedEventBlocks, options);
    const seedEventCount = seedBlocks.filter((block) => block.kind !== "frontmatter").length;
    return {
      blocks: [...seedBlocks, ...windowed.blocks],
      source: `${branch.mode || "agent"} conversation`,
      totalLines:
        branchDocument.split("\n").length +
        dedupedEventBlocks.reduce((sum, block) => sum + block.content.split("\n").length, 0),
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
    loadStoredConversationBranchSummaries(runId, conversationId),
    loadRawEvents(runId, conversationId),
    loadInterventions(runId, conversationId),
  ]);
  const active = storedBranches.find((branch) => branch.active) ?? storedBranches.at(-1) ?? null;
  const activeDocument = active
    ? await loadConversationBranchDocument(runId, conversationId, active.forkId)
    : null;
  const seedBlocks = activeDocument ? compactConversationBlocks(sliceBranchDocumentSeed(activeDocument)) : [];
  const { eventWindow, interventionWindow } = active
    ? eventsInWindow(rawEvents, interventions, active.createdAt, active.nextCreatedAt)
    : { eventWindow: rawEvents, interventionWindow: interventions };

  const combined: Array<
    | { ts: string; type: "event"; payload: ConversationBlock[] }
    | { ts: string; type: "intervention"; payload: InterventionEntry }
  > = [
    ...rawEventsToTimedBlocks(eventWindow).map((entry) => ({
      ts: entry.ts,
      type: "event" as const,
      payload: entry.blocks,
    })),
    ...interventionWindow.map((payload) => ({ ts: payload.ts, type: "intervention" as const, payload })),
  ].sort((a, b) => (parseTime(a.ts) ?? 0) - (parseTime(b.ts) ?? 0));

  const eventBlocks = combined.flatMap((entry) =>
    entry.type === "event" ? entry.payload : [interventionBlock(entry.payload)]
  );
  const dedupedEventBlocks = trimSeedOverlap(seedBlocks, eventBlocks);
  const windowed = sliceBlocks(dedupedEventBlocks, options);
  const seedEventCount = seedBlocks.filter((block) => block.kind !== "frontmatter").length;

  return {
    blocks: [...seedBlocks, ...windowed.blocks],
    source: active?.mode ? `${active.mode} raw events` : "agent raw events",
    totalLines:
      (activeDocument?.split("\n").length ?? 0) +
      dedupedEventBlocks.reduce((sum, block) => sum + block.content.split("\n").length, 0),
    totalEvents: seedEventCount + windowed.totalEvents,
    shownEvents: seedEventCount + windowed.shownEvents,
    hiddenEvents: windowed.hiddenEvents,
  };
}
