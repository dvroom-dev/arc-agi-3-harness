import type { RunLaunchParams, StoredRunParams } from "@/lib/runParams";

// --- Run list ---
export interface RunSummary {
  id: string;
  state: string; // WIN, NOT_FINISHED, GAME_OVER, LOSS, etc.
  gameId: string;
  currentLevel: number;
  levelsCompleted: number;
  totalLevels: number;
  totalSteps: number;
  hasLog: boolean;
  modifiedAt: number; // unix ms
  runParams: StoredRunParams | null;
  runParamsTooltip: string;
}

// --- Game state (state.json) ---
export interface GameState {
  game_id: string;
  current_level: number;
  state: string;
  levels_completed: number;
  win_levels: number;
  total_steps: number;
  steps: string[];
  available_actions: number[];
  last_action: string;
  full_reset: boolean;
  action_input_name: string;
  guid?: string;
}

// --- Tool engine history ---
export interface HistoryEvent {
  kind: "step" | "reset" | string;
  action?: string;
  data?: unknown;
  levels_completed?: number;
}

export interface ToolEngineHistory {
  game_id: string;
  events: HistoryEvent[];
  turn?: number;
}

// --- Turn trace (summary, returned in list) ---
export interface TraceSummary {
  turnNumber: number;
  action: string;
  steps: number;
  scriptError: boolean;
  stepActions?: string[];
  startLevel?: number | null;
  endLevel?: number | null;
}

// --- Turn trace with grid (returned for single turn) ---
export interface TraceWithGrid extends TraceSummary {
  grid: number[][] | null;
  selectedStep?: number | null;
}

// --- File tree ---
export interface FileNode {
  name: string;
  path: string;
  type: "file" | "directory";
  children?: FileNode[];
}

// --- Action sequence for a level ---
export interface ActionSequence {
  level: number;
  actions: { action: string; stepIndex: number }[];
  startEventIndex: number;
  endEventIndex: number;
}

export interface LevelScoreSummary {
  level: number;
  completed: boolean;
  score: number;
  actions: number;
  baselineActions: number | null;
}

export interface GameScoreSummary {
  gameId: string;
  score: number;
  levelsCompleted: number;
  levelCount: number;
  actions: number;
  resets: number;
  completed: boolean;
  attempts: number;
  selectedAttemptGuid: string | null;
  selectedAttemptState: string | null;
  selectedAttemptMessage: string | null;
  levels: LevelScoreSummary[];
}

export interface ScoreSummary {
  score: number;
  totalGames: number;
  totalGamesCompleted: number;
  totalLevelsCompleted: number;
  totalLevels: number;
  totalActions: number;
  games: GameScoreSummary[];
}

export interface ScoreComparisonLevel {
  level: number;
  matches: boolean;
}

export interface ScoreComparisonGame {
  gameId: string;
  matches: boolean;
  reason?: string;
  levels: ScoreComparisonLevel[];
}

export interface ScoreComparison {
  mode: "live" | "recorded-final-score";
  matches: boolean;
  totalMatches: boolean;
  games: ScoreComparisonGame[];
}

export interface ScorecardSummary {
  cardId: string | null;
  apiUrl: string | null;
  webUrl: string | null;
  closed: boolean;
  finalScore: number | null;
  createdHere: boolean | null;
  live: ScoreSummary | null;
  liveFetchError: string | null;
}

export interface RunScorePayload {
  runId: string;
  local: ScoreSummary;
  scorecard: ScorecardSummary | null;
  comparison: ScoreComparison | null;
}

export interface SuperToolCount {
  name: string;
  count: number;
}

export interface SuperModeDuration {
  mode: string;
  durationMs: number;
}

export interface SuperCheckResult {
  rule: string;
  status: string;
  comment: string | null;
}

export interface SuperCycleEntry {
  id: string;
  kind: "cycle";
  startedAt: string;
  endedAt: string | null;
  durationMs: number | null;
  mode: string | null;
  provider: string | null;
  model: string | null;
  sessionId: string | null;
  enabledTools: string[];
  totalEvents: number;
  toolCallCount: number;
  toolResultCount: number;
  toolErrorCount: number;
  assistantTextCount: number;
  userTextCount: number;
  firstToolLatencyMs: number | null;
  lastEventAt: string | null;
  toolCounts: SuperToolCount[];
}

export interface SuperInterventionEntry {
  id: string;
  kind: "intervention";
  at: string;
  actionSummary: string | null;
  forkSummary: string | null;
  reason: string | null;
  ruleChecks: SuperCheckResult[] | null;
  violationChecks: SuperCheckResult[] | null;
  provider: string | null;
  model: string | null;
  supervisorModel: string | null;
  prevMode: string | null;
  nextMode: string | null;
  elapsedSincePrevCycleMs: number | null;
  gapToNextCycleMs: number | null;
}

export interface SuperConversationSummary {
  key: string;
  conversationId: string;
  forkId: string;
  parentId: string | null;
  createdAt: string;
  mode: string | null;
  actionSummary: string | null;
  initialUserPreview: string | null;
  lastAssistantPreview: string | null;
  userTurns: number;
  assistantTurns: number;
  toolCallCount: number;
  toolResultCount: number;
  toolCounts: SuperToolCount[];
  skeletonPath: string;
}

export type SuperTimelineEntry = SuperCycleEntry | SuperInterventionEntry;

export interface SuperTimelinePayload {
  runId: string;
  conversationId: string | null;
  active: boolean;
  totalCycles: number;
  totalInterventions: number;
  totalDurationMs: number;
  totalToolCalls: number;
  totalToolErrors: number;
  modeDurations: SuperModeDuration[];
  conversationSummaries: SuperConversationSummary[];
  entries: SuperTimelineEntry[];
}

export type { RunLaunchParams, StoredRunParams };
