export interface BranchVisibilityCandidate {
  mode: string | null;
  active: boolean;
  assistantTurns: number;
  toolCallCount: number;
  toolResultCount: number;
}

export function filterVisibleAgentBranches<T extends BranchVisibilityCandidate>(
  branches: T[]
): T[] {
  const modeHasActivity = new Map<string, boolean>();
  for (const branch of branches) {
    const mode = branch.mode?.trim() || "agent";
    const hasActivity =
      branch.active ||
      branch.assistantTurns > 0 ||
      branch.toolCallCount > 0 ||
      branch.toolResultCount > 0;
    modeHasActivity.set(mode, (modeHasActivity.get(mode) ?? false) || hasActivity);
  }

  const seenSeedOnlyMode = new Set<string>();
  return branches.filter((branch) => {
    const mode = branch.mode?.trim() || "agent";
    const hasActivity =
      branch.active ||
      branch.assistantTurns > 0 ||
      branch.toolCallCount > 0 ||
      branch.toolResultCount > 0;
    if (hasActivity) return true;
    if (modeHasActivity.get(mode)) return false;
    if (seenSeedOnlyMode.has(mode)) return false;
    seenSeedOnlyMode.add(mode);
    return true;
  });
}
