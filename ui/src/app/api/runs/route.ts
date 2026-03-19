import { NextResponse } from "next/server";
import fs from "fs/promises";
import path from "path";
import { RUNS_DIR, LOGS_DIR } from "@/lib/paths";
import type { RunSummary } from "@/lib/types";
import { readRecordedRunParams } from "@/lib/runParams.server";
import {
  inferDisplayedRunState,
  listActiveRunIds,
  runProcessLookupIdsFromStoredRunParams,
} from "@/lib/runState.server";
import { readRunStateListSnapshot } from "@/lib/runStateSnapshot.server";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  try {
    const requestUrl = new URL(request.url);
    const rawLimit = Number.parseInt(requestUrl.searchParams.get("limit") || "", 10);
    const limit = Number.isFinite(rawLimit) && rawLimit > 0 ? rawLimit : null;
    const entries = await fs.readdir(RUNS_DIR, { withFileTypes: true });
    const activeRunIds = await listActiveRunIds();
    const logFileNames = new Set(
      (await fs.readdir(LOGS_DIR).catch(() => []))
        .filter((entry): entry is string => typeof entry === "string")
    );
    const runStats = (
      await Promise.all(
        entries.map(async (entry) => {
          if (!entry.isDirectory()) return null;
          const stat = await fs.stat(path.join(RUNS_DIR, entry.name));
          return {
            id: entry.name,
            modifiedAt: stat.mtimeMs,
          };
        })
      )
    )
      .filter((entry): entry is { id: string; modifiedAt: number } => Boolean(entry))
      .sort((a, b) => b.modifiedAt - a.modifiedAt);

    const selectedRuns = limit === null ? runStats : runStats.slice(0, limit);

    const runs = await Promise.all(
      selectedRuns.map(async ({ id: runId, modifiedAt }): Promise<RunSummary> => {
        const [state, recordedRunParams] = await Promise.all([
          readRunStateListSnapshot(runId),
          readRecordedRunParams(runId),
        ]);
        const hasLog = logFileNames.has(`${runId}.log`);
        const lookupIds = runProcessLookupIdsFromStoredRunParams(runId, recordedRunParams);
        const displayedState = await inferDisplayedRunState({
          runId,
          state: (state?.state as string) || "UNKNOWN",
          activeRunIds,
          lookupIds,
        });

        return {
          id: runId,
          state: displayedState,
          gameId: (state?.game_id as string) || "",
          currentLevel: (state?.current_level as number) || 0,
          levelsCompleted: (state?.levels_completed as number) || 0,
          totalLevels: (state?.win_levels as number) || 7,
          totalSteps: (state?.total_steps as number) || 0,
          hasLog,
          canImportParams: hasLog || recordedRunParams !== null,
          canContinue:
            ["STOPPED", "FAILED", "GAME_OVER", "LOSS"].includes(displayedState.toUpperCase())
            && (hasLog || recordedRunParams !== null),
          modifiedAt,
        };
      })
    );

    return NextResponse.json(runs);
  } catch (error) {
    return NextResponse.json(
      { error: String(error) },
      { status: 500 }
    );
  }
}
