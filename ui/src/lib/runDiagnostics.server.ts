import fs from "fs/promises";
import path from "path";
import { runDir } from "@/lib/paths";

export type RunDiagnosticSource =
  | "harness_phase"
  | "repl_daemon"
  | "super_state"
  | "super_review";

export interface RunDiagnostic {
  at: string | null;
  source: RunDiagnosticSource;
  severity: "error" | "warning";
  summary: string;
  detail: string;
  file: string | null;
}

function cleanDetail(detail: string): string {
  return detail.replace(/\s+/g, " ").trim();
}

function parseTimestamp(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

async function readLatestHarnessPhaseError(runId: string): Promise<RunDiagnostic | null> {
  const phasesPath = path.join(runDir(runId), "telemetry", "harness_phases.ndjson");
  try {
    const raw = await fs.readFile(phasesPath, "utf-8");
    const entries = raw
      .split(/\r?\n/)
      .filter(Boolean)
      .map((line) => {
        try {
          return JSON.parse(line) as {
            timestamp?: unknown;
            ok?: unknown;
            error?: unknown;
            category?: unknown;
            name?: unknown;
          };
        } catch {
          return null;
        }
      })
      .filter((entry): entry is NonNullable<typeof entry> => Boolean(entry))
      .filter((entry) => entry.ok === false && typeof entry.error === "string" && entry.error.trim());
    const latest = entries.at(-1);
    if (!latest) return null;
    const category = typeof latest.category === "string" ? latest.category.trim() : "phase";
    const name = typeof latest.name === "string" ? latest.name.trim() : "unknown";
    const message = cleanDetail(String(latest.error));
    return {
      at: parseTimestamp(latest.timestamp),
      source: "harness_phase",
      severity: "error",
      summary: `${category}.${name} failed`,
      detail: message,
      file: phasesPath,
    };
  } catch {
    return null;
  }
}

async function readLatestReplDaemonError(runId: string): Promise<RunDiagnostic | null> {
  const sessionsDir = path.join(runDir(runId), "supervisor", "arc", "repl-sessions");
  let files: string[] = [];
  try {
    const sessionEntries = await fs.readdir(sessionsDir);
    files = sessionEntries.map((entry) => path.join(sessionsDir, entry, "daemon.lifecycle.jsonl"));
  } catch {
    return null;
  }
  const diagnostics: RunDiagnostic[] = [];
  for (const file of files) {
    try {
      const raw = await fs.readFile(file, "utf-8");
      for (const line of raw.split(/\r?\n/)) {
        if (!line) continue;
        let payload: {
          event?: unknown;
          error?: unknown;
          timeout_s?: unknown;
          ts_unix?: unknown;
        } | null = null;
        try {
          payload = JSON.parse(line);
        } catch {
          continue;
        }
        const event = typeof payload?.event === "string" ? payload.event : "";
        if (event === "daemon_fatal_exception" && typeof payload?.error === "string") {
          diagnostics.push({
            at:
              typeof payload.ts_unix === "number"
                ? new Date(payload.ts_unix * 1000).toISOString()
                : null,
            source: "repl_daemon",
            severity: "error",
            summary: "ARC REPL daemon fatal exception",
            detail: cleanDetail(payload.error),
            file,
          });
        } else if (event === "wait_timeout") {
          diagnostics.push({
            at:
              typeof payload?.ts_unix === "number"
                ? new Date(payload.ts_unix * 1000).toISOString()
                : null,
            source: "repl_daemon",
            severity: "warning",
            summary: "ARC REPL daemon startup timeout",
            detail: cleanDetail(
              `waited ${String(payload?.timeout_s ?? "?")}s for daemon.ready after restart`
            ),
            file,
          });
        }
      }
    } catch {
      continue;
    }
  }
  return diagnostics
    .sort((a, b) => {
      if (a.severity !== b.severity) {
        return a.severity === "error" ? -1 : 1;
      }
      return Date.parse(b.at || "") - Date.parse(a.at || "");
    })
    .at(0) ?? null;
}

async function readLatestSuperStateError(runId: string): Promise<RunDiagnostic | null> {
  const statePath = path.join(runDir(runId), "super", "state.json");
  try {
    const payload = JSON.parse(await fs.readFile(statePath, "utf-8")) as {
      updatedAt?: unknown;
      lastStopReasons?: unknown;
      lastStopDetails?: unknown;
    };
    const reasons = Array.isArray(payload.lastStopReasons)
      ? payload.lastStopReasons.filter((value): value is string => typeof value === "string" && value.trim())
      : [];
    const details = Array.isArray(payload.lastStopDetails)
      ? payload.lastStopDetails.filter((value): value is string => typeof value === "string" && value.trim())
      : [];
    if (!reasons.some((reason) => /error/i.test(reason)) && details.length === 0) {
      return null;
    }
    const summary = reasons.length > 0 ? `Supervisor stop: ${reasons.join(", ")}` : "Supervisor stop";
    const detail = details.length > 0 ? cleanDetail(details.join(" | ")) : summary;
    return {
      at: parseTimestamp(payload.updatedAt),
      source: "super_state",
      severity: reasons.some((reason) => /error/i.test(reason)) ? "error" : "warning",
      summary,
      detail,
      file: statePath,
    };
  } catch {
    return null;
  }
}

async function readLatestSupervisorReviewError(runId: string): Promise<RunDiagnostic | null> {
  const conversationsDir = path.join(runDir(runId), ".ai-supervisor", "conversations");
  try {
    const conversationEntries = await fs.readdir(conversationsDir, { withFileTypes: true });
    const diagnostics: RunDiagnostic[] = [];
    for (const entry of conversationEntries) {
      if (!entry.isDirectory()) continue;
      const reviewsDir = path.join(conversationsDir, entry.name, "reviews");
      let reviewFiles: string[] = [];
      try {
        reviewFiles = await fs.readdir(reviewsDir);
      } catch {
        continue;
      }
      for (const fileName of reviewFiles) {
        if (!fileName.endsWith("_response.txt")) continue;
        const file = path.join(reviewsDir, fileName);
        try {
          const [raw, stat] = await Promise.all([fs.readFile(file, "utf-8"), fs.stat(file)]);
          const payload = JSON.parse(raw) as { error_type?: unknown; error?: unknown; message?: unknown };
          const errorType = typeof payload.error_type === "string" ? payload.error_type.trim() : "";
          if (!errorType) continue;
          const detail =
            typeof payload.error === "string" && payload.error.trim()
              ? payload.error
              : typeof payload.message === "string" && payload.message.trim()
                ? payload.message
                : errorType;
          diagnostics.push({
            at: stat.mtime.toISOString(),
            source: "super_review",
            severity: "error",
            summary: `Supervisor review error: ${errorType}`,
            detail: cleanDetail(detail),
            file,
          });
        } catch {
          continue;
        }
      }
    }
    return diagnostics.sort((a, b) => Date.parse(b.at || "") - Date.parse(a.at || "")).at(0) ?? null;
  } catch {
    return null;
  }
}

export async function readRunDiagnostics(runId: string): Promise<RunDiagnostic[]> {
  const diagnostics = await Promise.all([
    readLatestHarnessPhaseError(runId),
    readLatestReplDaemonError(runId),
    readLatestSuperStateError(runId),
    readLatestSupervisorReviewError(runId),
  ]);
  return diagnostics
    .filter((entry): entry is RunDiagnostic => Boolean(entry))
    .sort((a, b) => {
      if (a.severity !== b.severity) {
        return a.severity === "error" ? -1 : 1;
      }
      return Date.parse(b.at || "") - Date.parse(a.at || "");
    });
}

export async function readLatestRunDiagnostic(runId: string): Promise<RunDiagnostic | null> {
  return (await readRunDiagnostics(runId)).at(0) ?? null;
}
