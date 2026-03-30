import path from "node:path";

export const PROJECT_ROOT = path.resolve(process.cwd(), "..");
export const RUNS_DIR = path.join(PROJECT_ROOT, "runs");
export const SUPER_FLUX_ENTRYPOINT = "/home/dvroom/projs/super/src/bin/flux.ts";
export const HARNESS_FLUX_ENTRYPOINT = path.join(PROJECT_ROOT, "harness_flux.py");

export function runDir(runId: string): string {
  return path.join(RUNS_DIR, runId);
}
