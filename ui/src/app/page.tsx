"use client";

import { useEffect, useState } from "react";
import { RunList } from "@/components/RunList";
import { RunDashboard } from "@/components/RunDashboard";
import { RunLauncher } from "@/components/RunLauncher";
import {
  DEFAULT_RUN_LAUNCH_PARAMS,
  normalizeRunLaunchParams,
  prepareImportedRunLaunchParams,
} from "@/lib/runParams";
import type { RunLaunchParams } from "@/lib/types";

export default function Home() {
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [launchParams, setLaunchParams] = useState<RunLaunchParams | null>(null);
  const [refreshToken, setRefreshToken] = useState(0);

  useEffect(() => {
    fetch("/api/launcher")
      .then((r) => r.json())
      .then((payload) => setLaunchParams(normalizeRunLaunchParams(payload.recentParams)))
      .catch(() => setLaunchParams(DEFAULT_RUN_LAUNCH_PARAMS));
  }, []);

  return (
    <div className="flex h-screen overflow-hidden">
      {/* Left sidebar: run list */}
      <div className="w-64 border-r border-zinc-800 bg-zinc-950 flex flex-col shrink-0">
        <div className="px-3 py-2 border-b border-zinc-800">
          <h1 className="text-sm font-bold text-zinc-300 tracking-wide">
            ARC-AGI Harness
          </h1>
          <p className="text-xs text-zinc-600">Run Monitor</p>
          <RunLauncher
            params={launchParams}
            onChange={setLaunchParams}
            onStarted={(runIds) => {
              setRefreshToken((value) => value + 1);
              if (runIds[0]) {
                setSelectedRunId(runIds[0]);
              }
            }}
          />
        </div>
        <RunList
          selectedRunId={selectedRunId}
          onSelectRun={setSelectedRunId}
          onImportParams={(params) => setLaunchParams(prepareImportedRunLaunchParams(params))}
          refreshToken={refreshToken}
        />
      </div>

      {/* Main content */}
      <div className="flex-1 min-w-0 min-h-0 overflow-hidden">
        {selectedRunId ? (
          <RunDashboard key={selectedRunId} runId={selectedRunId} />
        ) : (
          <div className="flex items-center justify-center h-full text-zinc-600">
            <div className="text-center">
              <div className="text-lg mb-2">Select a run</div>
              <div className="text-sm">
                Choose a run from the sidebar to view its progress
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
