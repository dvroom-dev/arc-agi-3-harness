"use client";

import { useLayoutEffect, useMemo, useState } from "react";
import { usePolling } from "@/lib/hooks";
import { useAutoFollowScroll } from "@/lib/useAutoFollowScroll";

interface LogStreamProps {
  runId: string;
}

function isErrorLine(line: string) {
  return /\b(error|fatal|traceback|exception|game_over)\b/i.test(line);
}

function isWarningLine(line: string) {
  return /\b(warn|warning)\b/i.test(line);
}

function classifyLine(line: string) {
  if (isErrorLine(line)) {
    return {
      row: "bg-red-950/30 text-red-200 border-red-950/70",
      badge: "border-red-800 bg-red-950/70 text-red-300",
      label: "ERROR",
    };
  }
  if (isWarningLine(line)) {
    return {
      row: "bg-yellow-950/20 text-yellow-100 border-yellow-950/70",
      badge: "border-yellow-800 bg-yellow-950/60 text-yellow-300",
      label: "WARN",
    };
  }
  if (line.includes("[harness]")) {
    return {
      row: "text-sky-200 border-transparent",
      badge: "border-sky-900 bg-sky-950/60 text-sky-300",
      label: "HARNESS",
    };
  }
  if (line.includes("[super]")) {
    return {
      row: "text-violet-200 border-transparent",
      badge: "border-violet-900 bg-violet-950/60 text-violet-300",
      label: "SUPER",
    };
  }
  if (line.includes("[raw")) {
    return {
      row: "text-emerald-200 border-transparent",
      badge: "border-emerald-900 bg-emerald-950/60 text-emerald-300",
      label: "RAW",
    };
  }
  if (line.includes("WIN") || line.includes("level_complete")) {
    return {
      row: "text-green-300 border-transparent",
      badge: "border-green-900 bg-green-950/60 text-green-300",
      label: "OK",
    };
  }
  if (line.includes("keepalive")) {
    return {
      row: "text-orange-200 border-transparent",
      badge: "border-orange-900 bg-orange-950/60 text-orange-300",
      label: "KEEPALIVE",
    };
  }
  return {
    row: "text-zinc-300 border-transparent",
    badge: "border-zinc-800 bg-zinc-900 text-zinc-500",
    label: "LOG",
  };
}

export function LogStream({ runId }: LogStreamProps) {
  const { data } = usePolling<{
    lines: string[];
    file: string | null;
    totalLines?: number;
    rawEventLines?: string[];
    rawEventFile?: string | null;
    errorCount: number;
    warningCount: number;
  }>(`/api/runs/${runId}/logs?tail=500`, 3000, {
    lines: [],
    file: null,
    rawEventLines: [],
    rawEventFile: null,
    errorCount: 0,
    warningCount: 0,
  });

  const [showErrors, setShowErrors] = useState(false);
  const [showWarnings, setShowWarnings] = useState(false);

  const filtered = useMemo(() => {
    const active = showErrors || showWarnings;
    const matches = (line: string) =>
      !active ||
      (showErrors && isErrorLine(line)) ||
      (showWarnings && isWarningLine(line));

    return {
      lines: data.lines.filter(matches),
      rawEventLines: (data.rawEventLines || []).filter(matches),
    };
  }, [data.lines, data.rawEventLines, showErrors, showWarnings]);

  const { scrollRef, handleScroll, syncScrollPosition } = useAutoFollowScroll();

  useLayoutEffect(() => {
    syncScrollPosition();
  }, [filtered.lines.length, filtered.rawEventLines.length, syncScrollPosition]);

  return (
    <div className="flex flex-col h-full min-h-0">
      {data.file && (
        <div className="flex items-center justify-between gap-3 px-3 py-2 border-b border-zinc-800 shrink-0 bg-zinc-950/80">
          <div className="min-w-0 truncate text-xs text-zinc-400">
            {data.file}
            {data.totalLines && (
              <span className="ml-2 text-zinc-600">({data.totalLines} lines)</span>
            )}
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
        <div className="space-y-1 p-2">
          {filtered.lines.map((line, i) => {
            const tone = classifyLine(line);
            return (
              <div
                key={i}
                className={`flex items-start gap-2 rounded-md border px-2 py-1 hover:bg-zinc-800/30 ${tone.row}`}
              >
                <span className={`mt-0.5 shrink-0 rounded border px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-[0.14em] ${tone.badge}`}>
                  {tone.label}
                </span>
                <span className="min-w-0 whitespace-pre-wrap break-words">
                  {line || "\u00a0"}
                </span>
              </div>
            );
          })}
        </div>
        {Boolean(filtered.rawEventLines.length) && (
          <>
            <div className="px-3 pt-3 pb-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-zinc-500 border-t border-zinc-800 mt-2">
              {data.rawEventFile || "raw events"}
            </div>
            <div className="space-y-1 p-2 pt-0">
              {filtered.rawEventLines.map((line, i) => {
                const tone = classifyLine(line);
                return (
                  <div
                    key={`raw-${i}`}
                    className={`flex items-start gap-2 rounded-md border px-2 py-1 hover:bg-zinc-800/30 ${tone.row}`}
                  >
                    <span className={`mt-0.5 shrink-0 rounded border px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-[0.14em] ${tone.badge}`}>
                      {tone.label}
                    </span>
                    <span className="min-w-0 whitespace-pre-wrap break-words">
                      {line}
                    </span>
                  </div>
                );
              })}
            </div>
          </>
        )}
        {filtered.lines.length === 0 && (
          <div className="p-4 text-zinc-600 text-center">
            {filtered.rawEventLines.length
              ? "Showing raw event tail"
              : showErrors || showWarnings
                ? "No log lines match the active filters"
                : "No log data"}
          </div>
        )}
      </div>
    </div>
  );
}
