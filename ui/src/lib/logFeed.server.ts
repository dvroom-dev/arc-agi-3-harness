import fs from "fs/promises";
import path from "path";
import { readRunDiagnostics } from "@/lib/runDiagnostics.server";
import { LOGS_DIR } from "@/lib/paths";
import { readRawEventTail } from "@/lib/runArtifacts.server";
import type { LogFeedEntry, LogFeedPayload, LogFeedStream } from "@/lib/types";

function isErrorLine(line: string) {
  return /\b(error|fatal|traceback|exception|game_over)\b/i.test(line);
}

function isWarningLine(line: string) {
  return /\b(warn|warning)\b/i.test(line);
}

function classifyLine(line: string): Pick<LogFeedEntry, "severity" | "label"> {
  if (isErrorLine(line)) {
    return { severity: "error", label: "ERROR" };
  }
  if (isWarningLine(line)) {
    return { severity: "warning", label: "WARN" };
  }
  if (line.includes("WIN") || line.includes("level_complete")) {
    return { severity: "success", label: "OK" };
  }
  if (line.includes("[harness]")) {
    return { severity: "info", label: "HARNESS" };
  }
  if (line.includes("[super]")) {
    return { severity: "info", label: "SUPER" };
  }
  if (line.includes("[raw")) {
    return { severity: "info", label: "RAW" };
  }
  if (line.includes("keepalive")) {
    return { severity: "info", label: "KEEPALIVE" };
  }
  return { severity: "info", label: "LOG" };
}

function toEntries(
  source: LogFeedEntry["source"],
  lines: string[]
): LogFeedEntry[] {
  return lines.map((text, index) => {
    const tone = classifyLine(text);
    return {
      id: `${source}:${index}`,
      source,
      severity: tone.severity,
      label: tone.label,
      text,
    };
  });
}

function summarizeCounts(streams: LogFeedStream[]) {
  let errorCount = 0;
  let warningCount = 0;
  for (const stream of streams) {
    for (const entry of stream.entries) {
      if (entry.severity === "error") errorCount += 1;
      if (entry.severity === "warning") warningCount += 1;
    }
  }
  return { errorCount, warningCount };
}

export async function readLogFeed(
  runId: string,
  tail = 200
): Promise<LogFeedPayload> {
  const rawTail = Math.max(40, Math.min(120, Math.floor(tail / 4)));
  const streams: LogFeedStream[] = [];
  let error: string | null = null;

  try {
    const logFiles = await fs.readdir(LOGS_DIR);
    const matching = logFiles.filter((file) => file.includes(runId)).sort();
    const logFile = matching.at(-1) ?? null;
    if (logFile) {
      const content = await fs.readFile(path.join(LOGS_DIR, logFile), "utf-8");
      const allLines = content.split("\n");
      const lines = tail > 0 ? allLines.slice(-tail) : allLines;
      streams.push({
        id: "harness",
        title: logFile,
        file: logFile,
        totalLines: allLines.length,
        entries: toEntries("harness", lines),
      });
    }
  } catch (readError) {
    error = readError instanceof Error ? readError.message : String(readError);
  }

  const rawEvents = await readRawEventTail(runId, rawTail);
  if (rawEvents.lines.length > 0 || rawEvents.source) {
    streams.push({
      id: "super_raw",
      title: rawEvents.source || "raw events",
      file: rawEvents.source,
      entries: toEntries("super_raw", rawEvents.lines),
    });
  }

  const diagnostics = await readRunDiagnostics(runId);
  if (diagnostics.length > 0) {
    streams.unshift({
      id: "diagnostics",
      title: "diagnostics",
      file: diagnostics[0]?.file ?? null,
      entries: diagnostics.map((entry, index) => ({
        id: `diagnostics:${index}`,
        source: "diagnostics",
        severity: entry.severity,
        label: entry.severity === "error" ? "DIAG" : "WARN",
        text: `${entry.at ?? "unknown time"} ${entry.summary}: ${entry.detail}`,
      })),
    });
  }

  const counts = summarizeCounts(streams);
  return {
    streams,
    errorCount: counts.errorCount,
    warningCount: counts.warningCount,
    error,
  };
}
