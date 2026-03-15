"use client";

import { useEffect, useState } from "react";
import { RunList } from "@/components/RunList";
import { RunDashboard } from "@/components/RunDashboard";
import { RunLauncher } from "@/components/RunLauncher";
import { MobileRunDashboard } from "@/components/MobileRunDashboard";
import {
  DEFAULT_RUN_LAUNCH_PARAMS,
  normalizeRunLaunchParams,
  prepareImportedRunLaunchParams,
} from "@/lib/runParams";
import type { RunLaunchParams } from "@/lib/types";

function useIsDesktop() {
  const [isDesktop, setIsDesktop] = useState<boolean | null>(null);

  useEffect(() => {
    const media = window.matchMedia("(min-width: 768px)");
    const update = () => setIsDesktop(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);

  return isDesktop;
}

export default function Home() {
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [launchParams, setLaunchParams] = useState<RunLaunchParams | null>(null);
  const [refreshToken, setRefreshToken] = useState(0);
  const isDesktop = useIsDesktop();

  useEffect(() => {
    fetch("/api/launcher")
      .then((r) => r.json())
      .then((payload) => setLaunchParams(normalizeRunLaunchParams(payload.recentParams)))
      .catch(() => setLaunchParams(DEFAULT_RUN_LAUNCH_PARAMS));
  }, []);

  if (isDesktop === null) {
    return <div className="h-dvh overflow-hidden bg-zinc-950" />;
  }

  if (!isDesktop) {
    return (
      <div className="h-dvh overflow-hidden bg-zinc-950 pt-[env(safe-area-inset-top)] pb-[env(safe-area-inset-bottom)]">
        <div className="flex h-full overflow-hidden">
          {selectedRunId ? (
            <MobileRunDashboard
              key={`mobile:${selectedRunId}`}
              runId={selectedRunId}
              onBack={() => setSelectedRunId(null)}
              onRunStopped={() => setRefreshToken((value) => value + 1)}
            />
          ) : (
            <div className="flex h-full w-full flex-col">
              <div className="border-b border-zinc-800 px-3 py-3">
                <h1 className="text-sm font-bold tracking-wide text-zinc-300">
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
              <div className="min-h-0 flex-1">
                <RunList
                  selectedRunId={selectedRunId}
                  onSelectRun={setSelectedRunId}
                  onImportParams={(params) => setLaunchParams(prepareImportedRunLaunchParams(params))}
                  onContinueRun={(runId) => {
                    setRefreshToken((value) => value + 1);
                    setSelectedRunId(runId);
                  }}
                  refreshToken={refreshToken}
                />
              </div>
            </div>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="h-dvh overflow-hidden bg-zinc-950">
      <div className="flex h-full overflow-hidden">
        <div className="flex w-64 shrink-0 flex-col border-r border-zinc-800 bg-zinc-950">
          <div className="border-b border-zinc-800 px-3 py-2">
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
            onContinueRun={(runId) => {
              setRefreshToken((value) => value + 1);
              setSelectedRunId(runId);
            }}
            refreshToken={refreshToken}
          />
        </div>

        <div className="min-h-0 min-w-0 flex-1 overflow-hidden">
          {selectedRunId ? (
            <RunDashboard
              key={selectedRunId}
              runId={selectedRunId}
              onRunStopped={() => setRefreshToken((value) => value + 1)}
            />
          ) : (
            <div className="flex h-full items-center justify-center text-zinc-600">
              <div className="text-center">
                <div className="mb-2 text-lg">Select a run</div>
                <div className="text-sm">
                  Choose a run from the sidebar to view its progress
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
