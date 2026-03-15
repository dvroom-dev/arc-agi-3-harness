import type { ConversationBlock } from "@/lib/conversation";
import type { RawEventEntry } from "@/lib/agentConversationEvents.server";

export interface ParsedToolCall {
  name: string;
  toolUseId: string | null;
  body: string;
}

export interface ParsedToolResult {
  toolUseId: string | null;
  body: string;
  status: "ok" | "error";
}

const COMPACT_TOOL_DETAILS_OMITTED = "(details omitted in compact view)";

function buildPreviewLine(content: string) {
  return content.replace(/\s+/g, " ").trim() || "(empty)";
}

export function parseToolCallEvent(event: RawEventEntry): ParsedToolCall {
  const message =
    event.raw.message && typeof event.raw.message === "object"
      ? (event.raw.message as { content?: unknown })
      : null;
  const content = message?.content;
  let name = event.itemSummary || "tool_call";
  let toolUseId: string | null = null;
  if (Array.isArray(content)) {
    const toolUse = content.find(
      (entry) =>
        entry &&
        typeof entry === "object" &&
        (entry as { type?: unknown }).type === "tool_use"
    ) as
      | { id?: unknown; name?: unknown; input?: unknown }
      | undefined;
    if (toolUse) {
      if (typeof toolUse.name === "string" && toolUse.name.trim()) {
        name = toolUse.name;
      }
      if (typeof toolUse.id === "string" && toolUse.id.trim()) {
        toolUseId = toolUse.id;
      }
    }
  }

  return {
    name,
    toolUseId,
    body: COMPACT_TOOL_DETAILS_OMITTED,
  };
}

export function parseToolResultEvent(event: RawEventEntry): ParsedToolResult {
  const message =
    event.raw.message && typeof event.raw.message === "object"
      ? (event.raw.message as { content?: unknown })
      : null;
  const content = message?.content;

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

  return {
    toolUseId,
    body: COMPACT_TOOL_DETAILS_OMITTED,
    status: event.itemKind === "tool_error" ? "error" : "ok",
  };
}

export function buildToolEventBlock(
  toolCall: ParsedToolCall,
  toolResult: ParsedToolResult | null
): ConversationBlock {
  const status = toolResult?.status ?? "pending";
  const result = toolResult?.body ?? null;
  const resultStatus = toolResult?.status.toUpperCase() ?? "PENDING";
  const content = [
    `tool call ${toolCall.name} ${status.toUpperCase()}`,
    `Call: ${buildPreviewLine(toolCall.body)}`,
    result === null
      ? "Result pending"
      : `Result ${resultStatus}: ${buildPreviewLine(result)}`,
  ].join("\n");

  return {
    kind: "tool",
    content,
    tool: {
      name: toolCall.name,
      status,
      call: toolCall.body,
      result,
      toolUseId: toolCall.toolUseId,
    },
    raw: toolCall.name,
  };
}
