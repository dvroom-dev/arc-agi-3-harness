import fs from "fs/promises";
import path from "path";
import { ctxDir, runDir } from "@/lib/paths";

export interface RunHistoryForkSummaryFile {
  key?: string;
  conversationId?: string;
  forkId?: string;
  createdAt?: string;
  mode?: string;
  initialUserPreview?: string;
  lastAssistantPreview?: string;
  skeletonPath?: string;
}

export async function preferredConversationId(runId: string): Promise<string | null> {
  const sessionFile = path.join(ctxDir(runId), "session.md");
  try {
    const text = await fs.readFile(sessionFile, "utf-8");
    return text.match(/^conversation_id:\s*(.+)$/m)?.[1]?.trim() || null;
  } catch {
    return null;
  }
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
