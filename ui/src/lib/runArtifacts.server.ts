import fs from "fs/promises";
import path from "path";
import { parseConversationBlocks, sliceConversationBlocks } from "@/lib/conversation";
import { agentDir, ctxDir, runDir } from "@/lib/paths";

export interface ConversationDocument {
  blocks: import("@/lib/conversation").ConversationBlock[];
  source: string | null;
  totalLines: number;
  totalEvents: number;
  shownEvents: number;
  hiddenEvents: number;
}

interface ConversationHead {
  conversationId: string;
  documentText: string;
}

interface RawEventToolResultContent {
  content: string | null;
  source: string | null;
}

function trimTrailingBlankLines(lines: string[]) {
  let end = lines.length;
  while (end > 0 && lines[end - 1] === "") end -= 1;
  return lines.slice(0, end);
}

async function exists(filePath: string) {
  try {
    await fs.access(filePath);
    return true;
  } catch {
    return false;
  }
}

async function findConversationHead(runId: string): Promise<ConversationHead | null> {
  const conversationsDir = path.join(runDir(runId), ".ai-supervisor", "conversations");
  const sessionFile = path.join(ctxDir(runId), "session.md");
  let preferredConversationId: string | null = null;

  try {
    const sessionText = await fs.readFile(sessionFile, "utf-8");
    const match = sessionText.match(/^conversation_id:\s*(.+)$/m);
    preferredConversationId = match?.[1]?.trim() || null;
  } catch {
    preferredConversationId = null;
  }

  let conversationIds: string[] = [];
  try {
    const entries = await fs.readdir(conversationsDir, { withFileTypes: true });
    conversationIds = entries
      .filter((entry) => entry.isDirectory())
      .map((entry) => entry.name)
      .sort();
  } catch {
    return null;
  }

  if (conversationIds.length === 0) return null;

  const orderedIds = preferredConversationId
    ? [preferredConversationId, ...conversationIds.filter((id) => id !== preferredConversationId)]
    : conversationIds;

  for (const conversationId of orderedIds) {
    const conversationDir = path.join(conversationsDir, conversationId);
    const indexPath = path.join(conversationDir, "index.json");
    let headId = "";
    try {
      const indexPayload = JSON.parse(await fs.readFile(indexPath, "utf-8")) as {
        headId?: unknown;
      };
      headId = typeof indexPayload.headId === "string" ? indexPayload.headId : "";
    } catch {
      headId = "";
    }
    if (!headId) continue;

    const forkPath = path.join(conversationDir, "forks", `${headId}.json`);
    try {
      const forkPayload = JSON.parse(await fs.readFile(forkPath, "utf-8")) as {
        documentText?: unknown;
      };
      if (typeof forkPayload.documentText === "string" && forkPayload.documentText.trim()) {
        return {
          conversationId,
          documentText: forkPayload.documentText,
        };
      }
    } catch {
      // Try the next conversation candidate.
    }
  }

  return null;
}

async function conversationRawEventsPath(runId: string): Promise<string | null> {
  const head = await findConversationHead(runId);
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
  const sessionFile = path.join(ctxDir(runId), "session.md");
  try {
    const content = await fs.readFile(sessionFile, "utf-8");
    const lines = trimTrailingBlankLines(content.split("\n"));
    if (lines.length > 0) {
      const blocks = parseConversationBlocks(lines.join("\n"));
      const windowed = sliceConversationBlocks(blocks, options);
      return {
        blocks: windowed.blocks,
        source: "session.md",
        totalLines: lines.length,
        totalEvents: windowed.totalEvents,
        shownEvents: windowed.shownEvents,
        hiddenEvents: windowed.hiddenEvents,
      };
    }
  } catch {
    // Fall through to the conversation-store snapshot.
  }

  const head = await findConversationHead(runId);
  if (head) {
    const lines = trimTrailingBlankLines(head.documentText.split("\n"));
    const blocks = parseConversationBlocks(lines.join("\n"));
    const windowed = sliceConversationBlocks(blocks, options);
    return {
      blocks: windowed.blocks,
      source: `${head.conversationId} snapshot`,
      totalLines: lines.length,
      totalEvents: windowed.totalEvents,
      shownEvents: windowed.shownEvents,
      hiddenEvents: windowed.hiddenEvents,
    };
  }

  return {
    blocks: [],
    source: null,
    totalLines: 0,
    totalEvents: 0,
    shownEvents: 0,
    hiddenEvents: 0,
  };
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
