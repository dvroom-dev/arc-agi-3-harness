"use client";

import { useState } from "react";
import { GameView } from "./GameView";
import { TimelineView } from "./TimelineView";
import { SequencePlayer } from "./SequencePlayer";
import { LogStream } from "./LogStream";
import { FileTree } from "./FileTree";
import { FileViewer } from "./FileViewer";
import { ConversationView } from "./ConversationView";
import { HistoryTable } from "./HistoryTable";
import { ScoreView } from "./ScoreView";

interface RunDashboardProps {
  runId: string;
}

type Tab = "timeline" | "scores" | "sequences" | "conversation" | "logs" | "files" | "history";

const TABS: { id: Tab; label: string }[] = [
  { id: "timeline", label: "Timeline" },
  { id: "scores", label: "Scores" },
  { id: "sequences", label: "Sequences" },
  { id: "conversation", label: "Conversation" },
  { id: "logs", label: "Logs" },
  { id: "files", label: "Files" },
  { id: "history", label: "History" },
];

export function RunDashboard({ runId }: RunDashboardProps) {
  const [activeTab, setActiveTab] = useState<Tab>("timeline");
  const [selectedFile, setSelectedFile] = useState<string | null>(null);

  return (
    <div className="flex flex-col h-full">
      {/* Game state header */}
      <div className="px-4 py-3 border-b border-zinc-800 shrink-0">
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

      {/* Tab content */}
      <div className="flex-1 min-h-0">
        {activeTab === "timeline" && <TimelineView runId={runId} />}
        {activeTab === "scores" && <ScoreView runId={runId} />}
        {activeTab === "sequences" && <SequencePlayer runId={runId} />}
        {activeTab === "conversation" && <ConversationView runId={runId} />}
        {activeTab === "logs" && <LogStream runId={runId} />}
        {activeTab === "files" && (
          <div className="flex h-full">
            <div className="w-52 border-r border-zinc-800 overflow-y-auto">
              <FileTree
                runId={runId}
                onSelectFile={setSelectedFile}
                selectedPath={selectedFile}
              />
            </div>
            <div className="flex-1">
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
  );
}
