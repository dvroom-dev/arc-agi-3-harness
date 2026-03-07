"use client";

import { useEffect, useRef } from "react";
import { usePolling } from "@/lib/hooks";

interface LogStreamProps {
  runId: string;
}

function classifyLine(line: string): string {
  if (line.includes("[harness]")) return "text-blue-300";
  if (line.includes("[super]")) return "text-purple-300";
  if (line.includes("ERROR") || line.includes("error") || line.includes("Error"))
    return "text-red-400";
  if (line.includes("WARNING") || line.includes("warning"))
    return "text-yellow-400";
  if (line.includes("WIN") || line.includes("level_complete"))
    return "text-green-400";
  if (line.includes("GAME_OVER")) return "text-red-500 font-bold";
  if (line.includes("keepalive")) return "text-orange-300";
  return "text-zinc-400";
}

export function LogStream({ runId }: LogStreamProps) {
  const { data } = usePolling<{
    lines: string[];
    file: string | null;
    totalLines?: number;
  }>(`/api/runs/${runId}/logs?tail=500`, 3000, {
    lines: [],
    file: null,
  });

  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [data.lines.length]);

  return (
    <div className="flex flex-col h-full">
      {data.file && (
        <div className="text-xs text-zinc-600 px-2 py-1 border-b border-zinc-800 shrink-0">
          {data.file}
          {data.totalLines && (
            <span className="ml-2">({data.totalLines} lines)</span>
          )}
        </div>
      )}
      <div className="flex-1 overflow-y-auto font-mono text-xs leading-relaxed" ref={scrollRef}>
        {data.lines.map((line, i) => (
          <div
            key={i}
            className={`px-2 hover:bg-zinc-800/30 ${classifyLine(line)}`}
          >
            {line || "\u00a0"}
          </div>
        ))}
        {data.lines.length === 0 && (
          <div className="p-4 text-zinc-600 text-center">No log data</div>
        )}
      </div>
    </div>
  );
}
