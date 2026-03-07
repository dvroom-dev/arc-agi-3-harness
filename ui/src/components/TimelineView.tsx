"use client";

import { useState, useEffect, useRef } from "react";
import { ArcGrid } from "./ArcGrid";
import { usePolling } from "@/lib/hooks";
import type { HistoryEvent, TraceSummary, TraceWithGrid } from "@/lib/types";

interface TimelineViewProps {
  runId: string;
}

interface TimelineEvent extends HistoryEvent {
  index: number;
  traceTurn: number | null;
}

interface LevelSegment {
  level: number;
  events: TimelineEvent[];
  completed: boolean;
}

function mapHistoryEventsToTraceTurns(
  events: HistoryEvent[],
  traceSummaries: TraceSummary[]
): TimelineEvent[] {
  const mapped = events.map((event, index) => ({
    ...event,
    index,
    traceTurn: null,
  }));

  let eventIndex = 0;

  const consumeNextMatchingEvent = (
    predicate: (event: HistoryEvent) => boolean,
    turnNumber: number
  ) => {
    while (eventIndex < mapped.length) {
      const current = mapped[eventIndex];
      if (current.traceTurn === null && predicate(current)) {
        current.traceTurn = turnNumber;
        eventIndex += 1;
        return;
      }
      eventIndex += 1;
    }
  };

  const consumeNextStepEvents = (count: number, turnNumber: number) => {
    let assigned = 0;
    while (eventIndex < mapped.length && assigned < count) {
      const current = mapped[eventIndex];
      if (current.traceTurn === null && current.kind !== "reset") {
        current.traceTurn = turnNumber;
        assigned += 1;
      }
      eventIndex += 1;
    }
  };

  for (const trace of traceSummaries) {
    if (trace.action === "status") {
      continue;
    }
    if (trace.action === "reset_level") {
      consumeNextMatchingEvent((event) => event.kind === "reset", trace.turnNumber);
      continue;
    }

    consumeNextStepEvents(Math.max(1, trace.steps), trace.turnNumber);
  }

  return mapped;
}

function segmentByLevel(events: TimelineEvent[]): LevelSegment[] {
  const segments: LevelSegment[] = [];
  let currentLevel = 1;
  let currentEvents: TimelineEvent[] = [];

  events.forEach((event) => {
    if (event.kind === "step" && event.levels_completed !== undefined) {
      const newLevel = event.levels_completed + 1;
      if (newLevel > currentLevel) {
        segments.push({
          level: currentLevel,
          events: currentEvents,
          completed: true,
        });
        currentLevel = newLevel;
        currentEvents = [event];
      } else {
        currentEvents.push(event);
      }
    } else {
      currentEvents.push(event);
    }
  });

  if (currentEvents.length > 0) {
    segments.push({
      level: currentLevel,
      events: currentEvents,
      completed: false,
    });
  }

  return segments;
}

export function TimelineView({ runId }: TimelineViewProps) {
  const { data: history } = usePolling<{ events: HistoryEvent[] }>(
    `/api/runs/${runId}/history`,
    3000,
    { events: [] }
  );
  const { data: traceSummaries } = usePolling<TraceSummary[]>(
    `/api/runs/${runId}/traces`,
    5000,
    []
  );

  const [selectedTurn, setSelectedTurn] = useState<number | null>(null);
  const [selectedEventIndex, setSelectedEventIndex] = useState<number | null>(null);
  const [selectedGrid, setSelectedGrid] = useState<TraceWithGrid | null>(null);
  const [isLive, setIsLive] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);

  const mappedEvents = mapHistoryEventsToTraceTurns(history.events, traceSummaries);
  const segments = segmentByLevel(mappedEvents);
  const totalTraces = traceSummaries.length;

  // Fetch grid for selected turn (or latest in live mode)
  useEffect(() => {
    const turnToFetch = isLive && totalTraces > 0
      ? traceSummaries[totalTraces - 1].turnNumber
      : selectedTurn;
    if (turnToFetch === null || turnToFetch === undefined) {
      return;
    }
    fetch(`/api/runs/${runId}/traces?turn=${turnToFetch}`)
      .then((r) => r.json())
      .then(setSelectedGrid)
      .catch(console.error);
  }, [runId, selectedTurn, isLive, totalTraces, traceSummaries]);

  useEffect(() => {
    if (isLive && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [history.events.length, isLive]);

  return (
    <div className="flex gap-3 h-full">
      {/* Timeline */}
      <div className="w-56 flex flex-col border-r border-zinc-800">
        <div className="flex items-center justify-between px-2 py-1.5 border-b border-zinc-800">
          <span className="text-xs font-medium text-zinc-400">TIMELINE</span>
          <button
            onClick={() => {
              setIsLive(!isLive);
              if (!isLive) {
                setSelectedTurn(null);
                setSelectedEventIndex(null);
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
                const isCurrent = !isLive && selectedEventIndex === event.index;
                return (
                  <button
                    key={event.index}
                    onClick={() => {
                      setIsLive(false);
                      setSelectedEventIndex(event.index);
                      setSelectedTurn(event.traceTurn);
                      if (event.traceTurn === null) {
                        setSelectedGrid(null);
                      }
                    }}
                    className={`w-full text-left px-3 py-0.5 hover:bg-zinc-800/50 font-mono ${
                      isCurrent ? "bg-blue-900/30 text-blue-300" : ""
                    } ${event.kind === "reset" ? "text-orange-400" : "text-zinc-300"}`}
                  >
                    <span>
                      {event.kind === "reset" ? "\u21ba reset" : event.action}
                    </span>
                    {event.traceTurn === null && (
                      <span className="ml-2 text-zinc-600">no trace</span>
                    )}
                  </button>
                );
              })}
            </div>
          ))}
        </div>
      </div>

      {/* Grid preview */}
      <div className="flex-1 p-2">
        {selectedGrid?.grid ? (
          <div>
            <div className="text-xs text-zinc-500 mb-2">
              Turn {selectedGrid.turnNumber} &middot; {selectedGrid.action}
              {selectedGrid.scriptError && (
                <span className="text-red-400 ml-2">SCRIPT ERROR</span>
              )}
              {selectedGrid.steps > 0 && (
                <span className="text-zinc-600 ml-2">
                  {selectedGrid.steps} steps
                </span>
              )}
            </div>
            <ArcGrid grid={selectedGrid.grid} cellSize={6} className="rounded" />
          </div>
        ) : !isLive && selectedEventIndex !== null ? (
          <div className="text-xs text-zinc-600">
            No trace artifact available for this event
          </div>
        ) : (
          <div className="text-xs text-zinc-600">Select a turn to view grid</div>
        )}
      </div>
    </div>
  );
}
