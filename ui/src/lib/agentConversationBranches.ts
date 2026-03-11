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
  const branchByKey = new Map(
    branches
      .filter((branch): branch is T & { key: string } => typeof branch.key === "string" && branch.key.length > 0)
      .map((branch) => [branch.key, branch])
  );
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
    const isCheckpointOnly =
      !hasActivity && (branch.actionSummary === "mode checkpoint" || branch.actionSummary === "continue (hard)");
    if (isCheckpointOnly) return false;
    const childStartBranch = typeof branch.key === "string"
      ? branches.find((candidate) =>
          candidate.parentId === branch.key &&
          (candidate.mode?.trim() || "agent") === mode &&
          candidate.actionSummary === "supervise:start" &&
          (candidate.assistantTurns > 0 ||
            candidate.toolCallCount > 0 ||
            candidate.toolResultCount > 0)
        )
      : null;
    const isForkShellOnly =
      !hasActivity &&
      branch.actionSummary === "fork (hard)" &&
      childStartBranch !== null &&
      branchByKey.has(childStartBranch.key as string);
    if (isForkShellOnly) return false;
    if (hasActivity) return true;
    if (modeHasActivity.get(mode)) return false;
    if (seenSeedOnlyMode.has(mode)) return false;
    seenSeedOnlyMode.add(mode);
    return true;
  });
}
