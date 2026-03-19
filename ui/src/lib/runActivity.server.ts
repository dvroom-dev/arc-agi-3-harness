import { listAgentConversationBranches } from "@/lib/agentConversation.server";
import { findConversationId } from "@/lib/agentConversationData.server";
import { readLogFeed } from "@/lib/logFeed.server";
import { runDir } from "@/lib/paths";
import fs from "fs/promises";
import path from "path";
import type {
  AgentConversationBranch,
  RunActivitySummary,
} from "@/lib/types";

interface ConversationIndexForkRecord {
  actionSummary?: unknown;
  providerName?: unknown;
  supervisorProviderName?: unknown;
  model?: unknown;
  supervisorModel?: unknown;
}

async function readSupervisorSummary(runId: string): Promise<{
  runtime: RunActivitySummary["runtime"];
  status: RunActivitySummary["supervisor"]["status"];
}> {
  const conversationId = await findConversationId(runId);
  if (!conversationId) {
    return {
      runtime: {
        agentProvider: null,
        agentModel: null,
        supervisorProvider: null,
        supervisorModel: null,
      },
      status: "disabled",
    };
  }

  const conversationDir = path.join(
    runDir(runId),
    ".ai-supervisor",
    "conversations",
    conversationId
  );

  const [indexPayload, reviewNames] = await Promise.all([
    fs.readFile(path.join(conversationDir, "index.json"), "utf-8").catch(() => null),
    fs.readdir(path.join(conversationDir, "reviews")).catch(() => []),
  ]);

  const forks = indexPayload
    ? ((JSON.parse(indexPayload) as { forks?: ConversationIndexForkRecord[] }).forks ?? [])
    : [];
  const latestStart = [...forks].reverse().find(
    (fork) => typeof fork.actionSummary === "string" && fork.actionSummary === "supervise:start"
  );
  const latestSupervisorFork = [...forks].reverse().find(
    (fork) =>
      typeof fork.supervisorModel === "string" &&
      Boolean(String(fork.supervisorModel).trim())
  );

  const prompts = new Set(
    reviewNames
      .map((name) => name.match(/^(review_[^_]+(?:-[^_]+)*)_prompt\.txt$/)?.[1] ?? null)
      .filter((value): value is string => Boolean(value))
  );
  const responses = new Set(
    reviewNames
      .map((name) => name.match(/^(review_[^_]+(?:-[^_]+)*)_response\.txt$/)?.[1] ?? null)
      .filter((value): value is string => Boolean(value))
  );
  const hasPendingReview = [...prompts].some((reviewId) => !responses.has(reviewId));

  return {
    runtime: {
      agentProvider:
        typeof latestStart?.providerName === "string" ? latestStart.providerName : null,
      agentModel:
        typeof latestStart?.model === "string" ? latestStart.model : null,
      supervisorProvider:
        typeof latestSupervisorFork?.supervisorProviderName === "string"
          ? latestSupervisorFork.supervisorProviderName
          : null,
      supervisorModel:
        typeof latestSupervisorFork?.supervisorModel === "string"
          ? latestSupervisorFork.supervisorModel
          : null,
    },
    status: hasPendingReview ? "running" : "idle",
  };
}

export async function readRunActivitySummary(
  runId: string
): Promise<RunActivitySummary> {
  let branches: AgentConversationBranch[] = [];
  let branchesError: string | null = null;
  let supervisorStatus: RunActivitySummary["supervisor"]["status"] = "disabled";
  let runtime: RunActivitySummary["runtime"] = {
    agentProvider: null,
    agentModel: null,
    supervisorProvider: null,
    supervisorModel: null,
  };

  try {
    const payload = await listAgentConversationBranches(runId);
    branches = payload.branches;
  } catch (error) {
    branchesError = error instanceof Error ? error.message : String(error);
  }

  try {
    const summary = await readSupervisorSummary(runId);
    runtime = summary.runtime;
    supervisorStatus = summary.status;
  } catch {
    supervisorStatus = "disabled";
  }

  const logs = await readLogFeed(runId, 300);

  return {
    branches,
    branchesError,
    runtime,
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
