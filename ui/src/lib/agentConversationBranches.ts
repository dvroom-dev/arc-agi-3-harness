export interface BranchVisibilityCandidate {
  key?: string;
  mode: string | null;
  active: boolean;
  parentId?: string | null;
  actionSummary?: string | null;
  assistantTurns: number;
  toolCallCount: number;
  toolResultCount: number;
}

export function filterVisibleAgentBranches<T extends BranchVisibilityCandidate>(
  branches: T[]
): T[] {
  return branches.filter((branch) => {
    const actionSummary = branch.actionSummary ?? null;
    return actionSummary === "supervise:start" || branch.active;
  });
}
