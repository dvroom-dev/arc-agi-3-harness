"use client";

import { useState, useEffect, useRef } from "react";
import { ArcGrid } from "./ArcGrid";
import { usePolling } from "@/lib/hooks";
import type { TraceSummary, TraceWithGrid } from "@/lib/types";

interface TimelineViewProps {
  runId: string;
}

interface TimelineEvent {
  id: string;
  label: string;
  level: number;
  traceTurn: number;
  stepInCall: number | null;
  scriptError: boolean;
  steps: number;
  traceAction: string;
}

interface LevelSegment {
  level: number;
  events: TimelineEvent[];
  completed: boolean;
}

function labelForTrace(trace: TraceSummary): string {
  if (trace.action === "reset_level") return "\u21bb reset";
  if (trace.scriptError) return `${trace.action} (script error)`;
  return trace.action;
}

function buildTimelineEvents(traceSummaries: TraceSummary[]): TimelineEvent[] {
  const events: TimelineEvent[] = [];
  let currentLevel = 1;

  for (const trace of traceSummaries) {
    const traceLevel = trace.startLevel ?? currentLevel;
    currentLevel = trace.endLevel ?? traceLevel;

    if (trace.action === "status") {
      continue;
    }

    if (trace.action === "reset_level") {
      events.push({
        id: `turn-${trace.turnNumber}-reset`,
        label: labelForTrace(trace),
        level: traceLevel,
        traceTurn: trace.turnNumber,
        stepInCall: null,
        scriptError: trace.scriptError,
        steps: trace.steps,
        traceAction: trace.action,
      });
      continue;
    }

    const labels = trace.stepActions?.length ? trace.stepActions : [labelForTrace(trace)];
    labels.forEach((label, index) => {
      events.push({
        id: `turn-${trace.turnNumber}-step-${index}`,
        label,
        level: traceLevel,
        traceTurn: trace.turnNumber,
        stepInCall: trace.stepActions?.length ? index + 1 : null,
        scriptError: trace.scriptError,
        steps: trace.steps,
        traceAction: trace.action,
      });
    });
  }

  return events;
}

function segmentByLevel(events: TimelineEvent[]): LevelSegment[] {
  const segments: LevelSegment[] = [];
  for (const event of events) {
    const current = segments[segments.length - 1];
    if (!current || current.level !== event.level) {
      if (current) {
        current.completed = true;
      }
      segments.push({
        level: event.level,
        events: [event],
        completed: false,
      });
      continue;
    }
    current.events.push(event);
  }
  return segments;
}

export function TimelineView({ runId }: TimelineViewProps) {
  const { data: traceSummaries } = usePolling<TraceSummary[]>(
    `/api/runs/${runId}/traces`,
    5000,
    []
  );

  const [selectedTurn, setSelectedTurn] = useState<number | null>(null);
  const [selectedStepInCall, setSelectedStepInCall] = useState<number | null>(null);
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const [selectedGrid, setSelectedGrid] = useState<TraceWithGrid | null>(null);
  const [isLive, setIsLive] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);

  const segments = segmentByLevel(buildTimelineEvents(traceSummaries));
  const totalTraces = traceSummaries.length;

  // Fetch grid for selected turn (or latest in live mode)
  useEffect(() => {
    const turnToFetch = isLive && totalTraces > 0
      ? traceSummaries[totalTraces - 1].turnNumber
      : selectedTurn;
    if (turnToFetch === null || turnToFetch === undefined) {
      return;
    }
    const search = new URLSearchParams({ turn: String(turnToFetch) });
    if (!isLive && selectedStepInCall !== null) {
      search.set("step", String(selectedStepInCall));
    }
    fetch(`/api/runs/${runId}/traces?${search.toString()}`)
      .then((r) => r.json())
      .then(setSelectedGrid)
      .catch(console.error);
  }, [runId, selectedTurn, selectedStepInCall, isLive, totalTraces, traceSummaries]);

  useEffect(() => {
    if (isLive && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [traceSummaries.length, isLive]);

  return (
    <div className="flex gap-3 h-full min-h-0 min-w-0">
      {/* Timeline */}
      <div className="w-52 shrink-0 flex flex-col border-r border-zinc-800">
        <div className="flex items-center justify-between px-2 py-1.5 border-b border-zinc-800">
          <span className="text-xs font-medium text-zinc-400">TIMELINE</span>
          <button
            onClick={() => {
              setIsLive(!isLive);
              if (!isLive) {
                setSelectedTurn(null);
                setSelectedStepInCall(null);
                setSelectedEventId(null);
              }
            }}
            className={`text-xs px-1.5 py-0.5 rounded ${
              isLive
                ? "bg-green-900/50 text-green-400 border border-green-700"
                : "bg-zinc-800 text-zinc-400 border border-zinc-700"
            }`}
          >
            {isLive ? "LIVE" : "REPLAY"}
          </button>
        </div>
        <div className="flex-1 overflow-y-auto text-xs" ref={scrollRef}>
          {segments.map((seg) => (
            <div key={seg.level} className="border-b border-zinc-800/50">
              <div className="px-2 py-1 bg-zinc-900/50 text-zinc-400 font-medium sticky top-0">
                Level {seg.level}
                {seg.completed && (
                  <span className="text-green-500 ml-1">&#10003;</span>
                )}
              </div>
              {seg.events.map((event) => {
                const isCurrent = !isLive && selectedEventId === event.id;
                return (
                  <button
                    key={event.id}
                    onClick={() => {
                      setIsLive(false);
                      setSelectedEventId(event.id);
                      setSelectedTurn(event.traceTurn);
                      setSelectedStepInCall(event.stepInCall);
                    }}
                    className={`w-full text-left px-3 py-0.5 hover:bg-zinc-800/50 font-mono ${
                      isCurrent ? "bg-blue-900/30 text-blue-300" : ""
                    } ${event.traceAction === "reset_level" ? "text-orange-400" : "text-zinc-300"}`}
                  >
                    <span>{event.label}</span>
                    {event.scriptError && (
                      <span className="ml-2 text-red-500">error</span>
                    )}
                  </button>
                );
              })}
            </div>
          ))}
        </div>
      </div>

      {/* Grid preview */}
      <div className="flex-1 min-h-0 min-w-0 p-2">
        {selectedGrid?.grid ? (
          <div className="flex h-full min-h-0 min-w-0 flex-col">
            <div className="text-xs text-zinc-500 mb-2 shrink-0">
              Turn {selectedGrid.turnNumber} &middot; {selectedGrid.action}
              {selectedGrid.selectedStep ? (
                <span className="text-zinc-400 ml-2">step {selectedGrid.selectedStep}</span>
              ) : null}
              {selectedGrid.scriptError && (
                <span className="text-red-400 ml-2">SCRIPT ERROR</span>
              )}
              {selectedGrid.steps > 0 && (
                <span className="text-zinc-600 ml-2">
                  {selectedGrid.steps} steps
                </span>
              )}
            </div>
            <div className="flex-1 min-h-0 min-w-0 overflow-auto">
              <div className="flex min-h-full min-w-full items-start justify-center">
                <div className="min-w-max">
                  <ArcGrid grid={selectedGrid.grid} cellSize={6} className="rounded" />
                </div>
              </div>
            </div>
          </div>
        ) : (
          <div className="text-xs text-zinc-600">Select a turn to view grid</div>
        )}
      </div>
    </div>
  );
}
