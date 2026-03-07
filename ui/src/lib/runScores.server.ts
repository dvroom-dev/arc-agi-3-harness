import fs from "fs";
import path from "path";
import { execFile } from "child_process";
import { promisify } from "util";
import { PROJECT_ROOT } from "@/lib/paths";
import type { RunScorePayload } from "@/lib/types";

const execFileAsync = promisify(execFile);

function resolvePythonExecutable(): string {
  const projectPython = path.join(PROJECT_ROOT, ".venv", "bin", "python");
  return fs.existsSync(projectPython) ? projectPython : "python";
}

function formatExecError(error: unknown): string {
  if (error && typeof error === "object") {
    const withStreams = error as {
      message?: string;
      stdout?: string;
      stderr?: string;
    };
    const detail = (withStreams.stderr || withStreams.stdout || withStreams.message || "unknown error").trim();
    return detail || "unknown error";
  }
  return String(error);
}

export async function readRunScores(runId: string): Promise<RunScorePayload> {
  const scriptPath = path.join(PROJECT_ROOT, "ui_run_scores.py");
  try {
    const { stdout } = await execFileAsync(
      resolvePythonExecutable(),
      [scriptPath, "--run-id", runId],
      {
        cwd: PROJECT_ROOT,
        maxBuffer: 10 * 1024 * 1024,
      }
    );
    return JSON.parse(stdout) as RunScorePayload;
  } catch (error) {
    throw new Error(formatExecError(error));
  }
}
