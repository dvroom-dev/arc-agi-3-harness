import fs from "fs/promises";
import path from "path";
import { runDir } from "@/lib/paths";
import type { SuperCheckResult } from "@/lib/types";

export interface RawEventRecord {
  ts: string;
  provider: string | null;
  itemKind: string | null;
  itemSummary: string | null;
  raw: Record<string, unknown>;
  sessionId: string | null;
}

export interface SessionMetadata {
  sessionId: string;
  startedAt: string;
  endedAt: string;
  provider: string | null;
  model: string | null;
  enabledTools: string[];
}

export interface ReviewChecks {
  ruleChecks: SuperCheckResult[] | null;
  violationChecks: SuperCheckResult[] | null;
}

export function extractToolName(
  raw: Record<string, unknown>,
  itemSummary: string | null
): string | null {
  const message = raw.message;
  if (message && typeof message === "object") {
    const content = (message as { content?: unknown }).content;
    if (Array.isArray(content)) {
      for (const entry of content) {
        if (
          entry &&
          typeof entry === "object" &&
          (entry as { type?: unknown }).type === "tool_use" &&
          typeof (entry as { name?: unknown }).name === "string"
        ) {
          return (entry as { name: string }).name;
        }
      }
    }
  }

  if (itemSummary?.startsWith("tool_call ")) {
    return itemSummary.slice("tool_call ".length).split(/\s+/)[0] || null;
  }
  return null;
}

function normalizeChecks(raw: unknown): SuperCheckResult[] | null {
  if (!Array.isArray(raw)) return null;
  const checks = raw
    .map((entry) => {
      if (!entry || typeof entry !== "object") return null;
      const record = entry as Record<string, unknown>;
      const rule = typeof record.rule === "string" ? record.rule : "";
      const status = typeof record.status === "string" ? record.status : "";
      if (!rule || !status) return null;
      return {
        rule,
        status,
        comment: typeof record.comment === "string" ? record.comment : null,
      } satisfies SuperCheckResult;
    })
    .filter((entry): entry is SuperCheckResult => Boolean(entry));
  return checks.length > 0 ? checks : [];
}

export async function loadReviewChecks(
  runId: string,
  conversationId: string | null
): Promise<Map<string, ReviewChecks>> {
  const byReason = new Map<string, ReviewChecks>();
  if (!conversationId) return byReason;
  const reviewsDir = path.join(
    runDir(runId),
    ".ai-supervisor",
    "conversations",
    conversationId,
    "reviews"
  );
  let names: string[] = [];
  try {
    names = (await fs.readdir(reviewsDir))
      .filter((name) => name.endsWith("_response.txt"))
      .sort();
  } catch {
    return byReason;
  }

  for (const name of names) {
    try {
      const payload = JSON.parse(await fs.readFile(path.join(reviewsDir, name), "utf-8")) as {
        reasoning?: unknown;
        payload?: {
          agent_rule_checks?: unknown;
          agent_violation_checks?: unknown;
        };
      };
      const reasoning = typeof payload.reasoning === "string" ? payload.reasoning : null;
      if (!reasoning) continue;
      byReason.set(reasoning, {
        ruleChecks: normalizeChecks(payload.payload?.agent_rule_checks),
        violationChecks: normalizeChecks(payload.payload?.agent_violation_checks),
      });
    } catch {
      // Ignore malformed review payloads.
    }
  }

  return byReason;
}

export async function loadRawEvents(
  runId: string,
  conversationId: string | null,
  parseTime: (value: string | null | undefined) => number | null
): Promise<{
  events: RawEventRecord[];
  sessionMetadata: Map<string, SessionMetadata>;
}> {
  if (!conversationId) return { events: [], sessionMetadata: new Map() };
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
    return { events: [], sessionMetadata: new Map() };
  }

  const events: RawEventRecord[] = [];
  const sessionMetadata = new Map<string, SessionMetadata>();

  for (const line of lines) {
    let parsed: unknown;
    try {
      parsed = JSON.parse(line);
    } catch {
      continue;
    }
    if (!parsed || typeof parsed !== "object") continue;
    const event = parsed as {
      ts?: string;
      provider?: string;
      item_kind?: string;
      item_summary?: string;
      raw?: Record<string, unknown>;
    };
    const raw = event.raw ?? {};
    const sessionId = typeof raw.session_id === "string" ? raw.session_id : null;
    const ts = typeof event.ts === "string" ? event.ts : null;
    if (!ts) continue;

    events.push({
      ts,
      provider: typeof event.provider === "string" ? event.provider : null,
      itemKind: typeof event.item_kind === "string" ? event.item_kind : null,
      itemSummary: typeof event.item_summary === "string" ? event.item_summary : null,
      raw,
      sessionId,
    });

    if (sessionId && raw.type === "system" && raw.subtype === "init") {
      sessionMetadata.set(sessionId, {
        sessionId,
        startedAt: ts,
        endedAt: ts,
        provider: typeof event.provider === "string" ? event.provider : null,
        model: typeof raw.model === "string" ? raw.model : null,
        enabledTools: Array.isArray(raw.tools)
          ? raw.tools.filter((tool): tool is string => typeof tool === "string")
          : [],
      });
      continue;
    }

    if (!sessionId) continue;
    const metadata = sessionMetadata.get(sessionId);
    if (metadata) {
      metadata.endedAt = ts;
      if (!metadata.provider && typeof event.provider === "string") {
        metadata.provider = event.provider;
      }
      if (!metadata.model && typeof raw.model === "string") {
        metadata.model = raw.model;
      }
      continue;
    }
    sessionMetadata.set(sessionId, {
      sessionId,
      startedAt: ts,
      endedAt: ts,
      provider: typeof event.provider === "string" ? event.provider : null,
      model: typeof raw.model === "string" ? raw.model : null,
      enabledTools: [],
    });
  }

  events.sort((a, b) => (parseTime(a.ts) ?? 0) - (parseTime(b.ts) ?? 0));
  return { events, sessionMetadata };
}

export function aggregateCycleWindow(
  cycleStartAt: string | null,
  nextForkAt: string | null,
  providerName: string | null,
  model: string | null,
  rawEvents: RawEventRecord[],
  sessionMetadata: Map<string, SessionMetadata>,
  parseTime: (value: string | null | undefined) => number | null
) {
  const startMs = parseTime(cycleStartAt);
  const endMs = parseTime(nextForkAt);
  const windowEvents = rawEvents.filter((event) => {
    const eventMs = parseTime(event.ts);
    if (eventMs == null) return false;
    if (startMs != null && eventMs < startMs) return false;
    if (endMs != null && eventMs >= endMs) return false;
    return true;
  });

  const sessionIds = Array.from(
    new Set(windowEvents.map((event) => event.sessionId).filter((value): value is string => Boolean(value)))
  );
  const primarySessionId = sessionIds[0] ?? null;
  const primarySession = primarySessionId ? sessionMetadata.get(primarySessionId) ?? null : null;
  const startedAt = windowEvents[0]?.ts ?? cycleStartAt ?? "";
  const lastEventAt = windowEvents.at(-1)?.ts ?? null;
  const endedAt = lastEventAt ?? nextForkAt ?? null;
  const toolCounts = new Map<string, number>();
  let toolCallCount = 0;
  let toolResultCount = 0;
  let toolErrorCount = 0;
  let assistantTextCount = 0;
  let userTextCount = 0;
  let firstToolLatencyMs: number | null = null;
  let enabledTools = primarySession?.enabledTools ?? [];

  for (const event of windowEvents) {
    if (!enabledTools.length && event.sessionId) {
      enabledTools = sessionMetadata.get(event.sessionId)?.enabledTools ?? enabledTools;
    }

    if (event.itemKind === "tool_call") {
      toolCallCount += 1;
      const toolName = extractToolName(event.raw, event.itemSummary);
      if (toolName) {
        toolCounts.set(toolName, (toolCounts.get(toolName) ?? 0) + 1);
      }
      if (firstToolLatencyMs == null) {
        const callMs = parseTime(event.ts);
        firstToolLatencyMs =
          startMs != null && callMs != null ? Math.max(0, callMs - startMs) : null;
      }
    } else if (event.itemKind === "tool_result") {
      toolResultCount += 1;
    } else if (event.itemKind === "tool_error") {
      toolErrorCount += 1;
    }

    const message = event.raw.message;
    const content =
      message && typeof message === "object" ? (message as { content?: unknown }).content : null;
    if (event.raw.type === "assistant" && Array.isArray(content)) {
      const hasToolUse = content.some(
        (entry) =>
          entry &&
          typeof entry === "object" &&
          (entry as { type?: unknown }).type === "tool_use"
      );
      const hasText = content.some(
        (entry) =>
          entry &&
          typeof entry === "object" &&
          (entry as { type?: unknown }).type === "text" &&
          typeof (entry as { text?: unknown }).text === "string" &&
          Boolean((entry as { text: string }).text.trim())
      );
      if (hasText || hasToolUse) {
        assistantTextCount += 1;
      }
    } else if (event.raw.type === "user") {
      if (typeof content === "string" && content.trim()) {
        userTextCount += 1;
      } else if (Array.isArray(content)) {
        const hasUserText = content.some((entry) => {
          if (typeof entry === "string") return Boolean(entry.trim());
          return (
            entry &&
            typeof entry === "object" &&
            (entry as { type?: unknown }).type === "text" &&
            typeof (entry as { text?: unknown }).text === "string" &&
            Boolean((entry as { text: string }).text.trim())
          );
        });
        if (hasUserText) {
          userTextCount += 1;
        }
      }
    }
  }

  const durationMs =
    startMs != null && parseTime(endedAt) != null
      ? Math.max(0, (parseTime(endedAt) ?? 0) - startMs)
      : null;

  return {
    startedAt,
    endedAt,
    durationMs,
    sessionId: primarySessionId,
    provider:
      primarySession?.provider ??
      windowEvents.find((event) => event.provider)?.provider ??
      providerName,
    model:
      primarySession?.model ??
      (windowEvents.find((event) => typeof event.raw.model === "string")?.raw.model as string | undefined) ??
      model,
    enabledTools,
    totalEvents: windowEvents.length,
    toolCallCount,
    toolResultCount,
    toolErrorCount,
    assistantTextCount,
    userTextCount,
    firstToolLatencyMs,
    lastEventAt,
    toolCounts,
  };
}
