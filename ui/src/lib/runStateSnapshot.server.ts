import fs from "node:fs/promises";
import path from "node:path";
import { arcStateDir } from "@/lib/paths";

interface HistoryEventRecord {
  kind?: string;
}

interface StatePayload {
  total_steps?: number;
  current_attempt_steps?: number;
  total_resets?: number;
  [key: string]: unknown;
}

async function readJsonFile(filePath: string): Promise<Record<string, unknown> | null> {
  try {
    const raw = await fs.readFile(filePath, "utf-8");
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed as Record<string, unknown> : null;
  } catch {
    return null;
  }
}

export async function readRunStateSnapshot(runId: string): Promise<StatePayload | null> {
  return readRunStateSnapshotWithOptions(runId, { includeHistoryCounts: true });
}

export async function readRunStateListSnapshot(runId: string): Promise<StatePayload | null> {
  return readRunStateSnapshotWithOptions(runId, { includeHistoryCounts: false });
}

async function readRunStateSnapshotWithOptions(
  runId: string,
  options: { includeHistoryCounts: boolean }
): Promise<StatePayload | null> {
  const arcDir = arcStateDir(runId);
  const state = await readJsonFile(path.join(arcDir, "state.json"));
  if (!state) return null;

  if (!options.includeHistoryCounts) {
    return state;
  }

  const history = await readJsonFile(path.join(arcDir, "tool-engine-history.json"));
  const events = Array.isArray(history?.events) ? (history.events as HistoryEventRecord[]) : [];
  const totalSteps = events.filter((event) => String(event?.kind || "").trim() === "step").length;
  const totalResets = events.filter((event) => String(event?.kind || "").trim() === "reset").length;

  const merged: StatePayload = {
    ...state,
    total_steps:
      typeof state.total_steps === "number" && state.total_steps >= totalSteps
        ? state.total_steps
        : totalSteps,
    current_attempt_steps:
      typeof state.current_attempt_steps === "number"
        ? state.current_attempt_steps
        : typeof state.total_steps === "number"
          ? state.total_steps
          : totalSteps,
    total_resets:
      typeof state.total_resets === "number" && state.total_resets >= totalResets
        ? state.total_resets
        : totalResets,
  };

  return merged;
}
