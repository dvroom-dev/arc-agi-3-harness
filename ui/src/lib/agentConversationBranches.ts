import type { AgentConversationBranch } from "@/lib/types";

export interface BranchVisibilityCandidate {
  key?: string;
  mode: string | null;
  active: boolean;
  head?: boolean;
  conversationId: string;
  forkId: string;
  parentId?: string | null;
  createdAt: string;
  actionSummary?: string | null;
  assistantTurns: number;
  toolCallCount: number;
  toolResultCount: number;
  initialUserPreview: string | null;
  lastAssistantPreview: string | null;
}

export interface AgentConversationEpisode extends AgentConversationBranch {
  memberForkIds: string[];
}

function parseTime(value: string | null | undefined): number {
  const parsed = value ? Date.parse(value) : Number.NaN;
  return Number.isFinite(parsed) ? parsed : 0;
}

export function filterVisibleAgentBranches<T extends BranchVisibilityCandidate>(
  branches: T[]
): T[] {
  return branches.filter((branch) => {
    const actionSummary = branch.actionSummary ?? null;
    return actionSummary === "supervise:start" || branch.active || Boolean(branch.head);
  });
}

export function buildAgentConversationEpisodes<T extends BranchVisibilityCandidate>(
  branches: T[]
): AgentConversationEpisode[] {
  const visibleBranches = filterVisibleAgentBranches(branches).sort(
    (a, b) => parseTime(a.createdAt) - parseTime(b.createdAt)
  );

  const episodes: AgentConversationEpisode[] = [];
  const episodeByConversationMode = new Map<string, AgentConversationEpisode>();
  for (const branch of visibleBranches) {
    const mode = branch.mode?.trim() || "agent";
    const key = `${branch.conversationId}:${mode}`;
    const existing = episodeByConversationMode.get(key);

    if (!existing) {
      const episode: AgentConversationEpisode = {
        key: branch.key ?? branch.forkId,
        mode,
        label: mode,
        conversationId: branch.conversationId,
        forkId: branch.forkId,
        parentId: branch.parentId ?? null,
        createdAt: branch.createdAt,
        active: branch.active,
        actionSummary: branch.actionSummary ?? null,
        initialUserPreview: branch.initialUserPreview,
        lastAssistantPreview: branch.lastAssistantPreview,
        memberForkIds: [branch.forkId],
      };
      episodes.push(episode);
      episodeByConversationMode.set(key, episode);
      continue;
    }

    existing.active = existing.active || branch.active;
    existing.forkId = branch.forkId;
    existing.parentId = branch.parentId ?? null;
    existing.actionSummary = branch.actionSummary ?? existing.actionSummary ?? null;
    existing.lastAssistantPreview =
      branch.lastAssistantPreview || existing.lastAssistantPreview;
    existing.memberForkIds.push(branch.forkId);
  }

  const modeCounts = new Map<string, number>();
  for (const episode of episodes) {
    modeCounts.set(episode.mode ?? "agent", (modeCounts.get(episode.mode ?? "agent") ?? 0) + 1);
  }

  const seenCounts = new Map<string, number>();
  return episodes.map((episode) => {
    const mode = episode.mode ?? "agent";
    const index = (seenCounts.get(mode) ?? 0) + 1;
    seenCounts.set(mode, index);
    return {
      ...episode,
      key: `${episode.conversationId}:${mode}:${index}`,
      label: (modeCounts.get(mode) ?? 1) > 1 ? `${mode} (${index})` : mode,
    };
  });
}

export function findAgentConversationEpisode(
  episodes: AgentConversationEpisode[],
  branchKey: string
): AgentConversationEpisode | null {
  return episodes.find((episode) => episode.key === branchKey) ?? null;
}
