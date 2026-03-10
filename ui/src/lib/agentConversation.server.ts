import fs from "fs/promises";
import path from "path";
import type { ConversationBlock } from "@/lib/conversation";
import { parseConversationBlocks, sliceConversationBlocks } from "@/lib/conversation";
import {
  findConversationId,
  loadRunHistoryForks,
  type RunHistoryForkSummaryFile,
} from "@/lib/agentConversationData.server";
import {
  activeSessionInfo,
  loadAgentBaseBlock,
  loadConversationForkBranchFallback,
} from "@/lib/agentConversationSession.server";
import { runDir } from "@/lib/paths";
import type { AgentConversationBranch } from "@/lib/types";

interface AgentConversationDocument {
  blocks: ConversationBlock[];
  source: string | null;
  totalLines: number;
  totalEvents: number;
  shownEvents: number;
  hiddenEvents: number;
}

interface RawEventEntry {
  ts: string;
  provider: string | null;
  itemKind: string | null;
  itemSummary: string | null;
  raw: Record<string, unknown>;
}

interface InterventionEntry {
  ts: string;
  actionSummary: string | null;
  forkSummary: string | null;
  reason: string | null;
}

function parseTime(value: string | null | undefined): number | null {
  if (!value) return null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}

async function loadRawEvents(runId: string, conversationId: string | null): Promise<RawEventEntry[]> {
  if (!conversationId) return [];
  const rawEventsPath = path.join(
    runDir(runId),
    ".ai-supervisor",
    "conversations",
    conversationId,
    "raw_events",
    "events.ndjson"
  );
  let lines: string[] = [];
  try {
    lines = (await fs.readFile(rawEventsPath, "utf-8")).split("\n").filter(Boolean);
  } catch {
    return [];
  }

  const events: RawEventEntry[] = [];
  for (const line of lines) {
    try {
      const payload = JSON.parse(line) as {
        ts?: string;
        provider?: string;
        item_kind?: string;
        item_summary?: string;
        raw?: Record<string, unknown>;
      };
      if (typeof payload.ts !== "string" || !payload.raw || typeof payload.raw !== "object") {
        continue;
      }
      events.push({
        ts: payload.ts,
        provider: typeof payload.provider === "string" ? payload.provider : null,
        itemKind: typeof payload.item_kind === "string" ? payload.item_kind : null,
        itemSummary: typeof payload.item_summary === "string" ? payload.item_summary : null,
        raw: payload.raw,
      });
    } catch {
      // Ignore malformed lines.
    }
  }

  events.sort((a, b) => (parseTime(a.ts) ?? 0) - (parseTime(b.ts) ?? 0));
  return events;
}

async function loadInterventions(
  runId: string,
  conversationId: string | null
): Promise<InterventionEntry[]> {
  if (!conversationId) return [];
  const indexPath = path.join(
    runDir(runId),
    ".ai-supervisor",
    "conversations",
    conversationId,
    "index.json"
  );
  try {
    const payload = JSON.parse(await fs.readFile(indexPath, "utf-8")) as {
      forks?: Array<Record<string, unknown>>;
    };
    if (!Array.isArray(payload.forks)) return [];
    return payload.forks
      .map((fork) => {
        const actionSummary = typeof fork.actionSummary === "string" ? fork.actionSummary : null;
        if (actionSummary !== "fork (hard)" && actionSummary !== "fork (soft)") return null;
        const ts = typeof fork.createdAt === "string" ? fork.createdAt : null;
        if (!ts) return null;
        const reason =
          Array.isArray(fork.actions) &&
          fork.actions[0] &&
          typeof fork.actions[0] === "object" &&
          typeof (fork.actions[0] as { reasoning?: unknown }).reasoning === "string"
            ? (fork.actions[0] as { reasoning: string }).reasoning
            : null;
        return {
          ts,
          actionSummary,
          forkSummary: typeof fork.forkSummary === "string" ? fork.forkSummary : null,
          reason,
        } satisfies InterventionEntry;
      })
      .filter((entry): entry is InterventionEntry => Boolean(entry))
      .sort((a, b) => (parseTime(a.ts) ?? 0) - (parseTime(b.ts) ?? 0));
  } catch {
    return [];
  }
}

function contentText(content: unknown): string {
  if (typeof content === "string") return content.trim();
  if (!Array.isArray(content)) return "";
  return content
    .map((entry) => {
      if (!entry || typeof entry !== "object") return "";
      if ((entry as { type?: unknown }).type === "text") {
        const text = (entry as { text?: unknown }).text;
        return typeof text === "string" ? text : "";
      }
      return "";
    })
    .filter(Boolean)
    .join("\n")
    .trim();
}

function toolBlockContent(summary: string, status: string, body: string) {
  return [`summary: ${summary}`, `status: ${status}`, "", body.trim()].join("\n").trim();
}

function rawEventToBlocks(event: RawEventEntry): ConversationBlock[] {
  const blocks: ConversationBlock[] = [];
  if (event.raw.type === "system" && event.raw.subtype === "init") {
    const tools = Array.isArray(event.raw.tools)
      ? event.raw.tools.filter((tool): tool is string => typeof tool === "string")
      : [];
    const lines = [
      `provider: ${event.provider || "unknown"}`,
      `model: ${typeof event.raw.model === "string" ? event.raw.model : "unknown"}`,
      `session_id: ${typeof event.raw.session_id === "string" ? event.raw.session_id : "unknown"}`,
      `enabled_tools: ${tools.join(", ") || "(none)"}`,
    ];
    blocks.push({
      kind: "text",
      content: lines.join("\n"),
      raw: lines.join("\n"),
    });
    return blocks;
  }

  const message =
    event.raw.message && typeof event.raw.message === "object"
      ? (event.raw.message as { content?: unknown })
      : null;
  const content = message?.content;

  if (event.itemKind === "tool_call") {
    let summary = event.itemSummary || "tool_call";
    let body = "";
    if (Array.isArray(content)) {
      const toolUse = content.find(
        (entry) =>
          entry &&
          typeof entry === "object" &&
          (entry as { type?: unknown }).type === "tool_use"
      ) as
        | { name?: unknown; input?: unknown }
        | undefined;
      if (toolUse) {
        const name = typeof toolUse.name === "string" ? toolUse.name : summary;
        summary = name;
        body =
          typeof toolUse.input === "string"
            ? toolUse.input
            : JSON.stringify(toolUse.input ?? {}, null, 2);
      }
    }
    blocks.push({
      kind: "tool_call",
      content: toolBlockContent(summary, "ok", body || summary),
      raw: summary,
    });
    return blocks;
  }

  if (event.itemKind === "tool_result" || event.itemKind === "tool_error") {
    const summary = event.itemSummary || event.itemKind || "tool_result";
    let body = contentText(content);
    let toolUseId: string | null = null;
    if (Array.isArray(content)) {
      const toolResult = content.find(
        (entry) =>
          entry &&
          typeof entry === "object" &&
          (entry as { type?: unknown }).type === "tool_result"
      ) as { tool_use_id?: unknown } | undefined;
      if (toolResult && typeof toolResult.tool_use_id === "string") {
        toolUseId = toolResult.tool_use_id;
      }
    }
    if (!body && typeof event.raw.tool_use_result === "string") {
      body = event.raw.tool_use_result;
    } else if (!body && event.raw.tool_use_result && typeof event.raw.tool_use_result === "object") {
      body = JSON.stringify(event.raw.tool_use_result, null, 2);
    }
    blocks.push({
      kind: "tool_result",
      content: toolBlockContent(
        toolUseId ? `${summary} ${toolUseId}` : summary,
        event.itemKind === "tool_error" ? "error" : "ok",
        body || summary
      ),
      raw: summary,
    });
    return blocks;
  }

  if (event.raw.type === "assistant") {
    const text = contentText(content);
    if (text) {
      blocks.push({
        kind: "chat",
        role: "assistant",
        content: text,
        raw: text,
      });
    }
    return blocks;
  }

  if (event.raw.type === "user") {
    const text = contentText(content);
    if (text) {
      blocks.push({
        kind: "chat",
        role: "user",
        content: text,
        raw: text,
      });
    }
  }

  return blocks;
}

function interventionBlock(entry: InterventionEntry): ConversationBlock {
  const lines = [
    `mode: ${entry.actionSummary?.includes("hard") ? "hard" : "soft"}`,
    "trigger: supervisor_intervention",
    `decision: ${entry.actionSummary || "(unknown)"}`,
    `action: ${entry.forkSummary || "(none)"}`,
    `resume: true`,
    `reasons: ${entry.reason || "(none)"}`,
  ];
  return {
    kind: "text",
    content: lines.join("\n"),
    raw: lines.join("\n"),
  };
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
  const forks = await loadRunHistoryForks(runId);
  const active = await activeSessionInfo(runId);
  if (forks.length === 0) {
    return loadConversationForkBranchFallback(runId);
  }
  const sorted = forks
    .filter(
      (fork): fork is Required<
        Pick<
          RunHistoryForkSummaryFile,
          "key" | "conversationId" | "forkId" | "createdAt" | "skeletonPath"
        >
      > &
        RunHistoryForkSummaryFile =>
        Boolean(
          fork &&
            typeof fork.key === "string" &&
            typeof fork.conversationId === "string" &&
            typeof fork.forkId === "string" &&
            typeof fork.createdAt === "string" &&
            typeof fork.skeletonPath === "string"
        )
    )
    .sort((a, b) => (parseTime(a.createdAt) ?? 0) - (parseTime(b.createdAt) ?? 0));
  const baseBranches = sorted.map((fork) => ({
    key: fork.key,
    mode: fork.mode ?? null,
    label: fork.mode ?? "agent",
    conversationId: fork.conversationId,
    forkId: fork.forkId,
    createdAt: fork.createdAt,
    active: fork.conversationId === active.conversationId && fork.forkId === active.forkId,
    initialUserPreview:
      typeof fork.initialUserPreview === "string" ? fork.initialUserPreview : null,
    lastAssistantPreview:
      typeof fork.lastAssistantPreview === "string" ? fork.lastAssistantPreview : null,
  })) satisfies AgentConversationBranch[];

  const mergedBranches = [...baseBranches];
  if (
    active.conversationId &&
    active.forkId &&
    !mergedBranches.some(
      (branch) =>
        branch.conversationId === active.conversationId && branch.forkId === active.forkId
    )
  ) {
    mergedBranches.push({
      key: `${active.conversationId}:${active.forkId}`,
      mode: active.mode,
      label: active.mode || "agent",
      conversationId: active.conversationId,
      forkId: active.forkId,
      createdAt: new Date().toISOString(),
      active: true,
      initialUserPreview: null,
      lastAssistantPreview: null,
    });
  }

  if (mergedBranches.length === 0) {
    return loadConversationForkBranchFallback(runId);
  }

  mergedBranches.sort((a, b) => (parseTime(a.createdAt) ?? 0) - (parseTime(b.createdAt) ?? 0));
  const modeCounts = new Map<string, number>();
  for (const branch of mergedBranches) {
    const mode = branch.mode?.trim() || "agent";
    modeCounts.set(mode, (modeCounts.get(mode) ?? 0) + 1);
  }
  const seenPerMode = new Map<string, number>();
  const branches = mergedBranches.map((branch) => {
    const mode = branch.mode?.trim() || "agent";
    const nextIndex = (seenPerMode.get(mode) ?? 0) + 1;
    seenPerMode.set(mode, nextIndex);
    const totalForMode = modeCounts.get(mode) ?? 1;
    return {
      ...branch,
      label: totalForMode > 1 ? `${mode} (${nextIndex})` : mode,
      active:
        branch.conversationId === active.conversationId && branch.forkId === active.forkId,
    } satisfies AgentConversationBranch;
  });

  return { branches };
}

async function readAgentBranchSkeletonDocument(
  runId: string,
  branchKey: string,
  options: { hiddenEvents?: number; maxEvents?: number }
): Promise<AgentConversationDocument> {
  const active = await activeSessionInfo(runId);
  const activeCompositeBranchKey =
    active.conversationId && active.forkId
      ? `${active.conversationId}:${active.forkId}`
      : null;
  const matchesActiveBranch =
    (activeCompositeBranchKey && branchKey === activeCompositeBranchKey)
    || (active.forkId && branchKey === active.forkId);
  if (matchesActiveBranch) {
    return readAgentConversationDocument(runId, {
      hiddenEvents: options.hiddenEvents,
      maxEvents: options.maxEvents,
    });
  }

  const forks = await loadRunHistoryForks(runId);
  const fork = forks.find((entry) => entry.key === branchKey);
  if (
    !fork ||
    typeof fork.conversationId !== "string" ||
    typeof fork.forkId !== "string" ||
    typeof fork.skeletonPath !== "string"
  ) {
    return {
      blocks: [],
      source: null,
      totalLines: 0,
      totalEvents: 0,
      shownEvents: 0,
      hiddenEvents: 0,
    };
  }

  if (fork.conversationId === active.conversationId && fork.forkId === active.forkId) {
    return readAgentConversationDocument(runId, {
      hiddenEvents: options.hiddenEvents,
      maxEvents: options.maxEvents,
    });
  }

  try {
    const skeletonPath = path.join(runDir(runId), fork.skeletonPath);
    const text = await fs.readFile(skeletonPath, "utf-8");
    const blocks = parseConversationBlocks(text);
    const windowed = sliceConversationBlocks(blocks, options);
    return {
      blocks: windowed.blocks,
      source: `${fork.mode || "agent"} branch`,
      totalLines: text.split("\n").length,
      totalEvents: windowed.totalEvents,
      shownEvents: windowed.shownEvents,
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
  const active = await activeSessionInfo(runId);
  const agentBaseBlock = await loadAgentBaseBlock(runId);
  const rawEvents = await loadRawEvents(runId, conversationId);
  const interventions = await loadInterventions(runId, conversationId);

  const combined: Array<
    | { ts: string; type: "event"; payload: RawEventEntry }
    | { ts: string; type: "intervention"; payload: InterventionEntry }
  > = [
    ...rawEvents.map((payload) => ({ ts: payload.ts, type: "event" as const, payload })),
    ...interventions.map((payload) => ({ ts: payload.ts, type: "intervention" as const, payload })),
  ].sort((a, b) => (parseTime(a.ts) ?? 0) - (parseTime(b.ts) ?? 0));

  const eventBlocks = combined.flatMap((entry) =>
    entry.type === "event" ? rawEventToBlocks(entry.payload) : [interventionBlock(entry.payload)]
  );
  const windowed = sliceBlocks(eventBlocks, options);
  const blocks = [
    ...(active.frontmatterBlock ? [active.frontmatterBlock] : []),
    ...(agentBaseBlock ? [agentBaseBlock] : []),
    ...windowed.blocks,
  ];

  return {
    blocks,
    source: active.mode ? `${active.mode} raw events` : conversationId ? "agent raw events" : null,
    totalLines: (active.frontmatterBlock ? active.frontmatterBlock.content.split("\n").length : 0)
      + (agentBaseBlock ? agentBaseBlock.content.split("\n").length : 0)
      + eventBlocks.reduce((sum, block) => sum + block.content.split("\n").length, 0),
    totalEvents: windowed.totalEvents + (agentBaseBlock ? 1 : 0) + (active.frontmatterBlock ? 1 : 0),
    shownEvents: windowed.shownEvents + (agentBaseBlock ? 1 : 0) + (active.frontmatterBlock ? 1 : 0),
    hiddenEvents: windowed.hiddenEvents,
  };
}
