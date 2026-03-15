import fs from "fs/promises";
import path from "path";
import { spawn } from "child_process";
import {
  CTXS_DIR,
  LOGS_DIR,
  PROJECT_ROOT,
  RUNS_DIR,
  ctxDir,
  runDir,
} from "@/lib/paths";
import {
  DEFAULT_RUN_LAUNCH_PARAMS,
  normalizeRunLaunchParams,
  resolveRequestedGameIds,
  summarizeRunLaunchParams,
  type RunLaunchParams,
  type StoredRunParams,
} from "@/lib/runParams";

const RECENT_PARAMS_PATH = path.join(PROJECT_ROOT, ".ui-run-launcher.json");
const RUN_PARAMS_FILENAME = "run-params.json";
const RECENT_PARAMS_SCHEMA_VERSION = "ui.recent-run-params.v2";

function timestampSessionName() {
  const now = new Date();
  const pad = (value: number) => String(value).padStart(2, "0");
  return [
    now.getFullYear(),
    pad(now.getMonth() + 1),
    pad(now.getDate()),
    "_",
    pad(now.getHours()),
    pad(now.getMinutes()),
    pad(now.getSeconds()),
  ].join("");
}

function sanitizeSessionName(value: string): string {
  return value.replace(/[^A-Za-z0-9_.-]+/g, "-").replace(/^-+|-+$/g, "");
}

function sessionNameForGame(sessionBase: string, gameId: string, index: number): string {
  const safeGame = sanitizeSessionName(gameId) || `game-${String(index).padStart(2, "0")}`;
  return `${sessionBase}-${String(index).padStart(2, "0")}-${safeGame}`;
}

function buildHarnessArgs(params: RunLaunchParams): string[] {
  const args: string[] = [];
  args.push("--game-id", params.gameId);
  if (params.gameIds.trim()) args.push("--game-ids", params.gameIds.trim());
  if (params.maxTurns !== null) args.push("--max-turns", String(params.maxTurns));
  args.push("--operation-mode", params.operationMode);
  if (params.sessionName) args.push("--session-name", params.sessionName);
  if (params.verbose) args.push("--verbose");
  if (params.openScorecard) args.push("--open-scorecard");
  if (params.scorecardId) args.push("--scorecard-id", params.scorecardId);
  if (params.provider) args.push("--provider", params.provider);
  if (params.noSupervisor) args.push("--no-supervisor");
  if (params.exploreInputs) args.push("--explore-inputs");
  args.push("--max-game-over-resets", String(params.maxGameOverResets));
  args.push("--arc-backend", params.arcBackend);
  if (params.arcBaseUrl) args.push("--arc-base-url", params.arcBaseUrl);
  if (params.scorecardOwnerCheckId) {
    args.push("--scorecard-owner-check-id", params.scorecardOwnerCheckId);
  }
  if (params.scorecardSessionPreflight) args.push("--scorecard-session-preflight");
  if (params.scoreAfterSolve) args.push("--score-after-solve");
  if (params.scoreAfterSolveStartMode) {
    args.push("--score-after-solve-start-mode", params.scoreAfterSolveStartMode);
  }
  return args;
}

function buildCommandPreview(params: RunLaunchParams): string {
  return ["python", "harness.py", ...buildHarnessArgs(params)].join(" ");
}

function validateRunLaunchParams(params: RunLaunchParams) {
  const gameIds = resolveRequestedGameIds(params);
  if (!params.gameId.trim()) {
    throw new Error("gameId is required.");
  }
  if (params.openScorecard && params.scorecardId) {
    throw new Error("Use either openScorecard or scorecardId, not both.");
  }
  if (
    (params.openScorecard || params.scorecardId || params.scoreAfterSolve)
    && params.operationMode !== "ONLINE"
  ) {
    throw new Error("Scorecard flows require operationMode=ONLINE.");
  }
  if (params.scoreAfterSolve && (params.openScorecard || params.scorecardId)) {
    throw new Error("scoreAfterSolve cannot be combined with openScorecard or scorecardId.");
  }
  if (params.scoreAfterSolve && gameIds.length !== 1) {
    throw new Error("scoreAfterSolve currently supports exactly one game.");
  }
}

async function readJsonFile<T>(filePath: string): Promise<T | null> {
  try {
    return JSON.parse(await fs.readFile(filePath, "utf-8")) as T;
  } catch {
    return null;
  }
}

async function ensureDir(dirPath: string) {
  await fs.mkdir(dirPath, { recursive: true });
}

async function writeJsonFile(filePath: string, value: unknown) {
  await ensureDir(path.dirname(filePath));
  await fs.writeFile(filePath, JSON.stringify(value, null, 2) + "\n", "utf-8");
}

function parseMatch(text: string, pattern: RegExp): string | null {
  const match = text.match(pattern);
  return match?.[1]?.trim() || null;
}

function parseLastMatch(text: string, pattern: RegExp): string | null {
  const matches = Array.from(text.matchAll(pattern));
  const value = matches.at(-1)?.[1];
  return typeof value === "string" ? value.trim() : null;
}

function parseLastTuple(text: string, pattern: RegExp): string[] | null {
  const matches = Array.from(text.matchAll(pattern));
  const groups = matches.at(-1);
  return groups ? groups.slice(1).map((value) => value?.trim() || "") : null;
}

async function findLogPathForRun(runId: string): Promise<string | null> {
  const exactPath = path.join(LOGS_DIR, `${runId}.log`);
  try {
    await fs.access(exactPath);
    return exactPath;
  } catch {
    // Fall through to fuzzy match for older logs.
  }

  try {
    const logFiles = await fs.readdir(LOGS_DIR);
    const fuzzy = logFiles.find((file) => file.includes(runId));
    return fuzzy ? path.join(LOGS_DIR, fuzzy) : null;
  } catch {
    return null;
  }
}

async function inferParamsFromLog(runId: string): Promise<StoredRunParams | null> {
  const logPath = await findLogPathForRun(runId);
  if (!logPath) return null;

  let logText = "";
  try {
    logText = await fs.readFile(logPath, "utf-8");
  } catch {
    return null;
  }

  const uniqueGames = Array.from(
    new Set(
      Array.from(logText.matchAll(/^\[harness\] game: ([^\s]+) \(\d+\/\d+\)$/gm))
        .map((match) => match[1]?.trim())
        .filter((value): value is string => Boolean(value))
    )
  );

  const scorecard = await readJsonFile<{ scorecard_id?: string; operation_mode?: string }>(
    path.join(ctxDir(runId), "scorecard.json")
  );

  const scorecardTuple = parseLastTuple(
    logText,
    /^\[harness\] scorecard: ([^\s]+) \((created_new|reused_existing)\)$/gm
  );
  const superCommand = parseLastMatch(logText, /^\[harness\] running: (super .+)$/gm) || "";
  const scoreAfterSolveStartMode = parseLastMatch(
    logText,
    /^\[harness\] running: super new .* --start-mode ([^\s]+).*$/gm
  );
  const runtimeProvider = parseMatch(logText, /agent_provider=(claude|codex|mock)\b/);
  const commandProvider = parseMatch(superCommand, /--provider\s+(claude|codex|mock)\b/);
  const maxTurns = parseLastMatch(logText, /^\[harness\] max turns \((\d+)\) reached$/gm);
  const maxGameOverResets = parseLastMatch(
    logText,
    /^\[harness\] GAME_OVER detected .* limit=(\d+)$/gm
  );

  const inferred = normalizeRunLaunchParams({
    ...DEFAULT_RUN_LAUNCH_PARAMS,
    gameId: uniqueGames[0] || DEFAULT_RUN_LAUNCH_PARAMS.gameId,
    gameIds: uniqueGames.length > 1 ? uniqueGames.join(" ") : "",
    maxTurns: maxTurns ? Number.parseInt(maxTurns, 10) : null,
    operationMode:
      /NOTE: operation-mode OFFLINE/i.test(logText)
        ? "OFFLINE"
        : scorecardTuple || scorecard?.operation_mode === "ONLINE"
          ? "ONLINE"
          : DEFAULT_RUN_LAUNCH_PARAMS.operationMode,
    sessionName: "",
    openScorecard: scorecardTuple?.[1] === "created_new",
    scorecardId:
      scorecardTuple?.[1] === "reused_existing"
        ? scorecardTuple[0]
        : scorecardTuple
          ? ""
          : scorecard?.scorecard_id || "",
    provider: (commandProvider || runtimeProvider || "") as RunLaunchParams["provider"],
    noSupervisor: /(?:^|\s)--no-supervisor(?:\s|$)/.test(superCommand),
    exploreInputs: /\[harness\] input exploration is enabled\b/i.test(logText),
    maxGameOverResets: maxGameOverResets
      ? Number.parseInt(maxGameOverResets, 10)
      : DEFAULT_RUN_LAUNCH_PARAMS.maxGameOverResets,
    arcBackend:
      parseMatch(logText, /^\[harness\] arc backend: (api|server)$/m)
      === "server"
        ? "server"
        : "api",
    arcBaseUrl: parseMatch(logText, /^\[harness\] arc base url: (.+)$/m) || "",
    scorecardOwnerCheckId: "",
    scorecardSessionPreflight: /\[harness\] scorecard preflight passed:/i.test(logText),
    scoreAfterSolve: /\[harness\] score-after-solve:/i.test(logText),
    scoreAfterSolveStartMode: scoreAfterSolveStartMode || "recover",
  });

  const logStat = await fs.stat(logPath).catch(() => null);
  return {
    schemaVersion: "ui.run-params.inferred.log.v2",
    inferred: true,
    recordedAt: logStat ? new Date(logStat.mtimeMs).toISOString() : new Date(0).toISOString(),
    runId,
    effectiveGameId: inferred.gameId,
    params: inferred,
    commandPreview: buildCommandPreview(inferred),
  };
}

async function inferParamsForRun(runId: string): Promise<StoredRunParams | null> {
  const logInferred = await inferParamsFromLog(runId);
  if (logInferred) return logInferred;

  const scorecard = await readJsonFile<{ scorecard_id?: string; operation_mode?: string }>(
    path.join(ctxDir(runId), "scorecard.json")
  );
  const state = await readJsonFile<{ game_id?: string }>(
    path.join(runDir(runId), "supervisor", "arc", "state.json")
  );
  const inferred = normalizeRunLaunchParams({
    ...DEFAULT_RUN_LAUNCH_PARAMS,
    gameId: state?.game_id?.split("-")[0] || DEFAULT_RUN_LAUNCH_PARAMS.gameId,
    sessionName: "",
    operationMode:
      scorecard?.operation_mode === "ONLINE" ? "ONLINE" : DEFAULT_RUN_LAUNCH_PARAMS.operationMode,
    scorecardId: scorecard?.scorecard_id || "",
  });

  return {
    schemaVersion: "ui.run-params.inferred.state.v2",
    inferred: true,
    recordedAt: new Date(0).toISOString(),
    runId,
    effectiveGameId: inferred.gameId,
    params: inferred,
    commandPreview: buildCommandPreview(inferred),
  };
}

export async function readRecentRunParams(): Promise<RunLaunchParams> {
  const stored = await readJsonFile<{ schemaVersion?: string; params?: RunLaunchParams }>(RECENT_PARAMS_PATH);
  const normalized = normalizeRunLaunchParams(stored?.params ?? DEFAULT_RUN_LAUNCH_PARAMS);
  if (stored?.schemaVersion !== RECENT_PARAMS_SCHEMA_VERSION) {
    return normalizeRunLaunchParams({
      ...normalized,
      sessionName: "",
    });
  }
  return normalized;
}

export async function readStoredRunParams(runId: string): Promise<StoredRunParams | null> {
  const stored = await readJsonFile<StoredRunParams>(path.join(runDir(runId), RUN_PARAMS_FILENAME));
  if (stored) {
    return {
      ...stored,
      params: normalizeRunLaunchParams(stored.params),
    };
  }
  return inferParamsForRun(runId);
}

export async function readRecordedRunParams(runId: string): Promise<StoredRunParams | null> {
  const stored = await readJsonFile<StoredRunParams>(path.join(runDir(runId), RUN_PARAMS_FILENAME));
  if (!stored) return null;
  return {
    ...stored,
    params: normalizeRunLaunchParams(stored.params),
  };
}

async function writeStoredRunParams(record: StoredRunParams) {
  await writeJsonFile(path.join(runDir(record.runId), RUN_PARAMS_FILENAME), record);
}

async function writeRecentRunParams(params: RunLaunchParams) {
  await writeJsonFile(RECENT_PARAMS_PATH, {
    schemaVersion: RECENT_PARAMS_SCHEMA_VERSION,
    savedAt: new Date().toISOString(),
    params,
  });
}

async function readRunScorecardMeta(runId: string): Promise<{
  scorecard_id?: string;
  operation_mode?: string;
} | null> {
  return readJsonFile(path.join(ctxDir(runId), "scorecard.json"));
}

function buildStoredRecord(
  params: RunLaunchParams,
  options: {
    runId: string;
    effectiveGameId: string;
    commandPreview: string;
  }
): StoredRunParams {
  return {
    schemaVersion: "ui.run-params.v1",
    inferred: false,
    recordedAt: new Date().toISOString(),
    runId: options.runId,
    effectiveGameId: options.effectiveGameId,
    params,
    commandPreview: options.commandPreview,
  };
}

export async function launchRun(paramsInput: unknown): Promise<{
  params: RunLaunchParams;
  runIds: string[];
  logFile: string;
}> {
  const requestedParams = normalizeRunLaunchParams(paramsInput);
  const requestedGameIds = resolveRequestedGameIds(requestedParams);
  const sessionBase = sanitizeSessionName(requestedParams.sessionName) || timestampSessionName();
  const effectiveHarnessParams: RunLaunchParams = {
    ...requestedParams,
    sessionName: sessionBase,
  };
  const commandPreview = buildCommandPreview(effectiveHarnessParams);

  validateRunLaunchParams(requestedParams);

  await ensureDir(RUNS_DIR);
  await ensureDir(LOGS_DIR);
  await ensureDir(CTXS_DIR);

  const runIds = requestedGameIds.length === 1
    ? [sessionBase]
    : requestedGameIds.map((gameId, index) => sessionNameForGame(sessionBase, gameId, index + 1));

  const logFile = `${sessionBase}.log`;
  const logPath = path.join(LOGS_DIR, logFile);
  const logHandle = await fs.open(logPath, "a");

  for (const [index, runId] of runIds.entries()) {
    const effectiveGameId = requestedGameIds[index] ?? requestedGameIds[0];
    await ensureDir(runDir(runId));
    await writeStoredRunParams(
      buildStoredRecord(requestedParams, { runId, effectiveGameId, commandPreview })
    );
    if (runId !== sessionBase) {
      const aliasPath = path.join(LOGS_DIR, `${runId}.log`);
      try {
        await fs.unlink(aliasPath);
      } catch {
        // Ignore absent aliases.
      }
      try {
        await fs.symlink(logFile, aliasPath);
      } catch {
        // Best effort only; base log still exists.
      }
    }
  }

  await writeRecentRunParams(requestedParams);

  const pythonPath = path.join(PROJECT_ROOT, ".venv", "bin", "python");
  const child = spawn(
    pythonPath,
    ["harness.py", ...buildHarnessArgs(effectiveHarnessParams)],
    {
      cwd: PROJECT_ROOT,
      detached: true,
      env: process.env,
      stdio: ["ignore", logHandle.fd, logHandle.fd],
    }
  );
  child.unref();
  await logHandle.close();

  return {
    params: requestedParams,
    runIds,
    logFile,
  };
}

export async function continueRun(runId: string): Promise<{
  runId: string;
  params: RunLaunchParams;
  logFile: string;
}> {
  const stored = await readStoredRunParams(runId);
  if (!stored) {
    throw new Error(`No recorded parameters available for run ${runId}.`);
  }

  const scorecardMeta = await readRunScorecardMeta(runId);
  const requestedParams = normalizeRunLaunchParams({
    ...stored.params,
    gameId: stored.effectiveGameId || stored.params.gameId,
    gameIds: "",
    sessionName: runId,
    openScorecard: false,
    scoreAfterSolve: false,
    scorecardId: scorecardMeta?.scorecard_id || stored.params.scorecardId,
    operationMode:
      scorecardMeta?.operation_mode === "ONLINE"
        ? "ONLINE"
        : stored.params.operationMode,
  });

  await ensureDir(LOGS_DIR);
  await ensureDir(CTXS_DIR);
  await ensureDir(RUNS_DIR);
  await writeRecentRunParams(requestedParams);

  const logFile = `${runId}.log`;
  const logPath = path.join(LOGS_DIR, logFile);
  const logHandle = await fs.open(logPath, "a");
  const pythonPath = path.join(PROJECT_ROOT, ".venv", "bin", "python");
  const child = spawn(
    pythonPath,
    ["harness.py", ...buildHarnessArgs(requestedParams), "--continue-run"],
    {
      cwd: PROJECT_ROOT,
      detached: true,
      env: process.env,
      stdio: ["ignore", logHandle.fd, logHandle.fd],
    }
  );
  child.unref();
  await logHandle.close();

  return {
    runId,
    params: requestedParams,
    logFile,
  };
}

export function tooltipForStoredRunParams(value: StoredRunParams | null): string {
  if (!value) return "No recorded parameters.";
  const prefix = value.inferred
    ? value.schemaVersion.includes(".log.")
      ? "Parameters (recovered from logs)"
      : "Parameters (inferred)"
    : "Parameters";
  return `${prefix}\n${summarizeRunLaunchParams(value.params)}`;
}
