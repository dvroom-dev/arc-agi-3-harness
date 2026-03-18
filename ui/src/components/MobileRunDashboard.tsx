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
import {
  useAgentBranchSelection,
  useContinueRun,
  useRunActivitySummary,
  useRunStatusSummary,
  useStopRun,
} from "@/lib/runActivityHooks";
import type { RunStatusSummary } from "@/lib/types";

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
  const { data: activity } = useRunActivitySummary(runId);
  const { data: runStatus } = useRunStatusSummary(runId);
  const {
    activeBranchKey: activeAgentBranchKey,
    setRequestedBranchKey: setRequestedAgentBranchKey,
  } = useAgentBranchSelection(activity.branches);
  const { stopping, stopMessage, stopRun } = useStopRun(runId, onRunStopped);
  const { continuing, continueMessage, continueRun } = useContinueRun(runId, onRunStopped);
  const actionMessage = continueMessage || stopMessage;
  const actionPending = stopping || continuing;
  const showFailureCategoryBadge =
    runStatus.category === "provider_error" || runStatus.category === "harness_error";
  const statusBadge = mobileStatusBadgeTone(runStatus);
  const categoryBadge = mobileCategoryBadgeTone(runStatus);
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
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <span
                className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.14em] ${statusBadge}`}
              >
                {runStatus.statusLabel}
              </span>
              {showFailureCategoryBadge ? (
                <span
                  className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.14em] ${categoryBadge}`}
                >
                  {runStatus.categoryLabel}
                </span>
              ) : null}
            </div>
            {runStatus.detail ? (
              <div className="mt-2 text-xs text-zinc-400">{runStatus.detail}</div>
            ) : null}
            {actionMessage ? (
              <div className="mt-1 text-xs text-zinc-500">{actionMessage}</div>
            ) : null}
          </div>
          {runStatus.action === "stop" ? (
            <button
              type="button"
              onClick={stopRun}
              disabled={actionPending}
              className="shrink-0 rounded border border-red-800 bg-red-950/40 px-3 py-1.5 text-xs font-medium text-red-200 disabled:cursor-wait disabled:border-zinc-800 disabled:bg-zinc-900 disabled:text-zinc-500"
            >
              {stopping ? "Stopping..." : "Stop"}
            </button>
          ) : null}
          {runStatus.action === "continue" ? (
            <button
              type="button"
              onClick={continueRun}
              disabled={actionPending}
              className="shrink-0 rounded border border-emerald-800 bg-emerald-950/40 px-3 py-1.5 text-xs font-medium text-emerald-200 disabled:cursor-wait disabled:border-zinc-800 disabled:bg-zinc-900 disabled:text-zinc-500"
            >
              {continuing ? "Continuing..." : "Continue"}
            </button>
          ) : null}
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
              <span className="flex items-center gap-2">
                <span>{tab.label}</span>
                {tab.id === "agent" && activeHeadBranch ? (
                  <span className="rounded-full border border-emerald-800 bg-emerald-950/60 px-1.5 py-0.5 text-[9px] font-semibold text-emerald-300">
                    Head: {activeHeadBranch.label}
                  </span>
                ) : null}
                {tab.id === "supervisor" ? (
                  <span className={`rounded-full border px-1.5 py-0.5 text-[9px] font-semibold ${supervisorBadge.className}`}>
                    {supervisorBadge.label}
                  </span>
                ) : null}
              </span>
            </button>
          ))}
          </div>
        </div>
        {activeTab === "agent" && activity.branches.length > 0 ? (
          <div className="w-full min-w-0 overflow-x-auto overscroll-x-contain border-t border-zinc-900 [scrollbar-width:none] [-ms-overflow-style:none] [&::-webkit-scrollbar]:hidden touch-pan-x">
            <div className="flex w-max min-w-full gap-2 px-3 py-2">
              {activity.branches.map((branch) => (
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
        {activeTab === "supervisor" ? (
          <ConversationView runId={runId} source="supervisor" />
        ) : null}
        {activeTab === "super" ? <SuperTimeline runId={runId} /> : null}
        {activeTab === "logs" ? <LogStream runId={runId} /> : null}
      </div>
    </div>
  );
}

function mobileStatusBadgeTone(runStatus: RunStatusSummary) {
  switch (runStatus.category) {
    case "running":
      return "border-sky-800 bg-sky-950/60 text-sky-300";
    case "success":
      return "border-emerald-800 bg-emerald-950/60 text-emerald-300";
    case "provider_error":
    case "harness_error":
    case "game_over":
    case "loss":
      return "border-red-800 bg-red-950/50 text-red-300";
    case "stopped":
      return "border-zinc-700 bg-zinc-900 text-zinc-300";
    default:
      return "border-zinc-800 bg-zinc-950/70 text-zinc-400";
  }
}

function mobileCategoryBadgeTone(runStatus: RunStatusSummary) {
  switch (runStatus.category) {
    case "provider_error":
      return "border-amber-800 bg-amber-950/50 text-amber-300";
    case "harness_error":
      return "border-rose-800 bg-rose-950/50 text-rose-300";
    default:
      return "border-zinc-700 bg-zinc-900 text-zinc-300";
  }
}
