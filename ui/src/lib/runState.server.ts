import { execFile } from "node:child_process";
import { promisify } from "node:util";
import fs from "node:fs/promises";
import path from "node:path";
import { LOGS_DIR } from "@/lib/paths";

const execFileAsync = promisify(execFile);

const TERMINAL_STATES = new Set(["WIN", "LOSS", "GAME_OVER", "FAILED", "STOPPED"]);

function isTerminalState(state: string): boolean {
  return TERMINAL_STATES.has((state || "").trim().toUpperCase());
}

interface ActiveRunProcess {
  pid: number;
  args: string;
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
  const processes: ActiveRunProcess[] = [];
  for (const line of psOutput.split(/\r?\n/)) {
    const match = line.match(/^\s*(\d+)\s+(.*)$/);
    if (!match) continue;
    const pid = Number.parseInt(match[1] ?? "", 10);
    const args = (match[2] ?? "").trim();
    if (!Number.isFinite(pid) || !args.includes("harness.py")) continue;
    processes.push({ pid, args });
  }
  return processes;
}

function runIdMatchesProcess(runId: string, args: string): boolean {
  const sessionName = args.match(/--session-name\s+([^\s]+)/)?.[1]?.trim();
  if (sessionName === runId) return true;
  return args.includes(`/runs/${runId}/`);
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

async function findHarnessProcessForRun(
  runId: string
): Promise<ActiveRunProcess | null> {
  try {
    const { stdout } = await execFileAsync("ps", ["-eo", "pid=,args="], {
      maxBuffer: 1024 * 1024 * 8,
    });
    return (
      parseHarnessProcesses(stdout).find((processInfo) =>
        runIdMatchesProcess(runId, processInfo.args)
      ) ?? null
    );
  } catch {
    return null;
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

async function stopRunProcess(runId: string): Promise<{
  status: "stopped" | "not-running" | "signal-sent";
  pid: number | null;
}> {
  const processInfo = await findHarnessProcessForRun(runId);
  if (!processInfo) {
    return { status: "not-running", pid: null };
  }

  process.kill(processInfo.pid, "SIGINT");
  if (await waitForExit(processInfo.pid, 2500)) {
    return { status: "stopped", pid: processInfo.pid };
  }

  process.kill(processInfo.pid, "SIGTERM");
  if (await waitForExit(processInfo.pid, 1500)) {
    return { status: "stopped", pid: processInfo.pid };
  }

  return { status: "signal-sent", pid: processInfo.pid };
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

export async function inferDisplayedRunState(args: {
  runId: string;
  state: string;
  activeRunIds?: Set<string>;
}): Promise<string> {
  const rawState = (args.state || "UNKNOWN").trim() || "UNKNOWN";
  if (isTerminalState(rawState)) return rawState;

  const activeRunIds = args.activeRunIds ?? (await listActiveRunIds());
  if (activeRunIds.has(args.runId)) return rawState;

  const logTail = await readLogTail(args.runId);
  return inferExitedStateFromLog(logTail);
}

export { findHarnessProcessForRun, listActiveRunIds, stopRunProcess };
