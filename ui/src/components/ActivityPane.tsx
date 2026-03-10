"use client";

import { useMemo, useState } from "react";
import { ConversationView } from "./ConversationView";
import { LogStream } from "./LogStream";
import { SuperTimeline } from "./SuperTimeline";
import { usePolling } from "@/lib/hooks";
import type { AgentConversationBranch } from "@/lib/types";

interface ActivityPaneProps {
  runId: string;
}

type ActivityTab = "agent" | "supervisor" | "super" | "logs";

const ACTIVITY_TABS: { id: ActivityTab; label: string }[] = [
  { id: "agent", label: "Agent" },
  { id: "supervisor", label: "Supervisor" },
  { id: "super", label: "Super" },
  { id: "logs", label: "Logs" },
];

export function ActivityPane({ runId }: ActivityPaneProps) {
  const [activeTab, setActiveTab] = useState<ActivityTab>("agent");
  const [requestedAgentBranchKey, setRequestedAgentBranchKey] = useState<string | null>(null);
  const { data: logStats } = usePolling<{
    errorCount: number;
    warningCount: number;
  }>(`/api/runs/${runId}/logs?tail=300`, 3000, {
    errorCount: 0,
    warningCount: 0,
  });
  const { data: agentBranches } = usePolling<{ branches: AgentConversationBranch[] }>(
    `/api/runs/${runId}/conversation/agent/branches`,
    5000,
    { branches: [] }
  );
  const activeAgentBranchKey = useMemo(() => {
    const branches = agentBranches.branches;
    if (branches.length === 0) return null;
    if (requestedAgentBranchKey && branches.some((branch) => branch.key === requestedAgentBranchKey)) {
      return requestedAgentBranchKey;
    }
    const activeBranch = branches.find((branch) => branch.active);
    return activeBranch?.key ?? branches.at(-1)?.key ?? null;
  }, [agentBranches.branches, requestedAgentBranchKey]);

  return (
    <aside className="w-[45rem] shrink-0 border-l border-zinc-800 bg-zinc-950/40 flex flex-col min-h-0">
      <div className="flex border-b border-zinc-800 shrink-0">
        {ACTIVITY_TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex items-center gap-2 px-4 py-2 text-xs font-medium transition-colors ${
              activeTab === tab.id
                ? "text-zinc-100 border-b-2 border-emerald-500"
                : "text-zinc-500 hover:text-zinc-300"
            }`}
          >
            <span>{tab.label}</span>
            {tab.id === "logs" && logStats.errorCount > 0 ? (
              <span className="rounded-full border border-red-800 bg-red-950/70 px-1.5 py-0.5 text-[10px] font-semibold text-red-300">
                {logStats.errorCount}E
              </span>
            ) : null}
            {tab.id === "logs" && logStats.warningCount > 0 ? (
              <span className="rounded-full border border-yellow-800 bg-yellow-950/60 px-1.5 py-0.5 text-[10px] font-semibold text-yellow-300">
                {logStats.warningCount}W
              </span>
            ) : null}
          </button>
        ))}
      </div>
      {activeTab === "agent" && agentBranches.branches.length > 0 ? (
        <div className="flex gap-1 overflow-x-auto border-b border-zinc-800 px-2 py-2 shrink-0 bg-zinc-950/70">
          {agentBranches.branches.map((branch) => (
            <button
              key={branch.key}
              onClick={() => setRequestedAgentBranchKey(branch.key)}
              className={`shrink-0 rounded-full border px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.12em] transition-colors ${
                activeAgentBranchKey === branch.key
                  ? "border-emerald-700 bg-emerald-950/50 text-emerald-200"
                  : "border-zinc-800 bg-zinc-900 text-zinc-400 hover:border-zinc-700 hover:text-zinc-200"
              }`}
              title={`${branch.mode || "unknown"} · ${branch.createdAt}`}
            >
              {branch.label}
            </button>
          ))}
        </div>
      ) : null}
      <div className="flex-1 min-h-0">
        {activeTab === "agent" && (
          <ConversationView
            runId={runId}
            source="agent"
            branchKey={activeAgentBranchKey}
          />
        )}
        {activeTab === "supervisor" && <ConversationView runId={runId} source="supervisor" />}
        {activeTab === "super" && <SuperTimeline runId={runId} />}
        {activeTab === "logs" && <LogStream runId={runId} />}
      </div>
    </aside>
  );
}
