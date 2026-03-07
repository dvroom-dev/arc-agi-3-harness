export type OperationMode = "NORMAL" | "ONLINE" | "OFFLINE";
export type Provider = "" | "claude" | "codex" | "mock";
export type ArcBackend = "api" | "server";

export interface RunLaunchParams {
  gameId: string;
  gameIds: string;
  maxTurns: number | null;
  operationMode: OperationMode;
  sessionName: string;
  verbose: boolean;
  openScorecard: boolean;
  scorecardId: string;
  provider: Provider;
  noSupervisor: boolean;
  exploreInputs: boolean;
  maxGameOverResets: number;
  arcBackend: ArcBackend;
  arcBaseUrl: string;
  scorecardOwnerCheckId: string;
  scorecardSessionPreflight: boolean;
  scoreAfterSolve: boolean;
  scoreAfterSolveStartMode: string;
}

export interface StoredRunParams {
  schemaVersion: string;
  inferred: boolean;
  recordedAt: string;
  runId: string;
  effectiveGameId: string;
  params: RunLaunchParams;
  commandPreview: string;
}

export const DEFAULT_RUN_LAUNCH_PARAMS: RunLaunchParams = {
  gameId: "ls20",
  gameIds: "",
  maxTurns: null,
  operationMode: "NORMAL",
  sessionName: "",
  verbose: false,
  openScorecard: false,
  scorecardId: "",
  provider: "",
  noSupervisor: false,
  exploreInputs: false,
  maxGameOverResets: 0,
  arcBackend: "api",
  arcBaseUrl: "",
  scorecardOwnerCheckId: "",
  scorecardSessionPreflight: false,
  scoreAfterSolve: false,
  scoreAfterSolveStartMode: "recover",
};

function normalizeString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value.trim() : fallback;
}

function normalizeInt(value: unknown, fallback: number | null): number | null {
  if (value === "" || value === null || value === undefined) return fallback;
  const parsed = Number.parseInt(String(value), 10);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function normalizeBoolean(value: unknown, fallback = false): boolean {
  return typeof value === "boolean" ? value : fallback;
}

export function normalizeRunLaunchParams(value: unknown): RunLaunchParams {
  const raw = (value ?? {}) as Partial<RunLaunchParams>;
  const normalized: RunLaunchParams = {
    gameId: normalizeString(raw.gameId, DEFAULT_RUN_LAUNCH_PARAMS.gameId) || DEFAULT_RUN_LAUNCH_PARAMS.gameId,
    gameIds: normalizeString(raw.gameIds),
    maxTurns: normalizeInt(raw.maxTurns, DEFAULT_RUN_LAUNCH_PARAMS.maxTurns),
    operationMode:
      raw.operationMode === "ONLINE" || raw.operationMode === "OFFLINE" || raw.operationMode === "NORMAL"
        ? raw.operationMode
        : DEFAULT_RUN_LAUNCH_PARAMS.operationMode,
    sessionName: normalizeString(raw.sessionName),
    verbose: normalizeBoolean(raw.verbose),
    openScorecard: normalizeBoolean(raw.openScorecard),
    scorecardId: normalizeString(raw.scorecardId),
    provider:
      raw.provider === "claude" || raw.provider === "codex" || raw.provider === "mock"
        ? raw.provider
        : DEFAULT_RUN_LAUNCH_PARAMS.provider,
    noSupervisor: normalizeBoolean(raw.noSupervisor),
    exploreInputs: normalizeBoolean(raw.exploreInputs),
    maxGameOverResets: normalizeInt(raw.maxGameOverResets, DEFAULT_RUN_LAUNCH_PARAMS.maxGameOverResets) ?? 0,
    arcBackend:
      raw.arcBackend === "server" || raw.arcBackend === "api"
        ? raw.arcBackend
        : DEFAULT_RUN_LAUNCH_PARAMS.arcBackend,
    arcBaseUrl: normalizeString(raw.arcBaseUrl),
    scorecardOwnerCheckId: normalizeString(raw.scorecardOwnerCheckId),
    scorecardSessionPreflight: normalizeBoolean(raw.scorecardSessionPreflight),
    scoreAfterSolve: normalizeBoolean(raw.scoreAfterSolve),
    scoreAfterSolveStartMode:
      normalizeString(raw.scoreAfterSolveStartMode, DEFAULT_RUN_LAUNCH_PARAMS.scoreAfterSolveStartMode)
      || DEFAULT_RUN_LAUNCH_PARAMS.scoreAfterSolveStartMode,
  };

  return normalized;
}

export function resolveRequestedGameIds(params: RunLaunchParams): string[] {
  const raw = params.gameIds.trim();
  if (!raw) return [params.gameId];
  const unique: string[] = [];
  const seen = new Set<string>();
  for (const token of raw.split(/[,\s]+/)) {
    const trimmed = token.trim();
    if (!trimmed || seen.has(trimmed)) continue;
    seen.add(trimmed);
    unique.push(trimmed);
  }
  return unique.length > 0 ? unique : [params.gameId];
}

export function summarizeRunLaunchParams(params: RunLaunchParams): string {
  const lines = [
    `Games: ${params.gameIds.trim() || params.gameId}`,
    `Mode: ${params.operationMode}`,
    `Provider: ${params.provider || "default"}`,
    `Backend: ${params.arcBackend}`,
    `Session: ${params.sessionName || "auto"}`,
  ];

  if (params.maxTurns !== null) lines.push(`Max turns: ${params.maxTurns}`);
  if (params.maxGameOverResets !== DEFAULT_RUN_LAUNCH_PARAMS.maxGameOverResets) {
    lines.push(`Max GAME_OVER resets: ${params.maxGameOverResets}`);
  }
  if (params.arcBaseUrl) lines.push(`ARC base URL: ${params.arcBaseUrl}`);
  if (params.scorecardId) lines.push(`Scorecard ID: ${params.scorecardId}`);
  if (params.scorecardOwnerCheckId) lines.push(`Owner check ID: ${params.scorecardOwnerCheckId}`);
  if (params.scoreAfterSolve) lines.push(`Score-after-solve: ${params.scoreAfterSolveStartMode}`);
  if (params.openScorecard) lines.push("Open scorecard: yes");
  if (params.scorecardSessionPreflight) lines.push("Scorecard preflight: yes");
  if (params.noSupervisor) lines.push("Supervisor: disabled");
  if (params.exploreInputs) lines.push("Explore inputs: yes");
  if (params.verbose) lines.push("Verbose terminal grid: yes");
  return lines.join("\n");
}

export function prepareImportedRunLaunchParams(params: RunLaunchParams): RunLaunchParams {
  return normalizeRunLaunchParams({
    ...params,
    // Imported runs should launch as a fresh session unless the user explicitly re-enters a name.
    sessionName: "",
  });
}
