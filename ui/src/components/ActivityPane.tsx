"use client";

import { useState } from "react";
import { ConversationView } from "./ConversationView";
import { LogStream } from "./LogStream";
import { SuperTimeline } from "./SuperTimeline";
import { useAgentBranchSelection, useRunActivitySummary } from "@/lib/runActivityHooks";

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
  const {
    data: activity,
    error: activityError,
  } = useRunActivitySummary(runId);
  const {
    activeBranchKey: activeAgentBranchKey,
    setRequestedBranchKey: setRequestedAgentBranchKey,
  } = useAgentBranchSelection(activity.branches);
  const activeHeadBranch = activity.branches.find((branch) => branch.active) ?? null;
  const supervisorBadge =
    activity.supervisor.status === "running"
      ? {
          label: "Running",
          className: "border-sky-800 bg-sky-950/60 text-sky-300",
        }
      : activity.supervisor.status === "idle"
        ? {
            label: "Idle",
            className: "border-zinc-700 bg-zinc-900 text-zinc-400",
          }
        : {
            label: "Disabled",
            className: "border-zinc-800 bg-zinc-950/70 text-zinc-600",
          };

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
            {tab.id === "agent" && activeHeadBranch ? (
              <span className="rounded-full border border-emerald-800 bg-emerald-950/60 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-300">
                Head: {activeHeadBranch.label}
              </span>
            ) : null}
            {tab.id === "supervisor" ? (
              <span className={`rounded-full border px-1.5 py-0.5 text-[10px] font-semibold ${supervisorBadge.className}`}>
                {supervisorBadge.label}
              </span>
            ) : null}
            {tab.id === "logs" && activity.logs.errorCount > 0 ? (
              <span className="rounded-full border border-red-800 bg-red-950/70 px-1.5 py-0.5 text-[10px] font-semibold text-red-300">
                {activity.logs.errorCount}E
              </span>
            ) : null}
            {tab.id === "logs" && activity.logs.warningCount > 0 ? (
              <span className="rounded-full border border-yellow-800 bg-yellow-950/60 px-1.5 py-0.5 text-[10px] font-semibold text-yellow-300">
                {activity.logs.warningCount}W
              </span>
            ) : null}
          </button>
        ))}
      </div>
      {activeTab === "agent" && activity.branches.length > 0 ? (
        <div className="flex gap-1 overflow-x-auto border-b border-zinc-800 px-2 py-2 shrink-0 bg-zinc-950/70">
          {activity.branches.map((branch) => (
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
              <span className="flex items-center gap-2">
                <span>{branch.label}</span>
                {branch.active ? (
                  <span className="rounded-full border border-emerald-700/70 bg-emerald-950/80 px-1.5 py-0.5 text-[9px] font-semibold text-emerald-300">
                    Head
                  </span>
                ) : null}
              </span>
            </button>
          ))}
        </div>
      ) : null}
      {activity.branchesError || activityError ? (
        <div className="border-b border-zinc-800 px-3 py-2 text-xs text-amber-300">
          Activity summary warning: {activity.branchesError || activityError}
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
        {activeTab === "supervisor" && (
          <ConversationView runId={runId} source="supervisor" />
        )}
        {activeTab === "super" && <SuperTimeline runId={runId} />}
        {activeTab === "logs" && <LogStream runId={runId} />}
      </div>
    </aside>
  );
}
