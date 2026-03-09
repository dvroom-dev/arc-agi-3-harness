import fs from "fs/promises";
import path from "path";
import type { ConversationBlock } from "@/lib/conversation";
import { ctxDir, runDir } from "@/lib/paths";

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

async function preferredConversationId(runId: string): Promise<string | null> {
  const sessionFile = path.join(ctxDir(runId), "session.md");
  try {
    const text = await fs.readFile(sessionFile, "utf-8");
    return text.match(/^conversation_id:\s*(.+)$/m)?.[1]?.trim() || null;
  } catch {
    return null;
  }
}

async function findConversationId(runId: string): Promise<string | null> {
  const conversationsDir = path.join(runDir(runId), ".ai-supervisor", "conversations");
  const preferredId = await preferredConversationId(runId);
  let conversationIds: string[] = [];
  try {
    conversationIds = (await fs.readdir(conversationsDir, { withFileTypes: true }))
      .filter((entry) => entry.isDirectory())
      .map((entry) => entry.name)
      .sort();
  } catch {
    return null;
  }
  if (conversationIds.length === 0) return null;
  if (preferredId && conversationIds.includes(preferredId)) return preferredId;
  return conversationIds.at(-1) ?? null;
}

async function loadAgentBaseBlock(runId: string): Promise<ConversationBlock | null> {
  const sessionFile = path.join(ctxDir(runId), "session.md");
  try {
    const text = await fs.readFile(sessionFile, "utf-8");
    const match = text.match(/(`{3,})chat role=system scope=agent_base\n([\s\S]*?)\n\1/);
    if (!match) return null;
    const content = match[2]?.trim();
    if (!content) return null;
    return {
      kind: "chat",
      role: "system",
      header: "```chat role=system scope=agent_base",
      meta: { role: "system", scope: "agent_base" },
      content,
      raw: match[0],
    };
  } catch {
    return null;
  }
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

export async function readAgentConversationDocument(
  runId: string,
  options: { hiddenEvents?: number; maxEvents?: number }
): Promise<AgentConversationDocument> {
  const conversationId = await findConversationId(runId);
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
  const blocks = agentBaseBlock ? [agentBaseBlock, ...windowed.blocks] : windowed.blocks;

  return {
    blocks,
    source: conversationId ? `${conversationId} raw events` : null,
    totalLines: (agentBaseBlock ? agentBaseBlock.content.split("\n").length : 0)
      + eventBlocks.reduce((sum, block) => sum + block.content.split("\n").length, 0),
    totalEvents: windowed.totalEvents + (agentBaseBlock ? 1 : 0),
    shownEvents: windowed.shownEvents + (agentBaseBlock ? 1 : 0),
    hiddenEvents: windowed.hiddenEvents,
  };
}
