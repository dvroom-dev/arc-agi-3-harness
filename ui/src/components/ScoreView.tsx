"use client";

import type { ReactNode } from "react";
import { usePolling } from "@/lib/hooks";
import type {
  GameScoreSummary,
  LevelScoreSummary,
  RunScorePayload,
  ScoreComparisonGame,
} from "@/lib/types";

interface ScoreViewProps {
  runId: string;
}

function formatScore(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "n/a";
  return value.toFixed(2);
}

function ComparisonBadge({
  matches,
  unavailableLabel = "Unavailable",
}: {
  matches: boolean | null;
  unavailableLabel?: string;
}) {
  const text = matches === null ? unavailableLabel : matches ? "Matches" : "Mismatch";
  const className = matches === null
    ? "border-zinc-700 bg-zinc-900 text-zinc-400"
    : matches
      ? "border-green-800 bg-green-950/60 text-green-300"
      : "border-red-800 bg-red-950/60 text-red-300";

  return (
    <span className={`inline-flex rounded border px-2 py-1 text-[11px] font-medium ${className}`}>
      {text}
    </span>
  );
}

function SummaryCard({
  title,
  summary,
  match,
  footer,
}: {
  title: string;
  summary: {
    score: number;
    totalGames: number;
    totalGamesCompleted: number;
    totalLevelsCompleted: number;
    totalLevels: number;
    totalActions: number;
  };
  match: boolean | null;
  footer?: ReactNode;
}) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950/70 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-[11px] uppercase tracking-wide text-zinc-500">{title}</div>
          <div className="mt-2 text-3xl font-semibold text-zinc-100">{formatScore(summary.score)}</div>
        </div>
        <ComparisonBadge matches={match} />
      </div>
      <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
        <div>
          <div className="text-zinc-500">Games</div>
          <div className="text-zinc-200">{summary.totalGamesCompleted}/{summary.totalGames}</div>
        </div>
        <div>
          <div className="text-zinc-500">Levels</div>
          <div className="text-zinc-200">{summary.totalLevelsCompleted}/{summary.totalLevels}</div>
        </div>
        <div>
          <div className="text-zinc-500">Actions</div>
          <div className="text-zinc-200">{summary.totalActions}</div>
        </div>
      </div>
      {footer && <div className="mt-4 border-t border-zinc-800 pt-3 text-xs text-zinc-400">{footer}</div>}
    </div>
  );
}

function levelComparisonFor(
  comparisonGame: ScoreComparisonGame | undefined,
  level: number
) {
  return comparisonGame?.levels.find((entry) => entry.level === level)?.matches ?? null;
}

function LevelRow({
  localLevel,
  scorecardLevel,
  matches,
}: {
  localLevel: LevelScoreSummary;
  scorecardLevel: LevelScoreSummary | null;
  matches: boolean | null;
}) {
  return (
    <tr className="border-t border-zinc-800/80">
      <td className="px-3 py-2 text-zinc-300">L{localLevel.level}</td>
      <td className="px-3 py-2 text-zinc-200">{formatScore(localLevel.score)}</td>
      <td className="px-3 py-2 text-zinc-400">{localLevel.actions}</td>
      <td className="px-3 py-2 text-zinc-500">{localLevel.baselineActions ?? "n/a"}</td>
      <td className="px-3 py-2 text-zinc-400">{localLevel.completed ? "yes" : "no"}</td>
      <td className="px-3 py-2 text-zinc-200">{formatScore(scorecardLevel?.score)}</td>
      <td className="px-3 py-2 text-zinc-400">{scorecardLevel?.actions ?? "n/a"}</td>
      <td className="px-3 py-2"><ComparisonBadge matches={matches} unavailableLabel="No live scorecard" /></td>
    </tr>
  );
}

function GameScoreCard({
  localGame,
  scorecardGame,
  comparisonGame,
}: {
  localGame: GameScoreSummary;
  scorecardGame: GameScoreSummary | null;
  comparisonGame: ScoreComparisonGame | undefined;
}) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950/70">
      <div className="flex items-start justify-between gap-4 border-b border-zinc-800 px-4 py-3">
        <div>
          <div className="font-mono text-sm text-zinc-200">{localGame.gameId}</div>
          <div className="mt-1 text-xs text-zinc-500">
            {localGame.completed ? "Completed" : (localGame.selectedAttemptState || "In progress")}
            {" · "}
            attempts {localGame.attempts}
            {" · "}
            selected {localGame.selectedAttemptGuid || "n/a"}
          </div>
          {localGame.selectedAttemptMessage && (
            <div className="mt-1 text-xs text-amber-300">{localGame.selectedAttemptMessage}</div>
          )}
        </div>
        <ComparisonBadge matches={comparisonGame?.matches ?? null} />
      </div>

      <div className="grid grid-cols-2 gap-4 px-4 py-3 text-sm">
        <div className="rounded border border-zinc-800 bg-zinc-900/60 p-3">
          <div className="text-[11px] uppercase tracking-wide text-zinc-500">Local</div>
          <div className="mt-2 text-2xl font-semibold text-zinc-100">{formatScore(localGame.score)}</div>
          <div className="mt-2 text-zinc-400">
            Levels {localGame.levelsCompleted}/{localGame.levelCount}
          </div>
          <div className="text-zinc-500">Actions {localGame.actions} · Resets {localGame.resets}</div>
        </div>
        <div className="rounded border border-zinc-800 bg-zinc-900/60 p-3">
          <div className="text-[11px] uppercase tracking-wide text-zinc-500">Scorecard</div>
          <div className="mt-2 text-2xl font-semibold text-zinc-100">{formatScore(scorecardGame?.score)}</div>
          <div className="mt-2 text-zinc-400">
            Levels {scorecardGame?.levelsCompleted ?? "n/a"}/{scorecardGame?.levelCount ?? "n/a"}
          </div>
          <div className="text-zinc-500">
            Actions {scorecardGame?.actions ?? "n/a"} · Resets {scorecardGame?.resets ?? "n/a"}
          </div>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead className="bg-zinc-900/80 text-left text-[11px] uppercase tracking-wide text-zinc-500">
            <tr>
              <th className="px-3 py-2">Level</th>
              <th className="px-3 py-2">Local Score</th>
              <th className="px-3 py-2">Local Actions</th>
              <th className="px-3 py-2">Baseline</th>
              <th className="px-3 py-2">Done</th>
              <th className="px-3 py-2">Scorecard Score</th>
              <th className="px-3 py-2">Scorecard Actions</th>
              <th className="px-3 py-2">Check</th>
            </tr>
          </thead>
          <tbody>
            {localGame.levels.map((localLevel) => (
              <LevelRow
                key={localLevel.level}
                localLevel={localLevel}
                scorecardLevel={scorecardGame?.levels.find((level) => level.level === localLevel.level) || null}
                matches={levelComparisonFor(comparisonGame, localLevel.level)}
              />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function ScoreView({ runId }: ScoreViewProps) {
  const { data, loading } = usePolling<RunScorePayload | null>(
    `/api/runs/${runId}/score`,
    5000,
    null
  );

  if (loading && !data) {
    return (
      <div className="p-4 text-sm text-zinc-500">
        Loading score summary...
      </div>
    );
  }

  if (!data) {
    return (
      <div className="p-4 text-sm text-red-300">
        Failed to load scores.
      </div>
    );
  }

  const maybeError = (data as { error?: string }).error;
  if (maybeError) {
    return (
      <div className="p-4 text-sm text-red-300">
        Failed to load scores: {maybeError}
      </div>
    );
  }

  const scorecardSummary = data.scorecard?.live;
  const comparison = data.comparison;
  const comparisonGames = new Map(
    (comparison?.games || []).map((game) => [game.gameId, game])
  );

  return (
    <div className="h-full overflow-y-auto p-4">
      <div className="grid gap-4 lg:grid-cols-2">
        <SummaryCard
          title="Local Computed Score"
          summary={data.local}
          match={comparison?.totalMatches ?? null}
          footer="Computed from run artifacts with the same baseline-action formula used by the ARC scorecard backend."
        />
        <SummaryCard
          title="Scorecard"
          summary={scorecardSummary || {
            score: data.scorecard?.finalScore ?? 0,
            totalGames: data.local.totalGames,
            totalGamesCompleted: data.local.totalGamesCompleted,
            totalLevelsCompleted: data.local.totalLevelsCompleted,
            totalLevels: data.local.totalLevels,
            totalActions: data.local.totalActions,
          }}
          match={comparison?.totalMatches ?? null}
          footer={(
            <div className="space-y-1">
              <div>Card ID: {data.scorecard?.cardId || "none"}</div>
              {data.scorecard?.webUrl && (
                <a
                  href={data.scorecard.webUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="text-blue-300 hover:text-blue-200"
                >
                  Open scorecard
                </a>
              )}
              {data.scorecard?.liveFetchError && (
                <div className="text-amber-300">Live fetch unavailable: {data.scorecard.liveFetchError}</div>
              )}
            </div>
          )}
        />
      </div>

      <div className="mt-4 rounded-lg border border-zinc-800 bg-zinc-950/70 px-4 py-3 text-sm text-zinc-400">
        <span className="text-zinc-500">Comparison mode:</span>{" "}
        {comparison?.mode || "none"}
        {" · "}
        <span className="text-zinc-500">Result:</span>{" "}
        {comparison ? (comparison.matches ? "local score matches scorecard" : "local score differs from scorecard") : "no scorecard comparison available"}
      </div>

      <div className="mt-4 space-y-4">
        {data.local.games.map((localGame) => (
          <GameScoreCard
            key={localGame.gameId}
            localGame={localGame}
            scorecardGame={scorecardSummary?.games.find((game) => game.gameId === localGame.gameId) || null}
            comparisonGame={comparisonGames.get(localGame.gameId)}
          />
        ))}
      </div>
    </div>
  );
}
