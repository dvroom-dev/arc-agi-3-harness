import fs from "fs/promises";
import path from "path";
import { runDir } from "@/lib/paths";

export interface RunHistoryForkSummaryFile {
  key?: string;
  conversationId?: string;
  forkId?: string;
  createdAt?: string;
  mode?: string;
  initialUserPreview?: string;
  lastAssistantPreview?: string;
  skeletonPath?: string;
  assistantTurns?: number;
  toolCallCount?: number;
  toolResultCount?: number;
}

async function latestConversationIdFromRunHistory(runId: string): Promise<string | null> {
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
    const ranked = (payload.conversations ?? [])
      .map((entry) => {
        const conversationId =
          typeof entry?.conversationId === "string" && entry.conversationId.trim()
            ? entry.conversationId.trim()
            : null;
        const ts = Math.max(
          Date.parse(typeof entry?.lastForkAt === "string" ? entry.lastForkAt : ""),
          Date.parse(typeof entry?.firstForkAt === "string" ? entry.firstForkAt : "")
        );
        return {
          conversationId,
          sortKey: Number.isFinite(ts) ? ts : 0,
        };
      })
      .filter((entry): entry is { conversationId: string; sortKey: number } => Boolean(entry.conversationId))
      .sort((a, b) => b.sortKey - a.sortKey || a.conversationId.localeCompare(b.conversationId));
    return ranked[0]?.conversationId ?? null;
  } catch {
    return null;
  }
}

export async function preferredConversationId(runId: string): Promise<string | null> {
  return latestConversationIdFromRunHistory(runId);
}

export async function findConversationId(runId: string): Promise<string | null> {
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

export async function loadRunHistoryForks(runId: string): Promise<RunHistoryForkSummaryFile[]> {
  const indexPath = path.join(
    runDir(runId),
    ".ai-supervisor",
    "supervisor",
    "run_history",
    "index.json"
  );
  try {
    const payload = JSON.parse(await fs.readFile(indexPath, "utf-8")) as {
      forks?: RunHistoryForkSummaryFile[];
    };
    return Array.isArray(payload.forks) ? payload.forks : [];
  } catch {
    return [];
  }
}
