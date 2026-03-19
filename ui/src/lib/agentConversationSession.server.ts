import type { ConversationBlock } from "@/lib/conversation";
import { findConversationId } from "@/lib/agentConversationData.server";
import { runDir } from "@/lib/paths";
import {
  loadConversationBranchDocument,
  loadStoredConversationBranchSummaries,
} from "@/lib/agentConversationStore.server";
import type { AgentConversationBranch } from "@/lib/types";
import fs from "fs/promises";

export interface SessionMetadata {
  conversationId: string | null;
  forkId: string | null;
  mode: string | null;
  frontmatterBlock: ConversationBlock | null;
}

function extractFrontmatterBlock(documentText: string): ConversationBlock | null {
  const frontmatterMatch = documentText.match(/^---\n([\s\S]*?)\n---/);
  const frontmatterContent = frontmatterMatch?.[1]?.trim() || "";
  if (!frontmatterContent) return null;
  return {
    kind: "frontmatter",
    content: frontmatterContent,
    raw: frontmatterContent,
  };
}

async function loadActiveBranchDocument(runId: string): Promise<{
  conversationId: string;
  forkId: string;
  mode: string | null;
  documentText: string;
} | null> {
  const conversationId = await findConversationId(runId);
  if (!conversationId) return null;
  try {
    const storedBranches = await loadStoredConversationBranchSummaries(runId, conversationId);
    const activeBranch =
      storedBranches.find((branch) => branch.active) ??
      storedBranches.find((branch) => branch.head) ??
      storedBranches.at(-1) ??
      null;
    if (!activeBranch) return null;
    return {
      conversationId,
      forkId: activeBranch.forkId,
      mode: activeBranch.mode,
      documentText: await loadConversationBranchDocument(runId, conversationId, activeBranch.forkId),
    };
  } catch {
    return null;
  }
}

export async function activeSessionInfo(runId: string): Promise<SessionMetadata> {
  const activeBranch = await loadActiveBranchDocument(runId);
  if (!activeBranch) {
    return { conversationId: null, forkId: null, mode: null, frontmatterBlock: null };
  }
  return {
    conversationId: activeBranch.conversationId,
    forkId: activeBranch.forkId,
    mode: activeBranch.mode,
    frontmatterBlock: extractFrontmatterBlock(activeBranch.documentText),
  };
}

export async function loadAgentBaseBlock(runId: string): Promise<ConversationBlock | null> {
  const activeBranch = await loadActiveBranchDocument(runId);
  if (!activeBranch) return null;
  const match = activeBranch.documentText.match(/(`{3,})chat role=system scope=agent_base\n([\s\S]*?)\n\1/);
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
      .flatMap((fork): AgentConversationBranch[] => {
        const forkId = typeof fork.id === "string" ? fork.id : null;
        if (!forkId) return [];
        const mode =
          typeof fork.mode === "string" && fork.mode.trim()
            ? fork.mode.trim()
            : forkId === active.forkId
              ? active.mode
              : null;
        const branch = {
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
        return [branch];
      });
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
