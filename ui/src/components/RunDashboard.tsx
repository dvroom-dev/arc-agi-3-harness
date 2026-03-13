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
import { useStopRun } from "@/lib/runActivityHooks";

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
  const { stopping, stopMessage, stopRun } = useStopRun(runId, onRunStopped);

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
              {stopMessage && (
                <div className="mt-1 text-xs text-zinc-500">{stopMessage}</div>
              )}
            </div>
            <button
              type="button"
              onClick={stopRun}
              disabled={stopping}
              className="shrink-0 rounded border border-red-800 bg-red-950/40 px-3 py-1.5 text-xs font-medium text-red-200 transition-colors hover:border-red-700 hover:bg-red-950/70 disabled:cursor-wait disabled:border-zinc-800 disabled:bg-zinc-900 disabled:text-zinc-500"
            >
              {stopping ? "Stopping..." : "Stop Run"}
            </button>
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
