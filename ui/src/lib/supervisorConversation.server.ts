import fs from "fs/promises";
import path from "path";
import {
  eventsInWindow,
  interventionBlock,
  loadInterventions,
  loadRawEvents,
  rawEventsToTimedBlocks,
} from "@/lib/agentConversationEvents.server";
import { loadStoredConversationBranches } from "@/lib/agentConversationStore.server";
import {
  parseConversationBlocks,
  sliceConversationBlocks,
  trimSeedOverlap,
} from "@/lib/conversation";
import { runDir } from "@/lib/paths";

interface SuperStateFile {
  conversationId?: unknown;
  activeForkId?: unknown;
}

interface ResolvedSupervisorConversation {
  conversationId: string;
  forkId: string;
  createdAt: string;
  documentText: string;
}

export interface SupervisorConversationDocument {
  blocks: import("@/lib/conversation").ConversationBlock[];
  source: string | null;
  totalLines: number;
  totalEvents: number;
  shownEvents: number;
  hiddenEvents: number;
}

function trimTrailingBlankLines(lines: string[]) {
  let end = lines.length;
  while (end > 0 && lines[end - 1] === "") end -= 1;
  return lines.slice(0, end);
}

function parseTime(value: string | null | undefined): number {
  const parsed = Date.parse(value ?? "");
  return Number.isFinite(parsed) ? parsed : 0;
}

function normalizeString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function emptyConversationDocument(): SupervisorConversationDocument {
  return {
    blocks: [],
    source: null,
    totalLines: 0,
    totalEvents: 0,
    shownEvents: 0,
    hiddenEvents: 0,
  };
}

async function readSuperState(runId: string): Promise<{
  conversationId: string | null;
  activeForkId: string | null;
}> {
  const statePath = path.join(runDir(runId), "super", "state.json");
  try {
    const payload = JSON.parse(await fs.readFile(statePath, "utf-8")) as SuperStateFile;
    return {
      conversationId: normalizeString(payload.conversationId),
      activeForkId: normalizeString(payload.activeForkId),
    };
  } catch {
    return {
      conversationId: null,
      activeForkId: null,
    };
  }
}

async function readRunHistoryConversationIds(runId: string): Promise<string[]> {
  const indexPath = path.join(
    runDir(runId),
    ".ai-supervisor",
    "supervisor",
    "run_history",
    "index.json"
  );
  try {
    const payload = JSON.parse(await fs.readFile(indexPath, "utf-8")) as {
      conversations?: Array<{
        conversationId?: unknown;
        lastForkAt?: unknown;
        firstForkAt?: unknown;
      }>;
    };
    return (payload.conversations ?? [])
      .map((entry) => ({
        conversationId: normalizeString(entry.conversationId),
        sortKey: Math.max(
          parseTime(normalizeString(entry.lastForkAt)),
          parseTime(normalizeString(entry.firstForkAt))
        ),
      }))
      .filter((entry): entry is { conversationId: string; sortKey: number } => Boolean(entry.conversationId))
      .sort((a, b) => b.sortKey - a.sortKey || a.conversationId.localeCompare(b.conversationId))
      .map((entry) => entry.conversationId);
  } catch {
    return [];
  }
}

async function listConversationIds(runId: string): Promise<string[]> {
  const conversationsDir = path.join(runDir(runId), ".ai-supervisor", "conversations");
  try {
    const entries = await fs.readdir(conversationsDir, { withFileTypes: true });
    return entries
      .filter((entry) => entry.isDirectory())
      .map((entry) => entry.name)
      .sort();
  } catch {
    return [];
  }
}

async function resolveConversationCandidates(runId: string): Promise<
  Array<{ conversationId: string; preferredForkId: string | null }>
> {
  const [superState, runHistoryIds, conversationIds] = await Promise.all([
    readSuperState(runId),
    readRunHistoryConversationIds(runId),
    listConversationIds(runId),
  ]);
  const ordered = new Map<string, string | null>();

  if (superState.conversationId) {
    ordered.set(superState.conversationId, superState.activeForkId);
  }
  for (const conversationId of runHistoryIds) {
    if (!ordered.has(conversationId)) {
      ordered.set(conversationId, null);
    }
  }
  for (const conversationId of conversationIds) {
    if (!ordered.has(conversationId)) {
      ordered.set(conversationId, null);
    }
  }

  return Array.from(ordered, ([conversationId, preferredForkId]) => ({
    conversationId,
    preferredForkId,
  }));
}

async function readConversationHead(
  runId: string,
  conversationId: string,
  preferredForkId: string | null
): Promise<ResolvedSupervisorConversation | null> {
  try {
    const storedBranches = await loadStoredConversationBranches(runId, conversationId);
    const activeBranch =
      (preferredForkId
        ? storedBranches.find((branch) => branch.forkId === preferredForkId)
        : null) ??
      storedBranches.find((branch) => branch.active) ??
      storedBranches.find((branch) => branch.head) ??
      storedBranches.at(-1) ??
      null;
    if (!activeBranch || !activeBranch.documentText.trim()) {
      return null;
    }
    return {
      conversationId,
      forkId: activeBranch.forkId,
      createdAt: activeBranch.createdAt,
      documentText: activeBranch.documentText,
    };
  } catch {
    return null;
  }
}

export async function resolveActiveSupervisorConversation(
  runId: string
): Promise<ResolvedSupervisorConversation | null> {
  const candidates = await resolveConversationCandidates(runId);
  for (const candidate of candidates) {
    const resolved = await readConversationHead(
      runId,
      candidate.conversationId,
      candidate.preferredForkId
    );
    if (resolved) {
      return resolved;
    }
  }
  return null;
}

export async function readSupervisorConversationDocument(
  runId: string,
  options: { hiddenEvents?: number; maxEvents?: number }
): Promise<SupervisorConversationDocument> {
  const activeConversation = await resolveActiveSupervisorConversation(runId);
  const [rawEvents, interventions] = await Promise.all([
    loadRawEvents(runId, activeConversation?.conversationId ?? null),
    loadInterventions(runId, activeConversation?.conversationId ?? null),
  ]);
  const documentText = activeConversation?.documentText ?? "";

  if (!documentText.trim()) {
    return emptyConversationDocument();
  }

  const lines = trimTrailingBlankLines(documentText.split("\n"));
  const seedBlocks = parseConversationBlocks(lines.join("\n"));
  const eventBlocks =
    activeConversation
      ? (() => {
          const { eventWindow, interventionWindow } = eventsInWindow(
            rawEvents,
            interventions,
            activeConversation.createdAt,
            null
          );
          return [
            ...rawEventsToTimedBlocks(eventWindow),
            ...interventionWindow.map((entry) => ({
              ts: entry.ts,
              blocks: [interventionBlock(entry)],
            })),
          ]
            .sort((a, b) => parseTime(a.ts) - parseTime(b.ts))
            .flatMap((entry) => entry.blocks);
        })()
      : [];
  const dedupedEventBlocks = trimSeedOverlap(seedBlocks, eventBlocks);
  const windowed = sliceConversationBlocks(dedupedEventBlocks, options);
  const seedEventCount = seedBlocks.filter((block) => block.kind !== "frontmatter").length;
  return {
    blocks: [...seedBlocks, ...windowed.blocks],
    source: activeConversation
      ? `${activeConversation.conversationId}:${activeConversation.forkId} active head`
      : null,
    totalLines:
      lines.length +
      dedupedEventBlocks.reduce((sum, block) => sum + block.content.split("\n").length, 0),
    totalEvents: seedEventCount + windowed.totalEvents,
    shownEvents: seedEventCount + windowed.shownEvents,
    hiddenEvents: windowed.hiddenEvents,
  };
}
