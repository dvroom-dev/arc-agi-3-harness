"use client";

import { useMemo, useState } from "react";
import { usePolling } from "@/lib/hooks";
import type { AgentConversationBranch, RunActivitySummary } from "@/lib/types";

const EMPTY_ACTIVITY_SUMMARY: RunActivitySummary = {
  branches: [],
  branchesError: null,
  supervisor: {
    status: "disabled",
  },
  logs: {
    errorCount: 0,
    warningCount: 0,
    harnessFile: null,
    rawEventFile: null,
  },
};

export function useRunActivitySummary(runId: string) {
  return usePolling<RunActivitySummary>(
    `/api/runs/${runId}/activity`,
    5000,
    EMPTY_ACTIVITY_SUMMARY
  );
}

export function useAgentBranchSelection(branches: AgentConversationBranch[]) {
  const [requestedBranchKey, setRequestedBranchKey] = useState<string | null>(null);

  const activeBranchKey = useMemo(() => {
    if (branches.length === 0) return null;
    if (requestedBranchKey && branches.some((branch) => branch.key === requestedBranchKey)) {
      return requestedBranchKey;
    }
    const activeBranch = branches.find((branch) => branch.active);
    return activeBranch?.key ?? branches.at(-1)?.key ?? null;
  }, [branches, requestedBranchKey]);

  return {
    requestedBranchKey,
    setRequestedBranchKey,
    activeBranchKey,
  };
}

export function useStopRun(
  runId: string,
  onRunStopped?: () => void
) {
  const [stopping, setStopping] = useState(false);
  const [stopMessage, setStopMessage] = useState<string | null>(null);

  async function stopRun() {
    setStopping(true);
    setStopMessage(null);
    try {
      const response = await fetch(`/api/runs/${runId}/stop`, {
        method: "POST",
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || "Failed to stop run");
      }

      if (payload.status === "not-running") {
        setStopMessage("Run is not active.");
      } else if (payload.status === "signal-sent") {
        setStopMessage("Stop signal sent. Waiting for process exit.");
      } else {
        setStopMessage("Run stopped.");
      }
      onRunStopped?.();
    } catch (error) {
      setStopMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setStopping(false);
    }
  }

  return {
    stopping,
    stopMessage,
    stopRun,
  };
}
