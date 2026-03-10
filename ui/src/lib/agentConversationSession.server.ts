import fs from "fs/promises";
import path from "path";
import type { ConversationBlock } from "@/lib/conversation";
import { ctxDir, runDir } from "@/lib/paths";
import type { AgentConversationBranch } from "@/lib/types";

export interface SessionMetadata {
  conversationId: string | null;
  forkId: string | null;
  mode: string | null;
  frontmatterBlock: ConversationBlock | null;
}

export async function activeSessionInfo(runId: string): Promise<SessionMetadata> {
  const sessionFile = path.join(ctxDir(runId), "session.md");
  try {
    const text = await fs.readFile(sessionFile, "utf-8");
    const frontmatterMatch = text.match(/^---\n([\s\S]*?)\n---/);
    const frontmatterContent = frontmatterMatch?.[1]?.trim() || "";
    return {
      conversationId: text.match(/^conversation_id:\s*(.+)$/m)?.[1]?.trim() || null,
      forkId: text.match(/^fork_id:\s*(.+)$/m)?.[1]?.trim() || null,
      mode: text.match(/^mode:\s*(.+)$/m)?.[1]?.trim() || null,
      frontmatterBlock: frontmatterContent
        ? {
            kind: "frontmatter",
            content: frontmatterContent,
            raw: frontmatterContent,
          }
        : null,
    };
  } catch {
    return { conversationId: null, forkId: null, mode: null, frontmatterBlock: null };
  }
}

export async function loadAgentBaseBlock(runId: string): Promise<ConversationBlock | null> {
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

export async function loadConversationForkBranchFallback(
  runId: string
): Promise<{ branches: AgentConversationBranch[] }> {
  const active = await activeSessionInfo(runId);
  if (!active.conversationId || !active.forkId) {
    return { branches: [] };
  }
  const indexPath = path.join(
    runDir(runId),
    ".ai-supervisor",
    "conversations",
    active.conversationId,
    "index.json"
  );
  try {
    const payload = JSON.parse(await fs.readFile(indexPath, "utf-8")) as {
      forks?: Array<Record<string, unknown>>;
    };
    const forks = Array.isArray(payload.forks) ? payload.forks : [];
    const branches = forks
      .map((fork) => {
        const forkId = typeof fork.id === "string" ? fork.id : null;
        if (!forkId) return null;
        const mode =
          typeof fork.mode === "string" && fork.mode.trim()
            ? fork.mode.trim()
            : forkId === active.forkId
              ? active.mode
              : null;
        return {
          key: forkId,
          mode,
          label: mode || "agent",
          conversationId: active.conversationId!,
          forkId,
          createdAt: typeof fork.createdAt === "string" ? fork.createdAt : new Date(0).toISOString(),
          active: forkId === active.forkId,
          initialUserPreview: null,
          lastAssistantPreview: null,
        } satisfies AgentConversationBranch;
      })
      .filter((branch): branch is AgentConversationBranch => Boolean(branch));
    if (branches.length > 0) {
      return { branches };
    }
  } catch {
    // fall through
  }
  return {
    branches: [
      {
        key: active.forkId,
        mode: active.mode,
        label: active.mode || "agent",
        conversationId: active.conversationId,
        forkId: active.forkId,
        createdAt: new Date(0).toISOString(),
        active: true,
        initialUserPreview: null,
        lastAssistantPreview: null,
      },
    ],
  };
}
