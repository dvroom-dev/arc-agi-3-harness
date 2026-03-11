"use client";

import { ArcGrid } from "./ArcGrid";
import { usePolling } from "@/lib/hooks";
import type { GameState } from "@/lib/types";

interface GameViewProps {
  runId: string;
}

function stateIndicator(state: string) {
  const colors: Record<string, string> = {
    WIN: "bg-green-500",
    NOT_FINISHED: "bg-yellow-500 animate-pulse",
    STOPPED: "bg-zinc-400",
    FAILED: "bg-red-500",
    GAME_OVER: "bg-red-500",
    LOSS: "bg-red-500",
  };
  return (
    <span
      className={`inline-block w-2 h-2 rounded-full ${colors[state] || "bg-zinc-600"}`}
    />
  );
}

export function GameView({ runId }: GameViewProps) {
  const { data: state } = usePolling<GameState | null>(
    `/api/runs/${runId}/state`,
    3000,
    null
  );
  const { data: latestGrid } = usePolling<{ turn?: number; grid: number[][] | null } | null>(
    `/api/runs/${runId}/grid`,
    5000,
    null
  );

  return (
    <div className="space-y-3">
      {/* State header */}
      {state && (
        <div className="flex items-center gap-3 text-sm">
          {stateIndicator(state.state)}
          <span className="font-mono text-zinc-200">
            {state.game_id?.split("-")[0]}
          </span>
          <span className="text-zinc-400">
            Level {state.current_level} &middot;{" "}
            {state.levels_completed}/{state.win_levels || 7} completed
          </span>
          <span className="text-zinc-500">
            {state.total_steps} total steps
          </span>
          {typeof state.current_attempt_steps === "number" ? (
            <span className="text-zinc-600 text-xs">
              attempt: {state.current_attempt_steps}
            </span>
          ) : null}
          {typeof state.total_resets === "number" ? (
            <span className="text-zinc-600 text-xs">
              resets: {state.total_resets}
            </span>
          ) : null}
          {state.last_action && (
            <span className="text-zinc-600 text-xs">
              last: {state.last_action}
            </span>
          )}
        </div>
      )}

      {/* Grid display */}
      {latestGrid?.grid && (
        <div className="bg-zinc-900 rounded-lg p-3 inline-block">
          <div className="text-xs text-zinc-500 mb-2">
            Turn {latestGrid.turn ?? "?"}
          </div>
          <ArcGrid
            grid={latestGrid.grid}
            cellSize={6}
            className="rounded"
          />
        </div>
      )}

      {!latestGrid?.grid && (
        <div className="text-sm text-zinc-600">No grid data available</div>
      )}
    </div>
  );
}
