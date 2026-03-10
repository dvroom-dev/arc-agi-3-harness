"use client";

import { useState } from "react";
import { GameView } from "./GameView";
import { TimelineView } from "./TimelineView";
import { ScoreView } from "./ScoreView";
import { SequencePlayer } from "./SequencePlayer";
import { FileTree } from "./FileTree";
import { FileViewer } from "./FileViewer";
import { HistoryTable } from "./HistoryTable";
import { ConversationView } from "./ConversationView";
import { SuperTimeline } from "./SuperTimeline";
import { LogStream } from "./LogStream";
import { usePolling } from "@/lib/hooks";
import type { AgentConversationBranch } from "@/lib/types";

interface MobileRunDashboardProps {
  runId: string;
  onBack: () => void;
  onRunStopped?: () => void;
}

type MobileTab =
  | "game"
  | "timeline"
  | "scores"
  | "sequences"
  | "files"
  | "history"
  | "agent"
  | "supervisor"
  | "super"
  | "logs";

const MOBILE_TABS: { id: MobileTab; label: string }[] = [
  { id: "game", label: "Game" },
  { id: "timeline", label: "Timeline" },
  { id: "scores", label: "Scores" },
  { id: "sequences", label: "Sequences" },
  { id: "files", label: "Files" },
  { id: "history", label: "History" },
  { id: "agent", label: "Agent" },
  { id: "supervisor", label: "Supervisor" },
  { id: "super", label: "Super" },
  { id: "logs", label: "Logs" },
];

export function MobileRunDashboard({
  runId,
  onBack,
  onRunStopped,
}: MobileRunDashboardProps) {
  const [activeTab, setActiveTab] = useState<MobileTab>("game");
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [stopping, setStopping] = useState(false);
  const [stopMessage, setStopMessage] = useState<string | null>(null);
  const [requestedAgentBranchKey, setRequestedAgentBranchKey] = useState<string | null>(null);
  const { data: agentBranches } = usePolling<{ branches: AgentConversationBranch[] }>(
    `/api/runs/${runId}/conversation/agent/branches`,
    5000,
    { branches: [] }
  );

  const activeAgentBranchKey = (() => {
    const branches = agentBranches.branches;
    if (branches.length === 0) return null;
    if (requestedAgentBranchKey && branches.some((branch) => branch.key === requestedAgentBranchKey)) {
      return requestedAgentBranchKey;
    }
    const activeBranch = branches.find((branch) => branch.active);
    return activeBranch?.key ?? branches.at(-1)?.key ?? null;
  })();

  async function handleStopRun() {
    setStopping(true);
    setStopMessage(null);
    try {
      const response = await fetch(`/api/runs/${runId}/stop`, { method: "POST" });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || "Failed to stop run");
      }
      if (payload.status === "not-running") {
        setStopMessage("Run is not active.");
      } else if (payload.status === "signal-sent") {
        setStopMessage("Stop signal sent.");
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

  return (
    <div className="flex h-full min-h-0 w-full min-w-0 flex-col overflow-hidden bg-zinc-950">
      <div className="w-full min-w-0 border-b border-zinc-800 px-3 py-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <button
              type="button"
              onClick={onBack}
              className="mb-2 inline-flex items-center rounded-full border border-zinc-800 bg-zinc-900 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-zinc-300"
            >
              Runs
            </button>
            <div className="text-[11px] uppercase tracking-[0.16em] text-zinc-600">
              Selected Run
            </div>
            <div className="truncate font-mono text-sm text-zinc-200">{runId}</div>
            {stopMessage ? (
              <div className="mt-1 text-xs text-zinc-500">{stopMessage}</div>
            ) : null}
          </div>
          <button
            type="button"
            onClick={handleStopRun}
            disabled={stopping}
            className="shrink-0 rounded border border-red-800 bg-red-950/40 px-3 py-1.5 text-xs font-medium text-red-200 disabled:cursor-wait disabled:border-zinc-800 disabled:bg-zinc-900 disabled:text-zinc-500"
          >
            {stopping ? "Stopping..." : "Stop"}
          </button>
        </div>
      </div>

      <div className="w-full min-w-0 border-b border-zinc-800 bg-zinc-950/80">
        <div className="w-full min-w-0 overflow-x-auto overscroll-x-contain [scrollbar-width:none] [-ms-overflow-style:none] [&::-webkit-scrollbar]:hidden touch-pan-x">
          <div className="flex w-max min-w-full gap-2 px-3 py-2">
          {MOBILE_TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => setActiveTab(tab.id)}
              className={`shrink-0 rounded-full border px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.12em] transition-colors ${
                activeTab === tab.id
                  ? "border-blue-700 bg-blue-950/40 text-blue-100"
                  : "border-zinc-800 bg-zinc-900 text-zinc-400"
              }`}
            >
              {tab.label}
            </button>
          ))}
          </div>
        </div>
        {activeTab === "agent" && agentBranches.branches.length > 0 ? (
          <div className="w-full min-w-0 overflow-x-auto overscroll-x-contain border-t border-zinc-900 [scrollbar-width:none] [-ms-overflow-style:none] [&::-webkit-scrollbar]:hidden touch-pan-x">
            <div className="flex w-max min-w-full gap-2 px-3 py-2">
              {agentBranches.branches.map((branch) => (
                <button
                  key={branch.key}
                  type="button"
                  onClick={() => setRequestedAgentBranchKey(branch.key)}
                  className={`shrink-0 rounded-full border px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.12em] ${
                    activeAgentBranchKey === branch.key
                      ? "border-emerald-700 bg-emerald-950/50 text-emerald-200"
                      : "border-zinc-800 bg-zinc-900 text-zinc-400"
                  }`}
                >
                  {branch.label}
                </button>
              ))}
            </div>
          </div>
        ) : null}
      </div>

      <div className="min-h-0 w-full min-w-0 flex-1 overflow-x-hidden overflow-y-auto">
        {activeTab === "game" ? (
          <div className="space-y-4 overflow-x-auto p-3">
            <GameView runId={runId} />
          </div>
        ) : null}
        {activeTab === "timeline" ? <TimelineView runId={runId} /> : null}
        {activeTab === "scores" ? <ScoreView runId={runId} /> : null}
        {activeTab === "sequences" ? <SequencePlayer runId={runId} /> : null}
        {activeTab === "files" ? (
          <div className="flex min-h-full flex-col">
            <div className="max-h-64 shrink-0 overflow-y-auto border-b border-zinc-800">
              <FileTree
                runId={runId}
                onSelectFile={setSelectedFile}
                selectedPath={selectedFile}
              />
            </div>
            <div className="min-h-0 flex-1">
              <FileViewer
                key={`${runId}:${selectedFile ?? "none"}:mobile`}
                runId={runId}
                filePath={selectedFile}
              />
            </div>
          </div>
        ) : null}
        {activeTab === "history" ? <HistoryTable runId={runId} /> : null}
        {activeTab === "agent" ? (
          <ConversationView runId={runId} source="agent" branchKey={activeAgentBranchKey} />
        ) : null}
        {activeTab === "supervisor" ? <ConversationView runId={runId} source="supervisor" /> : null}
        {activeTab === "super" ? <SuperTimeline runId={runId} /> : null}
        {activeTab === "logs" ? <LogStream runId={runId} /> : null}
      </div>
    </div>
  );
}
