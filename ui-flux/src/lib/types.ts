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
  promptCount: number;
  userMessageCount: number;
  assistantMessageCount: number;
}

export interface FluxQueuePreview {
  length: number;
  reason: string | null;
  dedupeKey: string | null;
  interruptPolicy: string | null;
  baselineModelRevisionId: string | null;
  modelRevisionId: string | null;
  seedRevisionId: string | null;
  seedDeltaKind: string | null;
  evidenceBundleId: string | null;
}

export interface FluxRunDetail extends FluxRunSummary {
  queues: Record<FluxSessionType, FluxQueuePreview>;
  selectedGameDir: string | null;
  currentState: Record<string, unknown> | null;
  generatedSequenceCount: number | null;
  acceptedCoverageLevel: number | null;
  acceptedCoverageHighestSequenceId: string | null;
  acceptedCoverageMatchedSequences: number | null;
  lastCompareLevel: number | null;
  lastCompareRequestedSequences: number | null;
  lastCompareComparedSequences: number | null;
  lastCompareMatchedSequences: number | null;
  lastCompareDivergedSequences: number | null;
  lastCompareAllMatch: boolean | null;
  lastCompareHighestMatchedLevel: number | null;
  lastCompareHighestMatchedSequenceId: string | null;
  lastCompareFirstFailingSequenceId: string | null;
  lastCompareFirstFailingStep: number | null;
  lastCompareFirstFailingReason: string | null;
  currentModelerTargetLevel: number | null;
  currentModelerTargetSequenceId: string | null;
  currentModelerTargetStep: number | null;
  currentModelerTargetReason: string | null;
  currentLevel: number | null;
  currentAttemptId: string | null;
  currentModelRevisionId: string | null;
  lastBootstrapperModelRevisionId: string | null;
  lastQueuedBootstrapModelRevisionId: string | null;
  lastAttestedSeedRevisionId: string | null;
  lastAttestedSeedHash: string | null;
  lastInterruptPolicy: string | null;
  lastSeedDeltaKind: string | null;
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
