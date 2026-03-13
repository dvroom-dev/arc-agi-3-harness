"use client";

import { useLayoutEffect, useMemo, useState } from "react";
import { usePolling } from "@/lib/hooks";
import { useAutoFollowScroll } from "@/lib/useAutoFollowScroll";
import type { LogFeedEntry, LogFeedPayload } from "@/lib/types";

interface LogStreamProps {
  runId: string;
}

function classifyEntry(entry: LogFeedEntry) {
  if (entry.severity === "error") {
    return {
      row: "bg-red-950/30 text-red-200 border-red-950/70",
      badge: "border-red-800 bg-red-950/70 text-red-300",
      label: entry.label,
    };
  }
  if (entry.severity === "warning") {
    return {
      row: "bg-yellow-950/20 text-yellow-100 border-yellow-950/70",
      badge: "border-yellow-800 bg-yellow-950/60 text-yellow-300",
      label: entry.label,
    };
  }
  if (entry.label === "HARNESS") {
    return {
      row: "text-sky-200 border-transparent",
      badge: "border-sky-900 bg-sky-950/60 text-sky-300",
      label: entry.label,
    };
  }
  if (entry.label === "SUPER") {
    return {
      row: "text-violet-200 border-transparent",
      badge: "border-violet-900 bg-violet-950/60 text-violet-300",
      label: entry.label,
    };
  }
  if (entry.label === "RAW") {
    return {
      row: "text-emerald-200 border-transparent",
      badge: "border-emerald-900 bg-emerald-950/60 text-emerald-300",
      label: entry.label,
    };
  }
  if (entry.severity === "success") {
    return {
      row: "text-green-300 border-transparent",
      badge: "border-green-900 bg-green-950/60 text-green-300",
      label: entry.label,
    };
  }
  if (entry.label === "KEEPALIVE") {
    return {
      row: "text-orange-200 border-transparent",
      badge: "border-orange-900 bg-orange-950/60 text-orange-300",
      label: entry.label,
    };
  }
  return {
    row: "text-zinc-300 border-transparent",
    badge: "border-zinc-800 bg-zinc-900 text-zinc-500",
    label: entry.label,
  };
}

export function LogStream({ runId }: LogStreamProps) {
  const { data, error: pollError } = usePolling<LogFeedPayload>(`/api/runs/${runId}/logs?tail=500`, 3000, {
    streams: [],
    errorCount: 0,
    warningCount: 0,
    error: null,
  });

  const [showErrors, setShowErrors] = useState(false);
  const [showWarnings, setShowWarnings] = useState(false);

  const filteredStreams = useMemo(() => {
    const active = showErrors || showWarnings;
    const matches = (entry: LogFeedEntry) =>
      !active ||
      (showErrors && entry.severity === "error") ||
      (showWarnings && entry.severity === "warning");

    return data.streams
      .map((stream) => ({
        ...stream,
        entries: stream.entries.filter(matches),
      }))
      .filter((stream) => stream.entries.length > 0 || stream.file);
  }, [data.streams, showErrors, showWarnings]);
  const visibleEntryCount = useMemo(
    () => filteredStreams.reduce((sum, stream) => sum + stream.entries.length, 0),
    [filteredStreams]
  );

  const { scrollRef, handleScroll, syncScrollPosition } = useAutoFollowScroll();

  useLayoutEffect(() => {
    syncScrollPosition();
  }, [visibleEntryCount, syncScrollPosition]);

  const primaryStream = filteredStreams[0] || data.streams[0] || null;
  const loadError = pollError || data.error;
  const hasEntries = filteredStreams.some((stream) => stream.entries.length > 0);

  return (
    <div className="flex flex-col h-full min-h-0">
      {primaryStream?.file && (
        <div className="flex items-center justify-between gap-3 px-3 py-2 border-b border-zinc-800 shrink-0 bg-zinc-950/80">
          <div className="min-w-0 truncate text-xs text-zinc-400">
            {primaryStream.file}
            {typeof primaryStream.totalLines === "number" ? (
              <span className="ml-2 text-zinc-600">({primaryStream.totalLines} lines)</span>
            ) : null}
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <button
              type="button"
              onClick={() => setShowErrors((value) => !value)}
              className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold ${
                showErrors
                  ? "border-red-700 bg-red-900 text-red-100"
                  : "border-red-800 bg-red-950/70 text-red-300"
              }`}
            >
              {data.errorCount} errors
            </button>
            <button
              type="button"
              onClick={() => setShowWarnings((value) => !value)}
              className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold ${
                showWarnings
                  ? "border-yellow-700 bg-yellow-900 text-yellow-100"
                  : "border-yellow-800 bg-yellow-950/60 text-yellow-300"
              }`}
            >
              {data.warningCount} warnings
            </button>
            {(showErrors || showWarnings) && (
              <button
                type="button"
                onClick={() => {
                  setShowErrors(false);
                  setShowWarnings(false);
                }}
                className="rounded-full border border-zinc-700 bg-zinc-900 px-2 py-0.5 text-[10px] font-semibold text-zinc-300"
              >
                clear
              </button>
            )}
          </div>
        </div>
      )}
      <div
        className="flex-1 overflow-y-auto font-mono text-xs leading-relaxed bg-[linear-gradient(180deg,rgba(24,24,27,0.55)_0%,rgba(9,9,11,0)_100%)]"
        ref={scrollRef}
        onScroll={handleScroll}
      >
        {loadError ? (
          <div className="border-b border-zinc-800 px-3 py-2 text-xs text-amber-300">
            Log feed warning: {loadError}
          </div>
        ) : null}
        {filteredStreams.map((stream, index) => (
          <div key={stream.id}>
            {index > 0 ? (
              <div className="mt-2 border-t border-zinc-800 px-3 pt-3 pb-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-zinc-500">
                {stream.title}
              </div>
            ) : null}
            <div className="space-y-1 p-2">
              {stream.entries.map((entry) => {
                const tone = classifyEntry(entry);
                return (
                  <div
                    key={entry.id}
                    className={`flex items-start gap-2 rounded-md border px-2 py-1 hover:bg-zinc-800/30 ${tone.row}`}
                  >
                    <span className={`mt-0.5 shrink-0 rounded border px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-[0.14em] ${tone.badge}`}>
                      {tone.label}
                    </span>
                    <span className="min-w-0 whitespace-pre-wrap break-words">
                      {entry.text || "\u00a0"}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
        {!hasEntries ? (
          <div className="p-4 text-center text-zinc-600">
            {showErrors || showWarnings
              ? "No log lines match the active filters"
              : "No log data"}
          </div>
        ) : null}
      </div>
    </div>
  );
}
