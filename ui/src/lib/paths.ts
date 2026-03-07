import path from "path";

// Project root is one level up from ui/
export const PROJECT_ROOT = path.resolve(process.cwd(), "..");
export const RUNS_DIR = path.join(PROJECT_ROOT, "runs");
export const LOGS_DIR = path.join(PROJECT_ROOT, "logs");
export const CTXS_DIR = path.join(PROJECT_ROOT, ".ctxs");

export function runDir(runId: string) {
  return path.join(RUNS_DIR, runId);
}

export function arcStateDir(runId: string) {
  return path.join(runDir(runId), "supervisor", "arc");
}

export function agentDir(runId: string) {
  return path.join(runDir(runId), "agent");
}

export function ctxDir(runId: string) {
  return path.join(CTXS_DIR, runId);
}
