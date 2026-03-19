import fs from "fs/promises";
import path from "path";
import type { ConversationBlock } from "@/lib/conversation";
import { runDir } from "@/lib/paths";
import { loadStoredConversationBranchSummaries } from "@/lib/agentConversationStore.server";
import {
  buildToolEventBlock,
  parseToolCallEvent,
  parseToolResultEvent,
  type ParsedToolCall,
} from "@/lib/agentConversationTools.server";
import {
  assistantMetaDeltaText,
  assistantMetaEventText,
  assistantMetaItemId,
  contentText,
} from "@/lib/agentConversationReasoning.server";

export interface RawEventEntry {
  ts: string;
  provider: string | null;
  itemKind: string | null;
  itemSummary: string | null;
  raw: Record<string, unknown>;
}

export interface InterventionEntry {
  ts: string;
  actionSummary: string | null;
  forkSummary: string | null;
  reason: string | null;
  nextMode: string | null;
}

function parseTime(value: string | null | undefined): number | null {
  if (!value) return null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export async function loadRawEvents(
  runId: string,
  conversationId: string | null
): Promise<RawEventEntry[]> {
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

export async function loadInterventions(
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
    const storedBranches = await loadStoredConversationBranchSummaries(runId, conversationId);
    const childModeByParentId = new Map<string, string | null>();
    for (const branch of storedBranches) {
      if (branch.actionSummary !== "supervise:start" || !branch.parentId) continue;
      if (!childModeByParentId.has(branch.parentId)) {
        childModeByParentId.set(branch.parentId, branch.mode ?? null);
      }
    }
    const payload = JSON.parse(await fs.readFile(indexPath, "utf-8")) as {
      forks?: Array<Record<string, unknown>>;
    };
    if (!Array.isArray(payload.forks)) return [];
    return payload.forks
      .flatMap((fork): InterventionEntry[] => {
        const actionSummary = typeof fork.actionSummary === "string" ? fork.actionSummary : null;
        const isResume = actionSummary?.startsWith("resume_mode_head") ?? false;
        if (
          actionSummary !== "fork (hard)"
          && actionSummary !== "fork (soft)"
          && !isResume
        ) return [];
        const ts = typeof fork.createdAt === "string" ? fork.createdAt : null;
        if (!ts) return [];
        const reason =
          Array.isArray(fork.actions) &&
          fork.actions[0] &&
          typeof fork.actions[0] === "object" &&
          typeof (fork.actions[0] as { reasoning?: unknown }).reasoning === "string"
            ? (fork.actions[0] as { reasoning: string }).reasoning
            : null;
        return [{
          ts,
          actionSummary,
          forkSummary: typeof fork.forkSummary === "string" ? fork.forkSummary : null,
          reason,
          nextMode:
            typeof fork.id === "string" ? childModeByParentId.get(fork.id) ?? null : null,
        } satisfies InterventionEntry];
      })
      .sort((a, b) => (parseTime(a.ts) ?? 0) - (parseTime(b.ts) ?? 0));
  } catch {
    return [];
  }
}

function assistantEventText(event: RawEventEntry): string | null {
  const message =
    event.raw.message && typeof event.raw.message === "object"
      ? (event.raw.message as { content?: unknown })
      : null;
  const content = message?.content;

  if (event.raw.type === "assistant" || event.raw.type === "assistant_message") {
    const text =
      (typeof event.raw.text === "string" ? event.raw.text.trim() : "") ||
      contentText(content);
    return text || null;
  }

  if (event.raw.type === "result") {
    const result = typeof event.raw.result === "string" ? event.raw.result.trim() : "";
    return result || null;
  }

  return null;
}

export function rawEventToBlocks(event: RawEventEntry): ConversationBlock[] {
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

  if (event.raw.type === "system" && event.raw.subtype === "status") {
    const status = typeof event.raw.status === "string" ? event.raw.status.trim() : "";
    if (status === "compacting") {
      const lines = [
        `provider: ${event.provider || "unknown"}`,
        `status: ${status}`,
        `session_id: ${typeof event.raw.session_id === "string" ? event.raw.session_id : "unknown"}`,
      ];
      blocks.push({
        kind: "text",
        title: "Provider Status",
        content: lines.join("\n"),
        raw: lines.join("\n"),
      });
    }
    return blocks;
  }

  const message =
    event.raw.message && typeof event.raw.message === "object"
      ? (event.raw.message as { content?: unknown })
      : null;
  const content = message?.content;

  if (event.itemKind === "tool_call" || event.itemKind === "tool_result" || event.itemKind === "tool_error") {
    return blocks;
  }

  if (event.itemKind === "assistant_meta") {
    const body = assistantMetaEventText(event);
    if (body) {
      blocks.push({
        kind: "reasoning",
        title: "Reasoning Summary",
        content: body,
        raw: body,
      });
    }
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

  if (event.raw.type === "assistant_message") {
    const text =
      (typeof event.raw.text === "string" ? event.raw.text.trim() : "") ||
      contentText(
        event.raw.message && typeof event.raw.message === "object"
          ? (event.raw.message as { content?: unknown }).content
          : null
      );
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

  if (event.raw.type === "result") {
    const result = typeof event.raw.result === "string" ? event.raw.result.trim() : "";
    if (result) {
      blocks.push({
        kind: "chat",
        role: "assistant",
        content: result,
        raw: result,
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

export function rawEventsToTimedBlocks(events: RawEventEntry[]) {
  const timedBlocks: Array<{ ts: string; blocks: ConversationBlock[] }> = [];
  const pendingToolCalls = new Map<string, number>();
  const pendingAssistantMetaText = new Map<string, string>();
  let lastAssistantEvent:
    | {
        sourceType: "assistant" | "assistant_message" | "result";
        text: string;
      }
    | null = null;

  for (const event of events) {
    if (event.itemKind === "assistant_meta") {
      const delta = assistantMetaDeltaText(event);
      const itemId = assistantMetaItemId(event);
      if (delta && itemId) {
        pendingAssistantMetaText.set(
          itemId,
          `${pendingAssistantMetaText.get(itemId) ?? ""}${delta}`
        );
        continue;
      }

      const blocks = rawEventToBlocks(event);
      if (blocks.length > 0) {
        timedBlocks.push({ ts: event.ts, blocks });
      } else if (itemId) {
        const aggregated = (pendingAssistantMetaText.get(itemId) ?? "").trim();
        if (aggregated) {
          timedBlocks.push({
            ts: event.ts,
            blocks: [{
              kind: "reasoning",
              title: "Reasoning Summary",
              content: aggregated,
              raw: aggregated,
            }],
          });
        }
      }

      if (itemId) {
        pendingAssistantMetaText.delete(itemId);
      }
      continue;
    }

    if (event.itemKind === "tool_call") {
      const toolCall = parseToolCallEvent(event);
      if (!toolCall) continue;
      timedBlocks.push({
        ts: event.ts,
        blocks: [buildToolEventBlock(toolCall, null)],
      });
      if (toolCall.toolUseId) {
        pendingToolCalls.set(toolCall.toolUseId, timedBlocks.length - 1);
      }
      continue;
    }

    if (event.itemKind === "tool_result" || event.itemKind === "tool_error") {
      const toolResult = parseToolResultEvent(event);
      if (!toolResult) continue;
      const pendingIndex =
        toolResult.toolUseId ? pendingToolCalls.get(toolResult.toolUseId) : undefined;
      if (pendingIndex !== undefined) {
        const pendingEntry = timedBlocks[pendingIndex];
        const pendingBlock = pendingEntry?.blocks[0];
        if (pendingEntry && pendingBlock?.kind === "tool" && pendingBlock.tool) {
          pendingEntry.blocks = [
            buildToolEventBlock(
              {
                name: pendingBlock.tool.name,
                toolUseId: pendingBlock.tool.toolUseId,
                body: pendingBlock.tool.call,
              },
              toolResult
            ),
          ];
        }
        if (toolResult.toolUseId) {
          pendingToolCalls.delete(toolResult.toolUseId);
        }
      } else {
        const fallbackCall: ParsedToolCall = {
          name: event.itemSummary || event.itemKind || "tool",
          toolUseId: toolResult.toolUseId,
          body: "(call details unavailable)",
        };
        timedBlocks.push({
          ts: event.ts,
          blocks: [buildToolEventBlock(fallbackCall, toolResult)],
        });
      }
      continue;
    }

    const sourceType =
      event.raw.type === "assistant" ||
      event.raw.type === "assistant_message" ||
      event.raw.type === "result"
        ? event.raw.type
        : null;
    const assistantText = assistantEventText(event);
    const duplicateTerminalResult =
      sourceType === "result" &&
      assistantText &&
      lastAssistantEvent &&
      lastAssistantEvent.text === assistantText &&
      (lastAssistantEvent.sourceType === "assistant" ||
        lastAssistantEvent.sourceType === "assistant_message");

    if (!duplicateTerminalResult) {
      const blocks = rawEventToBlocks(event);
      if (blocks.length > 0) {
        timedBlocks.push({ ts: event.ts, blocks });
      }
    }

    if (sourceType && assistantText) {
      lastAssistantEvent = {
        sourceType,
        text: assistantText,
      };
    }
  }

  return timedBlocks;
}

export function interventionBlock(entry: InterventionEntry): ConversationBlock {
  const actionText = entry.nextMode
    ? `switch_mode to ${entry.nextMode}`
    : entry.forkSummary || "(none)";
  const lines = [
    `mode: ${entry.actionSummary?.includes("hard") ? "hard" : "soft"}`,
    "trigger: supervisor_intervention",
    `decision: ${entry.actionSummary || "(unknown)"}`,
    `action: ${actionText}`,
    `resume: true`,
    `reasons: ${entry.reason || "(none)"}`,
    `next_mode: ${entry.nextMode || "(none)"}`,
  ];
  return {
    kind: "text",
    content: lines.join("\n"),
    raw: lines.join("\n"),
  };
}

export function countBranchActivity(events: RawEventEntry[]) {
  let assistantTurns = 0;
  let toolCallCount = 0;
  let toolResultCount = 0;
  let lastAssistantPreview: string | null = null;

  for (const event of events) {
    if (event.itemKind === "tool_call") toolCallCount += 1;
    if (event.itemKind === "tool_result" || event.itemKind === "tool_error") toolResultCount += 1;
    if (event.itemKind === "assistant_meta") {
      const text =
        contentText(
          event.raw.message && typeof event.raw.message === "object"
            ? (event.raw.message as { content?: unknown }).content
            : null
        ) ||
        (typeof event.raw.text === "string" ? event.raw.text.trim() : "");
      if (text) {
        assistantTurns += 1;
        lastAssistantPreview = text.replace(/\s+/g, " ").trim().slice(0, 240);
      }
    } else if (event.raw.type === "assistant" || event.raw.type === "assistant_message") {
      const text = contentText(
        event.raw.message && typeof event.raw.message === "object"
          ? (event.raw.message as { content?: unknown }).content
          : null
      ) || (typeof event.raw.text === "string" ? event.raw.text.trim() : "");
      if (text) {
        assistantTurns += 1;
        lastAssistantPreview = text.replace(/\s+/g, " ").trim().slice(0, 240);
      }
    } else if (event.raw.type === "result") {
      const result = typeof event.raw.result === "string" ? event.raw.result.trim() : "";
      if (result) {
        assistantTurns += 1;
        lastAssistantPreview = result.replace(/\s+/g, " ").trim().slice(0, 240);
      }
    }
  }

  return { assistantTurns, toolCallCount, toolResultCount, lastAssistantPreview };
}

export function eventsInWindow(
  rawEvents: RawEventEntry[],
  interventions: InterventionEntry[],
  startAt: string,
  endAt: string | null
) {
  const start = parseTime(startAt);
  const end = parseTime(endAt);
  if (start === null) {
    return { eventWindow: [], interventionWindow: [] };
  }
  const eventWindow = rawEvents.filter((event) => {
    const ts = parseTime(event.ts);
    return ts !== null && ts >= start && (end === null || ts < end);
  });
  const interventionWindow = interventions.filter((entry) => {
    const ts = parseTime(entry.ts);
    return ts !== null && ts >= start && (end === null || ts < end);
  });
  return { eventWindow, interventionWindow };
}
