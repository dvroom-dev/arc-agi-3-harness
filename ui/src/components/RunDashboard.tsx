"use client";

import { useState } from "react";
import { ActivityPane } from "./ActivityPane";
import { GameView } from "./GameView";
import { TimelineView } from "./TimelineView";
import { SequencePlayer } from "./SequencePlayer";
import { FileTree } from "./FileTree";
import { FileViewer } from "./FileViewer";
import { HistoryTable } from "./HistoryTable";
import { ScoreView } from "./ScoreView";
import { useContinueRun, useRunStatusSummary, useStopRun } from "@/lib/runActivityHooks";
import type { RunStatusSummary } from "@/lib/types";

interface RunDashboardProps {
  runId: string;
  onRunStopped?: () => void;
}

type Tab = "timeline" | "scores" | "sequences" | "files" | "history";

const TABS: { id: Tab; label: string }[] = [
  { id: "timeline", label: "Timeline" },
  { id: "scores", label: "Scores" },
  { id: "sequences", label: "Sequences" },
  { id: "files", label: "Files" },
  { id: "history", label: "History" },
];

export function RunDashboard({ runId, onRunStopped }: RunDashboardProps) {
  const [activeTab, setActiveTab] = useState<Tab>("timeline");
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const { data: runStatus } = useRunStatusSummary(runId);
  const { stopping, stopMessage, stopRun } = useStopRun(runId, onRunStopped);
  const { continuing, continueMessage, continueRun } = useContinueRun(runId, onRunStopped);
  const actionMessage = continueMessage || stopMessage;
  const actionPending = stopping || continuing;
  const showFailureCategoryBadge =
    runStatus.category === "provider_error" || runStatus.category === "harness_error";
  const statusBadge = statusBadgeTone(runStatus);
  const categoryBadge = categoryBadgeTone(runStatus);

  return (
    <div className="flex h-full min-h-0 min-w-0">
      <div className="flex-1 min-h-0 min-w-0 flex flex-col">
        {/* Game state header */}
        <div className="px-4 py-3 border-b border-zinc-800 shrink-0">
          <div className="mb-3 flex items-start justify-between gap-4">
            <div className="min-w-0">
              <div className="text-[11px] uppercase tracking-[0.18em] text-zinc-600">
                Selected Run
              </div>
              <div className="truncate font-mono text-sm text-zinc-200">
                {runId}
              </div>
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
                <div className="mt-2 max-w-3xl text-xs text-zinc-400">{runStatus.detail}</div>
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
                className="shrink-0 rounded border border-red-800 bg-red-950/40 px-3 py-1.5 text-xs font-medium text-red-200 transition-colors hover:border-red-700 hover:bg-red-950/70 disabled:cursor-wait disabled:border-zinc-800 disabled:bg-zinc-900 disabled:text-zinc-500"
              >
                {stopping ? "Stopping..." : "Stop Run"}
              </button>
            ) : null}
            {runStatus.action === "continue" ? (
              <button
                type="button"
                onClick={continueRun}
                disabled={actionPending}
                className="shrink-0 rounded border border-emerald-800 bg-emerald-950/40 px-3 py-1.5 text-xs font-medium text-emerald-200 transition-colors hover:border-emerald-700 hover:bg-emerald-950/70 disabled:cursor-wait disabled:border-zinc-800 disabled:bg-zinc-900 disabled:text-zinc-500"
              >
                {continuing ? "Continuing..." : "Continue"}
              </button>
            ) : null}
          </div>
          <GameView runId={runId} />
        </div>

        {/* Tab bar */}
        <div className="flex border-b border-zinc-800 shrink-0">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`px-4 py-2 text-xs font-medium transition-colors ${
                activeTab === tab.id
                  ? "text-zinc-100 border-b-2 border-blue-500"
                  : "text-zinc-500 hover:text-zinc-300"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Main content */}
        <div className="flex-1 min-h-0 min-w-0">
          {activeTab === "timeline" && <TimelineView runId={runId} />}
          {activeTab === "scores" && <ScoreView runId={runId} />}
          {activeTab === "sequences" && <SequencePlayer runId={runId} />}
          {activeTab === "files" && (
            <div className="flex h-full min-w-0">
              <div className="w-52 border-r border-zinc-800 overflow-y-auto shrink-0">
                <FileTree
                  runId={runId}
                  onSelectFile={setSelectedFile}
                  selectedPath={selectedFile}
                />
              </div>
              <div className="flex-1 min-w-0">
                <FileViewer
                  key={`${runId}:${selectedFile ?? "none"}`}
                  runId={runId}
                  filePath={selectedFile}
                />
              </div>
            </div>
          )}
          {activeTab === "history" && <HistoryTable runId={runId} />}
        </div>
      </div>
      <ActivityPane key={runId} runId={runId} />
    </div>
  );
}

function statusBadgeTone(runStatus: RunStatusSummary) {
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

function categoryBadgeTone(runStatus: RunStatusSummary) {
  switch (runStatus.category) {
    case "provider_error":
      return "border-amber-800 bg-amber-950/50 text-amber-300";
    case "harness_error":
      return "border-rose-800 bg-rose-950/50 text-rose-300";
    default:
      return "border-zinc-700 bg-zinc-900 text-zinc-300";
  }
}
