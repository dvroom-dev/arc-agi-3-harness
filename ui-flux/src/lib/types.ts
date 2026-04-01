export type FluxSessionType = "solver" | "modeler" | "bootstrapper";

export interface FluxRunSummary {
  runId: string;
  gameId: string | null;
  updatedAt: string | null;
  startedAt: string | null;
  status: string;
  liveStatus: "running" | "stopped" | "stale" | "missing";
  active: Record<FluxSessionType, { status: string; sessionId: string | null }>;
}

export interface FluxFrameSnapshot {
  id: string;
  label: string;
  grid: number[][];
  actionLabel: string | null;
  lastActionLabel: string | null;
  turnDir: string | null;
  changedPixels: number;
  stepCount: number;
}

export interface FluxActionSummary {
  step: number;
  actionLabel: string;
  changedPixels: number;
  turnDir: string;
  stateBefore: string;
  stateAfter: string;
}

export interface FluxSessionSummary {
  sessionId: string;
  sessionType: FluxSessionType;
  status: string;
  createdAt: string | null;
  updatedAt: string | null;
  provider: string | null;
  model: string | null;
  stopReason: string | null;
  latestAssistantText: string | null;
}

export interface FluxRunDetail extends FluxRunSummary {
  queues: Record<FluxSessionType, { length: number }>;
  selectedGameDir: string | null;
  currentState: Record<string, unknown> | null;
  currentLevel: number | null;
  currentAttemptId: string | null;
  frames: FluxFrameSnapshot[];
  actions: FluxActionSummary[];
  sessionHistory: Record<FluxSessionType, FluxSessionSummary[]>;
}

export interface FluxSessionTimelineEntry {
  kind: string;
  ts: string | null;
  title: string;
  text: string | null;
  raw: unknown;
}

export interface FluxPromptPayload {
  fileName: string;
  payload: unknown;
}

export interface FluxSessionDetail {
  session: FluxSessionSummary | null;
  prompts: FluxPromptPayload[];
  messages: Record<string, unknown>[];
  toolEvents: FluxSessionTimelineEntry[];
}

export interface FluxRunStartRequest {
  gameId: string;
  provider: "claude" | "codex" | "mock";
  operationMode: "OFFLINE" | "ONLINE" | "NORMAL";
  sessionName: string;
}
