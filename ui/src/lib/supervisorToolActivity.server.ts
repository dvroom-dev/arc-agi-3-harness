import type { RawEventEntry } from "@/lib/agentConversationEvents.server";

export interface ToolBurstSummary {
  startedAt: string;
  endedAt: string;
  sessionId: string | null;
  toolCounts: Array<{ name: string; count: number }>;
  errorCount: number;
  files: string[];
}

export interface ToolActivitySummary {
  startedAt: string;
  endedAt: string;
  sessionIds: string[];
  toolCounts: Array<{ name: string; count: number }>;
  errorCount: number;
  files: string[];
}

function parseTime(value: string | null | undefined): number {
  const parsed = Date.parse(value ?? "");
  return Number.isFinite(parsed) ? parsed : 0;
}

function summarizeToolName(event: RawEventEntry): string | null {
  const message =
    event.raw.message && typeof event.raw.message === "object"
      ? (event.raw.message as { content?: unknown })
      : null;
  const content = message?.content;
  if (Array.isArray(content)) {
    const toolUse = content.find(
      (entry) =>
        entry &&
        typeof entry === "object" &&
        (entry as { type?: unknown }).type === "tool_use"
    ) as { name?: unknown } | undefined;
    if (toolUse && typeof toolUse.name === "string" && toolUse.name.trim()) {
      return toolUse.name.trim();
    }
  }
  if (event.itemSummary?.startsWith("tool_call ")) {
    return event.itemSummary.slice("tool_call ".length).split(/\s+/)[0] || null;
  }
  return null;
}

function normalizePathToken(token: string): string | null {
  const trimmed = token.trim().replace(/^['"`]+|['"`]+$/g, "");
  if (!trimmed) return null;
  const normalized = trimmed.replace(/[),;:]+$/g, "");
  if (!normalized) return null;
  if (
    normalized.startsWith("./") ||
    normalized.startsWith("../") ||
    /^\/(?:home|tmp|var|Users|private|workspace)\//.test(normalized) ||
    /(?:^|\/)[A-Za-z0-9_.-]+\.(?:md|py|json|txt|hex|yaml|yml)$/.test(normalized)
  ) {
    return normalized;
  }
  return null;
}

function extractPathTokens(text: string): string[] {
  const matches =
    text.match(
      /(?:\/[^\s"'`]+|\.\.\/[^\s"'`]+|\.\/[^\s"'`]+|[A-Za-z0-9_.-]+\/[A-Za-z0-9_./-]+|[A-Za-z0-9_.-]+\.(?:md|py|json|txt|hex|yaml|yml))/g
    ) ?? [];
  return matches
    .map((match) => normalizePathToken(match))
    .filter((value): value is string => Boolean(value));
}

function collectInputPaths(value: unknown): string[] {
  if (typeof value === "string") {
    return extractPathTokens(value);
  }
  if (Array.isArray(value)) {
    return value.flatMap((entry) => collectInputPaths(entry));
  }
  if (!value || typeof value !== "object") return [];
  return Object.entries(value as Record<string, unknown>).flatMap(([key, entry]) => {
    if (key === "file_path" && typeof entry === "string") {
      const exact = normalizePathToken(entry);
      return exact ? [exact] : [];
    }
    return collectInputPaths(entry);
  });
}

function summarizeToolFiles(event: RawEventEntry): string[] {
  const message =
    event.raw.message && typeof event.raw.message === "object"
      ? (event.raw.message as { content?: unknown })
      : null;
  const content = message?.content;
  if (!Array.isArray(content)) return [];
  const toolUse = content.find(
    (entry) =>
      entry &&
      typeof entry === "object" &&
      (entry as { type?: unknown }).type === "tool_use"
  ) as { input?: unknown } | undefined;
  if (!toolUse) return [];
  return collectInputPaths(toolUse.input).slice(0, 8);
}

function isToolErrorEvent(event: RawEventEntry): boolean {
  if (event.itemKind === "tool_error") return true;
  if (event.itemKind !== "tool_result") return false;
  const message =
    event.raw.message && typeof event.raw.message === "object"
      ? (event.raw.message as { content?: unknown })
      : null;
  const content = message?.content;
  if (!Array.isArray(content)) return false;
  return content.some(
    (entry) =>
      entry &&
      typeof entry === "object" &&
      (entry as { type?: unknown }).type === "tool_result" &&
      (entry as { is_error?: unknown }).is_error === true
  );
}

export function summarizeToolBursts(
  rawEvents: RawEventEntry[],
  startAt: string | null,
  endAt: string | null
): ToolBurstSummary[] {
  const startMs = parseTime(startAt);
  const endMs = parseTime(endAt);
  const toolEvents = rawEvents.filter((event) => {
    if (event.itemKind !== "tool_call") return false;
    const ts = parseTime(event.ts);
    if (ts < startMs) return false;
    if (endAt && ts >= endMs) return false;
    return true;
  });

  const bursts: ToolBurstSummary[] = [];
  let current:
    | {
        startedAt: string;
        endedAt: string;
        sessionId: string | null;
        toolCounts: Map<string, number>;
        files: Set<string>;
      }
    | null = null;
  let lastTs = 0;

  for (const event of toolEvents) {
    const ts = parseTime(event.ts);
    const sessionId =
      typeof event.raw.session_id === "string" ? event.raw.session_id : null;
    const contiguous =
      current &&
      current.sessionId === sessionId &&
      ts - lastTs <= 20_000;

    if (!current || !contiguous) {
      if (current) {
        bursts.push({
          startedAt: current.startedAt,
          endedAt: current.endedAt,
          sessionId: current.sessionId,
          toolCounts: Array.from(current.toolCounts.entries()).map(([name, count]) => ({ name, count })),
          errorCount: 0,
          files: Array.from(current.files).sort().slice(0, 8),
        });
      }
      current = {
        startedAt: event.ts,
        endedAt: event.ts,
        sessionId,
        toolCounts: new Map(),
        files: new Set(),
      };
    }

    current.endedAt = event.ts;
    const toolName = summarizeToolName(event) ?? "unknown";
    current.toolCounts.set(toolName, (current.toolCounts.get(toolName) ?? 0) + 1);
    for (const file of summarizeToolFiles(event)) {
      current.files.add(file);
    }
    lastTs = ts;
  }

  if (current) {
    bursts.push({
      startedAt: current.startedAt,
      endedAt: current.endedAt,
      sessionId: current.sessionId,
      toolCounts: Array.from(current.toolCounts.entries()).map(([name, count]) => ({ name, count })),
      errorCount: 0,
      files: Array.from(current.files).sort().slice(0, 8),
    });
  }

  for (const burst of bursts) {
    const burstStartMs = parseTime(burst.startedAt);
    const burstEndMs = parseTime(burst.endedAt);
    burst.errorCount = rawEvents.filter((event) => {
      if (!isToolErrorEvent(event)) return false;
      if (burst.sessionId && event.raw.session_id !== burst.sessionId) return false;
      const ts = parseTime(event.ts);
      return ts >= burstStartMs && ts <= burstEndMs;
    }).length;
  }

  return bursts;
}

export function combineToolBursts(
  bursts: ToolBurstSummary[]
): ToolActivitySummary | null {
  if (bursts.length === 0) return null;

  const sessionIds = new Set<string>();
  const toolCounts = new Map<string, number>();
  let errorCount = 0;
  const files = new Set<string>();

  for (const burst of bursts) {
    if (burst.sessionId) {
      sessionIds.add(burst.sessionId);
    }
    for (const entry of burst.toolCounts) {
      toolCounts.set(entry.name, (toolCounts.get(entry.name) ?? 0) + entry.count);
    }
    errorCount += burst.errorCount;
    for (const file of burst.files) {
      files.add(file);
    }
  }

  return {
    startedAt: bursts[0].startedAt,
    endedAt: bursts[bursts.length - 1].endedAt,
    sessionIds: Array.from(sessionIds).sort(),
    toolCounts: Array.from(toolCounts.entries()).map(([name, count]) => ({
      name,
      count,
    })),
    errorCount,
    files: Array.from(files).sort().slice(0, 8),
  };
}
