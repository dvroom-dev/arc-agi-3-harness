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

export { listActiveRunIds };
