import fs from "fs/promises";
import path from "path";
import { agentDir, runDir } from "@/lib/paths";
import {
  readSupervisorConversationDocument,
  resolveActiveSupervisorConversation,
} from "@/lib/supervisorConversation.server";

export interface ConversationDocument {
  blocks: import("@/lib/conversation").ConversationBlock[];
  source: string | null;
  totalLines: number;
  totalEvents: number;
  shownEvents: number;
  hiddenEvents: number;
}

interface RawEventToolResultContent {
  content: string | null;
  source: string | null;
}

async function exists(filePath: string) {
  try {
    await fs.access(filePath);
    return true;
  } catch {
    return false;
  }
}

async function conversationRawEventsPath(runId: string): Promise<string | null> {
  const head = await resolveActiveSupervisorConversation(runId);
  if (!head) return null;
  return path.join(
    runDir(runId),
    ".ai-supervisor",
    "conversations",
    head.conversationId,
    "raw_events",
    "events.ndjson"
  );
}

async function listConversationRawEventsPaths(runId: string): Promise<string[]> {
  const conversationsDir = path.join(runDir(runId), ".ai-supervisor", "conversations");
  const preferred = await conversationRawEventsPath(runId);
  const ordered = new Set<string>();

  if (preferred) {
    ordered.add(preferred);
  }

  try {
    const entries = await fs.readdir(conversationsDir, { withFileTypes: true });
    const conversationIds = entries
      .filter((entry) => entry.isDirectory())
      .map((entry) => entry.name)
      .sort()
      .reverse();
    for (const conversationId of conversationIds) {
      ordered.add(
        path.join(
          conversationsDir,
          conversationId,
          "raw_events",
          "events.ndjson"
        )
      );
    }
  } catch {
    // Fall through with whatever preferred path we had.
  }

  return Array.from(ordered);
}

export async function resolvePrimaryGameWorkspaceDir(runId: string): Promise<string | null> {
  const baseDir = agentDir(runId);
  const candidates = [baseDir];

  try {
    const firstLevel = await fs.readdir(baseDir, { withFileTypes: true });
    for (const entry of firstLevel) {
      if (!entry.isDirectory()) continue;
      const childPath = path.join(baseDir, entry.name);
      candidates.push(childPath);
      try {
        const secondLevel = await fs.readdir(childPath, { withFileTypes: true });
        for (const grandchild of secondLevel) {
          if (!grandchild.isDirectory()) continue;
          candidates.push(path.join(childPath, grandchild.name));
        }
      } catch {
        // Ignore unreadable nested directories.
      }
    }
  } catch {
    return null;
  }

  for (const candidate of candidates) {
    if (await exists(path.join(candidate, "level_current"))) {
      return candidate;
    }
  }

  return null;
}

export async function readConversationDocument(
  runId: string,
  options: { hiddenEvents?: number; maxEvents?: number }
): Promise<ConversationDocument> {
  return readSupervisorConversationDocument(runId, options);
}

function formatRawEventLine(rawLine: string): string | null {
  try {
    const payload = JSON.parse(rawLine) as {
      ts?: string;
      provider?: string;
      item_kind?: string;
      item_summary?: string;
      item_type?: string;
    };
    const time = payload.ts
      ? new Date(payload.ts).toLocaleTimeString("en-US", {
          hour12: false,
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
        })
      : "??:??:??";
    const provider = payload.provider || "provider";
    const kind = payload.item_kind || payload.item_type || "event";
    const summary = payload.item_summary || "event";
    return `[raw ${time}] [${provider}] [${kind}] ${summary}`;
  } catch {
    return null;
  }
}

export async function readRawEventTail(
  runId: string,
  maxLines = 120
): Promise<{ lines: string[]; source: string | null }> {
  const rawEventsPath = await conversationRawEventsPath(runId);
  if (!rawEventsPath) return { lines: [], source: null };

  try {
    const content = await fs.readFile(rawEventsPath, "utf-8");
    const lines = content
      .split("\n")
      .filter(Boolean)
      .slice(-maxLines)
      .map(formatRawEventLine)
      .filter((line): line is string => Boolean(line));
    return { lines, source: path.basename(rawEventsPath) };
  } catch {
    return { lines: [], source: null };
  }
}

export async function readToolResultContent(
  runId: string,
  toolUseId: string
): Promise<RawEventToolResultContent> {
  const rawEventsPaths = await listConversationRawEventsPaths(runId);

  for (const rawEventsPath of rawEventsPaths) {
    try {
      const content = await fs.readFile(rawEventsPath, "utf-8");
      const lines = content.split("\n").filter(Boolean);

      for (let i = lines.length - 1; i >= 0; i -= 1) {
        let parsed: unknown;
        try {
          parsed = JSON.parse(lines[i]);
        } catch {
          continue;
        }

        const payload =
          typeof parsed === "object" && parsed !== null
            ? (parsed as {
                raw?: {
                  message?: {
                    content?: unknown;
                  };
                  tool_use_result?: unknown;
                };
                item_id?: unknown;
              })
            : null;

        const messageContent = payload?.raw?.message?.content;
        if (Array.isArray(messageContent)) {
          for (const entry of messageContent) {
            if (
              entry &&
              typeof entry === "object" &&
              "tool_use_id" in entry &&
              entry.tool_use_id === toolUseId &&
              "type" in entry &&
              entry.type === "tool_result" &&
              "content" in entry &&
              typeof entry.content === "string"
            ) {
              return {
                content: entry.content,
                source: rawEventsPath,
              };
            }
          }
        }

        if (payload?.item_id === toolUseId) {
          const toolUseResult = payload.raw?.tool_use_result;
          if (
            typeof toolUseResult === "object" &&
            toolUseResult !== null &&
            "stdout" in toolUseResult &&
            typeof toolUseResult.stdout === "string" &&
            toolUseResult.stdout.trim()
          ) {
            return {
              content: toolUseResult.stdout,
              source: rawEventsPath,
            };
          }
          if (
            typeof toolUseResult === "object" &&
            toolUseResult !== null &&
            "content" in toolUseResult &&
            typeof toolUseResult.content === "string" &&
            toolUseResult.content.trim()
          ) {
            return {
              content: toolUseResult.content,
              source: rawEventsPath,
            };
          }
          if (typeof toolUseResult === "string" && toolUseResult.trim()) {
            return {
              content: toolUseResult,
              source: rawEventsPath,
            };
          }
        }
      }
    } catch {
      // Try the next conversation artifact.
    }
  }

  return { content: null, source: null };
}
