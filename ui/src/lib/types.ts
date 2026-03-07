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
}

// --- Turn trace with grid (returned for single turn) ---
export interface TraceWithGrid extends TraceSummary {
  grid: number[][] | null;
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

export type { RunLaunchParams, StoredRunParams };
