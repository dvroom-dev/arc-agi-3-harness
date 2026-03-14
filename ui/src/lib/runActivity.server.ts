import { listAgentConversationBranches } from "@/lib/agentConversation.server";
import { readLogFeed } from "@/lib/logFeed.server";
import { buildSuperTimeline } from "@/lib/superTimeline.server";
import type { AgentConversationBranch, RunActivitySummary } from "@/lib/types";

export async function readRunActivitySummary(
  runId: string
): Promise<RunActivitySummary> {
  let branches: AgentConversationBranch[] = [];
  let branchesError: string | null = null;
  let supervisorStatus: RunActivitySummary["supervisor"]["status"] = "disabled";

  try {
    const payload = await listAgentConversationBranches(runId);
    branches = payload.branches;
  } catch (error) {
    branchesError = error instanceof Error ? error.message : String(error);
  }

  try {
    const timeline = await buildSuperTimeline(runId);
    supervisorStatus = timeline.active
      ? "running"
      : timeline.conversationId
        ? "idle"
        : "disabled";
  } catch {
    supervisorStatus = "disabled";
  }

  const logs = await readLogFeed(runId, 300);

  return {
    branches,
    branchesError,
    supervisor: {
      status: supervisorStatus,
    },
    logs: {
      errorCount: logs.errorCount,
      warningCount: logs.warningCount,
      harnessFile: logs.streams.find((stream) => stream.id === "harness")?.file ?? null,
      rawEventFile: logs.streams.find((stream) => stream.id === "super_raw")?.file ?? null,
    },
  };
}
