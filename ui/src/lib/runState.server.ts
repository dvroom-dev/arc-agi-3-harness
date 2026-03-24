import { execFile } from "node:child_process";
import { promisify } from "node:util";
import fs from "node:fs/promises";
import path from "node:path";
import { LOGS_DIR } from "@/lib/paths";
import { readLatestRunDiagnostic } from "@/lib/runDiagnostics.server";
import { readStoredRunParams } from "@/lib/runParams.server";
import type { StoredRunParams } from "@/lib/runParams";
import { readRunStateSnapshot } from "@/lib/runStateSnapshot.server";
import type { RunStatusSummary } from "@/lib/types";

const execFileAsync = promisify(execFile);

const TERMINAL_STATES = new Set(["WIN", "LOSS", "GAME_OVER", "FAILED", "STOPPED"]);
const CONTINUABLE_STATES = new Set(["STOPPED", "FAILED", "GAME_OVER", "LOSS"]);
const PROVIDER_ERROR_PATTERNS = [
  /provider[_\s-]*error/i,
  /provider execution error/i,
  /usage limit/i,
  /rate limit/i,
  /quota/i,
  /context window/i,
  /remote compact task/i,
];

function isTerminalState(state: string): boolean {
  return TERMINAL_STATES.has((state || "").trim().toUpperCase());
}

function isProviderErrorDetail(detail: string | null): boolean {
  if (!detail) return false;
  return PROVIDER_ERROR_PATTERNS.some((pattern) => pattern.test(detail));
}

interface ActiveRunProcess {
  pid: number;
  args: string;
}

function parseProcesses(psOutput: string): ActiveRunProcess[] {
  const processes: ActiveRunProcess[] = [];
  for (const line of psOutput.split(/\r?\n/)) {
    const match = line.match(/^\s*(\d+)\s+(.*)$/);
    if (!match) continue;
    const pid = Number.parseInt(match[1] ?? "", 10);
    const args = (match[2] ?? "").trim();
    if (!Number.isFinite(pid) || !args) continue;
    processes.push({ pid, args });
  }
  return processes;
}

function parseSessionNameFromCommandPreview(commandPreview: string): string | null {
  const match = commandPreview.match(/--session-name\s+([^\s]+)/);
  return match?.[1]?.trim() || null;
}

export function runProcessLookupIdsFromStoredRunParams(
  runId: string,
  storedRunParams: StoredRunParams | null
): Set<string> {
  const lookupIds = new Set<string>([runId]);
  const explicitSessionName = storedRunParams?.params.sessionName?.trim();
  if (explicitSessionName) {
    lookupIds.add(explicitSessionName);
  }
  const commandPreviewSessionName = storedRunParams?.commandPreview
    ? parseSessionNameFromCommandPreview(storedRunParams.commandPreview)
    : null;
  if (commandPreviewSessionName) {
    lookupIds.add(commandPreviewSessionName);
  }
  return lookupIds;
}

async function loadRunProcessLookupIds(runId: string): Promise<Set<string>> {
  return runProcessLookupIdsFromStoredRunParams(runId, await readStoredRunParams(runId));
}

function parseActiveRunIds(psOutput: string): Set<string> {
  const runIds = new Set<string>();
  for (const line of psOutput.split(/\r?\n/)) {
    if (!line.includes("harness.py") && !line.includes("run-config.ts")) continue;

    for (const match of line.matchAll(/\/runs\/([^/\s]+)\//g)) {
      runIds.add(match[1]);
    }

    const sessionName = line.match(/--session-name\s+([^\s]+)/)?.[1]?.trim();
    if (sessionName) runIds.add(sessionName);
  }
  return runIds;
}

function parseHarnessProcesses(psOutput: string): ActiveRunProcess[] {
  return parseProcesses(psOutput).filter((processInfo) =>
    processInfo.args.includes("harness.py")
  );
}

function runIdMatchesProcess(runId: string, args: string): boolean {
  const sessionName = args.match(/--session-name\s+([^\s]+)/)?.[1]?.trim();
  if (sessionName === runId) return true;
  return args.includes(`/runs/${runId}/`);
}

function anyRunIdMatchesProcess(runIds: Iterable<string>, args: string): boolean {
  for (const runId of runIds) {
    if (runIdMatchesProcess(runId, args)) return true;
  }
  return false;
}

async function listActiveRunIds(): Promise<Set<string>> {
  try {
    const { stdout } = await execFileAsync("ps", ["-eo", "args="], {
      maxBuffer: 1024 * 1024 * 8,
    });
    return parseActiveRunIds(stdout);
  } catch {
    return new Set<string>();
  }
}

async function listMatchingRunProcesses(
  lookupIds: Iterable<string>
): Promise<ActiveRunProcess[]> {
  try {
    const { stdout } = await execFileAsync("ps", ["-eo", "pid=,args="], {
      maxBuffer: 1024 * 1024 * 8,
    });
    return parseProcesses(stdout).filter((processInfo) =>
      anyRunIdMatchesProcess(lookupIds, processInfo.args)
    );
  } catch {
    return [];
  }
}

async function findHarnessProcessForRun(
  runId: string
): Promise<ActiveRunProcess | null> {
  const lookupIds = await loadRunProcessLookupIds(runId);
  try {
    const { stdout } = await execFileAsync("ps", ["-eo", "pid=,args="], {
      maxBuffer: 1024 * 1024 * 8,
    });
    return (
      parseHarnessProcesses(stdout).find((processInfo) =>
        anyRunIdMatchesProcess(lookupIds, processInfo.args)
      ) ?? null
    );
  } catch {
    return null;
  }
}

function signalPid(pid: number, signal: NodeJS.Signals): boolean {
  try {
    process.kill(pid, signal);
    return true;
  } catch {
    return false;
  }
}

function pidExists(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

async function waitForExit(pid: number, timeoutMs: number): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (!pidExists(pid)) return true;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  return !pidExists(pid);
}

async function terminateRemainingRunProcesses(
  lookupIds: Iterable<string>,
  excludedPids: Iterable<number> = []
): Promise<boolean> {
  const excluded = new Set(excludedPids);
  let remaining = (await listMatchingRunProcesses(lookupIds)).filter(
    (processInfo) => !excluded.has(processInfo.pid)
  );
  if (remaining.length === 0) return true;

  for (const processInfo of remaining) {
    signalPid(processInfo.pid, "SIGTERM");
  }
  await new Promise((resolve) => setTimeout(resolve, 500));
  remaining = remaining.filter((processInfo) => pidExists(processInfo.pid));
  if (remaining.length === 0) return true;

  for (const processInfo of remaining) {
    signalPid(processInfo.pid, "SIGKILL");
  }
  await new Promise((resolve) => setTimeout(resolve, 250));
  return remaining.every((processInfo) => !pidExists(processInfo.pid));
}

async function stopRunProcess(runId: string): Promise<{
  status: "stopped" | "not-running" | "signal-sent";
  pid: number | null;
}> {
  const lookupIds = await loadRunProcessLookupIds(runId);
  const processInfo = await findHarnessProcessForRun(runId);
  if (!processInfo) {
    const cleanedUp = await terminateRemainingRunProcesses(lookupIds);
    return cleanedUp
      ? { status: "stopped", pid: null }
      : { status: "not-running", pid: null };
  }

  signalPid(processInfo.pid, "SIGINT");
  if (await waitForExit(processInfo.pid, 2500)) {
    const cleanedUp = await terminateRemainingRunProcesses(lookupIds, [processInfo.pid]);
    return {
      status: cleanedUp ? "stopped" : "signal-sent",
      pid: processInfo.pid,
    };
  }

  signalPid(processInfo.pid, "SIGTERM");
  if (await waitForExit(processInfo.pid, 1500)) {
    const cleanedUp = await terminateRemainingRunProcesses(lookupIds, [processInfo.pid]);
    return {
      status: cleanedUp ? "stopped" : "signal-sent",
      pid: processInfo.pid,
    };
  }

  await terminateRemainingRunProcesses(lookupIds, [processInfo.pid]);
  return {
    status: "signal-sent",
    pid: processInfo.pid,
  };
}

async function readLogTail(runId: string): Promise<string> {
  const logPath = path.join(LOGS_DIR, `${runId}.log`);
  try {
    const raw = await fs.readFile(logPath, "utf-8");
    return raw.slice(-64_000);
  } catch {
    return "";
  }
}

function inferExitedStateFromLog(logTail: string): string {
  if (
    logTail.includes("[harness] FATAL:") ||
    logTail.includes("Traceback (most recent call last):") ||
    logTail.includes("RuntimeError:")
  ) {
    return "FAILED";
  }
  if (
    logTail.includes("[harness] max turns (") ||
    logTail.includes("[harness] max GAME_OVER auto-resets reached") ||
    logTail.includes("[harness] GAME_OVER auto-reset disabled") ||
    logTail.includes("[harness] session files:")
  ) {
    return "STOPPED";
  }
  return "STOPPED";
}

function cleanDetail(detail: string): string {
  return detail.replace(/\s+/g, " ").trim();
}

function extractHarnessFailureDetail(logTail: string): string | null {
  const lines = logTail
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);

  for (let index = lines.length - 1; index >= 0; index -= 1) {
    const line = lines[index]!;
    if (line.startsWith("[super] Error:")) {
      return cleanDetail(line.replace(/^\[super\] Error:\s*/, ""));
    }
  }

  for (let index = lines.length - 1; index >= 0; index -= 1) {
    const line = lines[index]!;
    if (line.startsWith("[harness] FATAL:")) {
      return cleanDetail(line.replace(/^\[harness\] FATAL:\s*/, ""));
    }
  }

  for (let index = lines.length - 1; index >= 0; index -= 1) {
    const line = lines[index]!;
    if (/^(RuntimeError|ValueError|AssertionError|TypeError|Error):/.test(line)) {
      return cleanDetail(line.replace(/^[A-Za-z]+Error:\s*/, ""));
    }
  }

  return null;
}

function summarizeDisplayedState(state: string, active: boolean) {
  const normalized = (state || "UNKNOWN").trim().toUpperCase() || "UNKNOWN";
  if (active && !isTerminalState(normalized)) {
    return {
      statusLabel: "Running",
      category: "running",
      categoryLabel: "Running",
    } as const;
  }

  switch (normalized) {
    case "WIN":
      return {
        statusLabel: "Success",
        category: "success",
        categoryLabel: "Success",
      } as const;
    case "STOPPED":
      return {
        statusLabel: "Stopped",
        category: "stopped",
        categoryLabel: "Stopped",
      } as const;
    case "GAME_OVER":
      return {
        statusLabel: "Game Over",
        category: "game_over",
        categoryLabel: "Game Over",
      } as const;
    case "LOSS":
      return {
        statusLabel: "Loss",
        category: "loss",
        categoryLabel: "Loss",
      } as const;
    case "FAILED":
      return {
        statusLabel: "Failed",
        category: "unknown",
        categoryLabel: "Unknown Failure",
      } as const;
    default:
      return {
        statusLabel: normalized === "UNKNOWN" ? "Unknown" : normalized,
        category: "unknown",
        categoryLabel: "Unknown",
      } as const;
  }
}

export async function readRunStatusSummary(runId: string): Promise<RunStatusSummary> {
  const [stateSnapshot, storedRunParams] = await Promise.all([
    readRunStateSnapshot(runId),
    readStoredRunParams(runId),
  ]);
  const rawState = typeof stateSnapshot?.state === "string" ? stateSnapshot.state : "UNKNOWN";
  const lookupIds = runProcessLookupIdsFromStoredRunParams(runId, storedRunParams);
  const activeRunIds = await listActiveRunIds();
  const displayedState = await inferDisplayedRunState({
    runId,
    state: rawState,
    activeRunIds,
    lookupIds,
  });
  const active = Array.from(lookupIds).some((lookupId) => activeRunIds.has(lookupId));
  const logTail = await readLogTail(runId);
  const harnessFailureDetail = extractHarnessFailureDetail(logTail);
  const latestDiagnostic = await readLatestRunDiagnostic(runId);
  const hasLog = await fs
    .access(path.join(LOGS_DIR, `${runId}.log`))
    .then(() => true)
    .catch(() => false);
  const canContinue =
    !active &&
    CONTINUABLE_STATES.has(displayedState.toUpperCase()) &&
    (hasLog || storedRunParams !== null);

  const base = summarizeDisplayedState(displayedState, active);
  let category = base.category;
  let categoryLabel = base.categoryLabel;
  let detail: string | null = null;

  if (displayedState.toUpperCase() === "FAILED") {
    if (latestDiagnostic?.severity === "error") {
      detail = `${latestDiagnostic.summary}: ${latestDiagnostic.detail}`;
      if (isProviderErrorDetail(latestDiagnostic.detail)) {
        category = "provider_error";
        categoryLabel = "Provider Error";
      } else {
        category = "harness_error";
        categoryLabel = "Harness Error";
      }
    } else if (harnessFailureDetail && !isProviderErrorDetail(harnessFailureDetail)) {
      category = "harness_error";
      categoryLabel = "Harness Error";
      detail = harnessFailureDetail;
    } else if (harnessFailureDetail) {
      category = "provider_error";
      categoryLabel = "Provider Error";
      detail = harnessFailureDetail;
    } else {
      category = "unknown";
      categoryLabel = "Unknown Failure";
    }
  } else if (displayedState.toUpperCase() === "STOPPED") {
    detail =
      latestDiagnostic?.severity === "error"
        ? `${latestDiagnostic.summary}: ${latestDiagnostic.detail}`
        : null;
  } else if (displayedState.toUpperCase() === "GAME_OVER") {
    detail = "The ARC run ended in GAME_OVER.";
  } else if (displayedState.toUpperCase() === "LOSS") {
    detail = "The ARC run ended in LOSS.";
  }

  return {
    runId,
    state: displayedState,
    statusLabel: base.statusLabel,
    active,
    category,
    categoryLabel,
    detail,
    canContinue,
    action: active && !isTerminalState(displayedState) ? "stop" : canContinue ? "continue" : null,
  };
}

export async function inferDisplayedRunState(args: {
  runId: string;
  state: string;
  activeRunIds?: Set<string>;
  lookupIds?: Iterable<string>;
}): Promise<string> {
  const rawState = (args.state || "UNKNOWN").trim() || "UNKNOWN";
  if (isTerminalState(rawState)) return rawState;

  const activeRunIds = args.activeRunIds ?? (await listActiveRunIds());
  const lookupIds = args.lookupIds
    ? Array.from(args.lookupIds)
    : Array.from(await loadRunProcessLookupIds(args.runId));
  if (lookupIds.some((lookupId) => activeRunIds.has(lookupId))) return rawState;

  const logTail = await readLogTail(args.runId);
  return inferExitedStateFromLog(logTail);
}

export { findHarnessProcessForRun, listActiveRunIds, stopRunProcess };
