"use client";

import { usePolling } from "@/lib/hooks";
import type { HistoryEvent } from "@/lib/types";

interface HistoryTableProps {
  runId: string;
}

export function HistoryTable({ runId }: HistoryTableProps) {
  const { data } = usePolling<{ events: HistoryEvent[]; turn?: number }>(
    `/api/runs/${runId}/history`,
    3000,
    { events: [] }
  );

  return (
    <div className="flex flex-col h-full">
      <div className="text-xs text-zinc-600 px-2 py-1 border-b border-zinc-800 shrink-0">
        tool-engine-history ({data.events.length} events
        {data.turn !== undefined && `, turn ${data.turn}`})
      </div>
      <div className="flex-1 overflow-y-auto">
        <table className="w-full text-xs font-mono">
          <thead className="sticky top-0 bg-zinc-950">
            <tr className="text-zinc-500 border-b border-zinc-800">
              <th className="text-left px-2 py-1 w-10">#</th>
              <th className="text-left px-2 py-1 w-16">Kind</th>
              <th className="text-left px-2 py-1">Action</th>
              <th className="text-left px-2 py-1 w-16">Levels</th>
            </tr>
          </thead>
          <tbody>
            {data.events.map((event, i) => (
              <tr
                key={i}
                className={`border-b border-zinc-800/30 ${
                  event.kind === "reset"
                    ? "text-orange-400"
                    : "text-zinc-300"
                }`}
              >
                <td className="px-2 py-0.5 text-zinc-600">{i + 1}</td>
                <td className="px-2 py-0.5">{event.kind}</td>
                <td className="px-2 py-0.5">{event.action || "-"}</td>
                <td className="px-2 py-0.5">
                  {event.levels_completed !== undefined
                    ? event.levels_completed
                    : "-"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {data.events.length === 0 && (
          <div className="p-4 text-zinc-600 text-center text-sm">
            No history events
          </div>
        )}
      </div>
    </div>
  );
}
