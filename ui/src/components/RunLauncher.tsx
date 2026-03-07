"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  DEFAULT_RUN_LAUNCH_PARAMS,
  normalizeRunLaunchParams,
  summarizeRunLaunchParams,
  type RunLaunchParams,
} from "@/lib/runParams";

interface RunLauncherProps {
  params: RunLaunchParams | null;
  onChange: (params: RunLaunchParams) => void;
  onStarted: (runIds: string[]) => void;
}

function FieldLabel({ children }: { children: React.ReactNode }) {
  return <label className="text-[11px] uppercase tracking-wide text-zinc-500">{children}</label>;
}

function CheckboxField({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (next: boolean) => void;
}) {
  return (
    <label className="flex items-center gap-2 text-xs text-zinc-300">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="h-3.5 w-3.5 rounded border-zinc-700 bg-zinc-900 text-blue-500"
      />
      <span>{label}</span>
    </label>
  );
}

export function RunLauncher({ params, onChange, onStarted }: RunLauncherProps) {
  const [open, setOpen] = useState(false);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);

  const activeParams = params ?? DEFAULT_RUN_LAUNCH_PARAMS;
  const summary = useMemo(() => summarizeRunLaunchParams(activeParams), [activeParams]);

  useEffect(() => {
    if (!open) return;
    const handlePointerDown = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handlePointerDown);
    return () => document.removeEventListener("mousedown", handlePointerDown);
  }, [open]);

  function updateParams(patch: Partial<RunLaunchParams>) {
    const next = normalizeRunLaunchParams({
      ...activeParams,
      ...patch,
    });
    onChange(next);
  }

  function updateBooleanField(key: keyof RunLaunchParams, checked: boolean) {
    const patch: Partial<RunLaunchParams> = { [key]: checked };
    if (key === "openScorecard" && checked) {
      patch.scoreAfterSolve = false;
      patch.operationMode = "ONLINE";
    }
    if (key === "scoreAfterSolve" && checked) {
      patch.openScorecard = false;
      patch.scorecardId = "";
      patch.operationMode = "ONLINE";
    }
    if (key === "scorecardSessionPreflight" && checked) {
      patch.operationMode = "ONLINE";
    }
    updateParams(patch);
  }

  async function startRun() {
    setStarting(true);
    setError(null);
    try {
      const response = await fetch("/api/launcher", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ params: activeParams }),
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || "Failed to start run.");
      }
      const normalized = normalizeRunLaunchParams(payload.params ?? activeParams);
      onChange(normalized);
      onStarted(Array.isArray(payload.runIds) ? payload.runIds : []);
      setOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setStarting(false);
    }
  }

  return (
    <div className="mt-3 relative" ref={rootRef}>
      <div className="flex items-stretch">
        <button
          type="button"
          onClick={startRun}
          disabled={starting || !params}
          title={`Start run with current parameters\n${summary}`}
          className="flex-1 rounded-l border border-blue-500/70 bg-blue-600 px-3 py-2 text-xs font-medium text-white transition-colors hover:bg-blue-500 disabled:cursor-not-allowed disabled:bg-zinc-800 disabled:text-zinc-500"
        >
          {starting ? "Starting..." : "Start Run"}
        </button>
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          title={`Edit current parameters\n${summary}`}
          className="rounded-r border border-l-0 border-blue-500/70 bg-blue-600 px-2 text-white transition-colors hover:bg-blue-500"
        >
          ▾
        </button>
      </div>

      {open && (
        <div className="absolute left-0 right-0 z-20 mt-2 rounded-lg border border-zinc-800 bg-zinc-950 p-3 shadow-2xl">
          <div className="mb-3 rounded border border-zinc-800 bg-zinc-900/60 p-2">
            <div className="text-[11px] uppercase tracking-wide text-zinc-500">Current Params</div>
            <pre className="mt-1 whitespace-pre-wrap text-[11px] leading-relaxed text-zinc-300">
              {summary}
            </pre>
          </div>

          <div className="max-h-[70vh] space-y-3 overflow-y-auto pr-1">
            <div className="grid grid-cols-1 gap-3">
              <div>
                <FieldLabel>Game ID</FieldLabel>
                <input
                  value={activeParams.gameId}
                  onChange={(e) => updateParams({ gameId: e.target.value })}
                  className="mt-1 w-full rounded border border-zinc-700 bg-zinc-900 px-2 py-1.5 text-sm text-zinc-200"
                />
              </div>
              <div>
                <FieldLabel>Game IDs Override</FieldLabel>
                <input
                  value={activeParams.gameIds}
                  onChange={(e) => updateParams({ gameIds: e.target.value })}
                  placeholder="ls20 ft09 vc33"
                  className="mt-1 w-full rounded border border-zinc-700 bg-zinc-900 px-2 py-1.5 text-sm text-zinc-200"
                />
              </div>
              <div>
                <FieldLabel>Session Name</FieldLabel>
                <input
                  value={activeParams.sessionName}
                  onChange={(e) => updateParams({ sessionName: e.target.value })}
                  placeholder="auto timestamp"
                  className="mt-1 w-full rounded border border-zinc-700 bg-zinc-900 px-2 py-1.5 text-sm text-zinc-200"
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <FieldLabel>Operation Mode</FieldLabel>
                <select
                  value={activeParams.operationMode}
                  onChange={(e) => updateParams({ operationMode: e.target.value as RunLaunchParams["operationMode"] })}
                  className="mt-1 w-full rounded border border-zinc-700 bg-zinc-900 px-2 py-1.5 text-sm text-zinc-200"
                >
                  <option value="NORMAL">NORMAL</option>
                  <option value="ONLINE">ONLINE</option>
                  <option value="OFFLINE">OFFLINE</option>
                </select>
              </div>
              <div>
                <FieldLabel>Provider</FieldLabel>
                <select
                  value={activeParams.provider}
                  onChange={(e) => updateParams({ provider: e.target.value as RunLaunchParams["provider"] })}
                  className="mt-1 w-full rounded border border-zinc-700 bg-zinc-900 px-2 py-1.5 text-sm text-zinc-200"
                >
                  <option value="">default</option>
                  <option value="claude">claude</option>
                  <option value="codex">codex</option>
                  <option value="mock">mock</option>
                </select>
              </div>
              <div>
                <FieldLabel>ARC Backend</FieldLabel>
                <select
                  value={activeParams.arcBackend}
                  onChange={(e) => updateParams({ arcBackend: e.target.value as RunLaunchParams["arcBackend"] })}
                  className="mt-1 w-full rounded border border-zinc-700 bg-zinc-900 px-2 py-1.5 text-sm text-zinc-200"
                >
                  <option value="api">api</option>
                  <option value="server">server</option>
                </select>
              </div>
              <div>
                <FieldLabel>Max Turns</FieldLabel>
                <input
                  type="number"
                  value={activeParams.maxTurns ?? ""}
                  onChange={(e) => updateParams({ maxTurns: e.target.value === "" ? null : Number.parseInt(e.target.value, 10) })}
                  className="mt-1 w-full rounded border border-zinc-700 bg-zinc-900 px-2 py-1.5 text-sm text-zinc-200"
                />
              </div>
              <div>
                <FieldLabel>Max GAME_OVER Resets</FieldLabel>
                <input
                  type="number"
                  value={activeParams.maxGameOverResets}
                  onChange={(e) => updateParams({ maxGameOverResets: Number.parseInt(e.target.value || "0", 10) || 0 })}
                  className="mt-1 w-full rounded border border-zinc-700 bg-zinc-900 px-2 py-1.5 text-sm text-zinc-200"
                />
              </div>
              <div>
                <FieldLabel>Score Replay Start Mode</FieldLabel>
                <input
                  value={activeParams.scoreAfterSolveStartMode}
                  onChange={(e) => updateParams({ scoreAfterSolveStartMode: e.target.value })}
                  className="mt-1 w-full rounded border border-zinc-700 bg-zinc-900 px-2 py-1.5 text-sm text-zinc-200"
                />
              </div>
            </div>

            <div className="grid grid-cols-1 gap-3">
              <div>
                <FieldLabel>ARC Base URL</FieldLabel>
                <input
                  value={activeParams.arcBaseUrl}
                  onChange={(e) => updateParams({ arcBaseUrl: e.target.value })}
                  className="mt-1 w-full rounded border border-zinc-700 bg-zinc-900 px-2 py-1.5 text-sm text-zinc-200"
                />
              </div>
              <div>
                <FieldLabel>Scorecard ID</FieldLabel>
                <input
                  value={activeParams.scorecardId}
                  onChange={(e) => updateParams({
                    scorecardId: e.target.value,
                    openScorecard: e.target.value.trim() ? false : activeParams.openScorecard,
                    operationMode: e.target.value.trim() ? "ONLINE" : activeParams.operationMode,
                  })}
                  className="mt-1 w-full rounded border border-zinc-700 bg-zinc-900 px-2 py-1.5 text-sm text-zinc-200"
                />
              </div>
              <div>
                <FieldLabel>Scorecard Owner Check ID</FieldLabel>
                <input
                  value={activeParams.scorecardOwnerCheckId}
                  onChange={(e) => updateParams({ scorecardOwnerCheckId: e.target.value })}
                  className="mt-1 w-full rounded border border-zinc-700 bg-zinc-900 px-2 py-1.5 text-sm text-zinc-200"
                />
              </div>
            </div>

            <div className="grid grid-cols-1 gap-2 rounded border border-zinc-800 bg-zinc-900/40 p-2">
              <CheckboxField
                label="Verbose terminal grid"
                checked={activeParams.verbose}
                onChange={(checked) => updateBooleanField("verbose", checked)}
              />
              <CheckboxField
                label="Open scorecard"
                checked={activeParams.openScorecard}
                onChange={(checked) => updateBooleanField("openScorecard", checked)}
              />
              <CheckboxField
                label="Disable supervisor"
                checked={activeParams.noSupervisor}
                onChange={(checked) => updateBooleanField("noSupervisor", checked)}
              />
              <CheckboxField
                label="Explore inputs"
                checked={activeParams.exploreInputs}
                onChange={(checked) => updateBooleanField("exploreInputs", checked)}
              />
              <CheckboxField
                label="Scorecard session preflight"
                checked={activeParams.scorecardSessionPreflight}
                onChange={(checked) => updateBooleanField("scorecardSessionPreflight", checked)}
              />
              <CheckboxField
                label="Score after solve"
                checked={activeParams.scoreAfterSolve}
                onChange={(checked) => updateBooleanField("scoreAfterSolve", checked)}
              />
            </div>
          </div>

          {error && (
            <div className="mt-3 rounded border border-red-900/80 bg-red-950/60 px-2 py-1.5 text-xs text-red-300">
              {error}
            </div>
          )}

          <div className="mt-3 flex items-center justify-between gap-2">
            <button
              type="button"
              onClick={() => onChange(DEFAULT_RUN_LAUNCH_PARAMS)}
              className="rounded border border-zinc-700 px-2 py-1.5 text-xs text-zinc-400 transition-colors hover:border-zinc-500 hover:text-zinc-200"
            >
              Reset
            </button>
            <button
              type="button"
              onClick={startRun}
              disabled={starting}
              className="rounded border border-blue-500/70 bg-blue-600 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-blue-500 disabled:cursor-not-allowed disabled:bg-zinc-800 disabled:text-zinc-500"
            >
              {starting ? "Starting..." : "Start With These Params"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
