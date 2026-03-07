"use client";

import { useEffect, useState } from "react";
import type { RunLaunchParams, RunSummary } from "@/lib/types";

interface RunListProps {
  selectedRunId: string | null;
  onSelectRun: (runId: string) => void;
  onImportParams: (params: RunLaunchParams) => void;
  refreshToken: number;
}

function stateColor(state: string): string {
  switch (state) {
    case "WIN":
      return "text-green-400";
    case "NOT_FINISHED":
      return "text-yellow-400";
    case "STOPPED":
      return "text-zinc-300";
    case "FAILED":
    case "GAME_OVER":
    case "LOSS":
      return "text-red-400";
    default:
      return "text-zinc-500";
  }
}

function stateBadge(state: string): string {
  switch (state) {
    case "WIN":
      return "bg-green-900/50 border-green-700";
    case "NOT_FINISHED":
      return "bg-yellow-900/30 border-yellow-700";
    case "STOPPED":
      return "bg-zinc-800 border-zinc-600";
    case "FAILED":
    case "GAME_OVER":
    case "LOSS":
      return "bg-red-900/30 border-red-700";
    default:
      return "bg-zinc-800 border-zinc-700";
  }
}

export function RunList({
  selectedRunId,
  onSelectRun,
  onImportParams,
  refreshToken,
}: RunListProps) {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [filter, setFilter] = useState("");

  useEffect(() => {
    const load = () =>
      fetch("/api/runs")
        .then((r) => r.json())
        .then(setRuns)
        .catch(console.error);
    load();
    const interval = setInterval(load, 10000);
    return () => clearInterval(interval);
  }, [refreshToken]);

  const filtered = runs.filter(
    (r) =>
      r.id.toLowerCase().includes(filter.toLowerCase()) ||
      r.gameId.toLowerCase().includes(filter.toLowerCase())
  );

  return (
    <div className="flex flex-col h-full">
      <div className="p-2 border-b border-zinc-800">
        <input
          type="text"
          placeholder="Filter runs..."
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="w-full bg-zinc-900 border border-zinc-700 rounded px-2 py-1 text-sm text-zinc-200 placeholder-zinc-600 focus:outline-none focus:border-zinc-500"
        />
      </div>
      <div className="flex-1 overflow-y-auto">
        {filtered.map((run) => (
          <div
            key={run.id}
            title={run.runParamsTooltip}
            className={`border-b border-zinc-800/50 transition-colors ${
              selectedRunId === run.id ? "bg-zinc-800 border-l-2 border-l-blue-500" : "hover:bg-zinc-800/50"
            }`}
          >
            <div className="flex items-start gap-2 px-2 py-2">
              <button
                onClick={() => onSelectRun(run.id)}
                className="min-w-0 flex-1 text-left"
              >
                <div className="text-xs font-mono text-zinc-300 truncate">
                  {run.id}
                </div>
                <div className="mt-1 flex items-center gap-2">
                  <span
                    className={`text-xs px-1.5 py-0.5 rounded border ${stateBadge(run.state)}`}
                  >
                    <span className={stateColor(run.state)}>{run.state}</span>
                  </span>
                  {run.gameId && (
                    <span className="text-xs text-zinc-500">{run.gameId.split("-")[0]}</span>
                  )}
                  {run.levelsCompleted > 0 && (
                    <span className="text-xs text-zinc-400">
                      L{run.levelsCompleted}/{run.totalLevels}
                    </span>
                  )}
                </div>
              </button>
              <button
                type="button"
                onClick={(event) => {
                  event.stopPropagation();
                  if (run.runParams) {
                    onImportParams(run.runParams.params);
                  }
                }}
                disabled={!run.runParams}
                title={run.runParams ? `Import parameters from ${run.id}\n${run.runParamsTooltip}` : "No parameters available"}
                className="shrink-0 rounded border border-zinc-700 px-2 py-1 text-[11px] text-zinc-400 transition-colors hover:border-zinc-500 hover:text-zinc-200 disabled:cursor-not-allowed disabled:border-zinc-800 disabled:text-zinc-700"
              >
                Use
              </button>
            </div>
          </div>
        ))}
        {filtered.length === 0 && (
          <div className="p-4 text-sm text-zinc-600 text-center">
            No runs found
          </div>
        )}
      </div>
    </div>
  );
}
