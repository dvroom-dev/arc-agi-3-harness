import fs from "fs/promises";
import path from "path";
import { loadRawEvents } from "@/lib/agentConversationEvents.server";
import { sliceConversationBlocks, type ConversationBlock } from "@/lib/conversation";
import { runDir } from "@/lib/paths";
import {
  combineToolBursts,
  summarizeToolBursts,
  type ToolActivitySummary,
} from "@/lib/supervisorToolActivity.server";

interface SuperStateFile {
  conversationId?: unknown;
  activeForkId?: unknown;
}

interface ReviewEntry {
  id: string;
  at: string;
  promptText: string;
  responseText: string | null;
}

interface ParsedSupervisorResponse {
  decision: string | null;
  payload: Record<string, unknown> | null;
  modeAssessment: Record<string, unknown> | null;
  reasoning: string | null;
}

interface ResolvedSupervisorConversation {
  conversationId: string;
  activeForkId: string | null;
  reviews: ReviewEntry[];
}

export interface SupervisorConversationDocument {
  blocks: ConversationBlock[];
  source: string | null;
  totalLines: number;
  totalEvents: number;
  shownEvents: number;
  hiddenEvents: number;
}

function normalizeString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function emptyConversationDocument(): SupervisorConversationDocument {
  return {
    blocks: [],
    source: null,
    totalLines: 0,
    totalEvents: 0,
    shownEvents: 0,
    hiddenEvents: 0,
  };
}

function parseTime(value: string | null | undefined): number {
  const parsed = Date.parse(value ?? "");
  return Number.isFinite(parsed) ? parsed : 0;
}

function promptMeta(promptText: string) {
  const trigger = promptText.match(/^Trigger:\s*(.+)$/m)?.[1]?.trim() ?? null;
  const mode =
    promptText.match(/^- Current mode:\s*(.+)$/m)?.[1]?.trim() ??
    promptText.match(/^current_mode:\s*(.+)$/m)?.[1]?.trim() ??
    null;
  const allowedNextModes =
    promptText.match(/^- Allowed next modes:\s*(.+)$/m)?.[1]?.trim() ?? null;
  const why =
    promptText.match(/^Why this review ran:\s*(.+)$/m)?.[1]?.trim() ??
    null;
  return { trigger, mode, allowedNextModes, why };
}

function parseSupervisorResponse(responseText: string | null): ParsedSupervisorResponse {
  if (!responseText) {
    return {
      decision: null,
      payload: null,
      modeAssessment: null,
      reasoning: null,
    };
  }
  try {
    const parsed = JSON.parse(responseText) as Record<string, unknown>;
    return {
      decision: typeof parsed.decision === "string" ? parsed.decision : null,
      payload:
        parsed.payload && typeof parsed.payload === "object"
          ? (parsed.payload as Record<string, unknown>)
          : null,
      modeAssessment:
        parsed.mode_assessment && typeof parsed.mode_assessment === "object"
          ? (parsed.mode_assessment as Record<string, unknown>)
          : null,
      reasoning: typeof parsed.reasoning === "string" ? parsed.reasoning.trim() : null,
    };
  } catch {
    return {
      decision: null,
      payload: null,
      modeAssessment: null,
      reasoning: null,
    };
  }
}

function buildToolActivityBlock(
  summary: ToolActivitySummary,
  title = "Tool Activity"
): ConversationBlock {
  const toolTypes = summary.toolCounts
    .map((entry) => `${entry.name} x${entry.count}`)
    .join(", ");
  const sessionIdLabel =
    summary.sessionIds.length === 0
      ? "(unknown)"
      : summary.sessionIds.length === 1
        ? summary.sessionIds[0]
        : summary.sessionIds.join(", ");
  const lines = [
    `start: ${summary.startedAt}`,
    `end: ${summary.endedAt}`,
    `session_id: ${sessionIdLabel}`,
    `tool_types: ${toolTypes || "(none)"}`,
    `errors: ${summary.errorCount}`,
    `files: ${summary.files.join(", ") || "(none detected)"}`,
  ];
  return {
    kind: "text",
    title,
    content: lines.join("\n"),
    raw: lines.join("\n"),
  };
}

function formatReviewContextBlock(review: ReviewEntry): string {
  const meta = promptMeta(review.promptText);
  const lines = [
    `review_id: ${review.id}`,
    `at: ${review.at}`,
    `trigger: ${meta.trigger ?? "(unknown)"}`,
    `current_mode: ${meta.mode ?? "(unknown)"}`,
  ];
  if (meta.allowedNextModes) {
    lines.push(`allowed_next_modes: ${meta.allowedNextModes}`);
  }
  if (meta.why) {
    lines.push(`why: ${meta.why}`);
  }
  return lines.join("\n");
}

function formatDecisionBlock(promptText: string, responseText: string | null): string {
  const { trigger, mode } = promptMeta(promptText);
  if (!responseText) {
    return [
      `mode: ${mode ?? "(unknown)"}`,
      `trigger: ${trigger ?? "(unknown)"}`,
      "decision: (pending)",
      "action: (pending)",
      "next_mode: (pending)",
    ].join("\n");
  }
  const parsed = parseSupervisorResponse(responseText);
  const payload = parsed.payload;
  const nextMode = typeof payload?.mode === "string" ? payload.mode : "(none)";
  const action =
    typeof payload?.action === "string"
      ? payload.action
      : typeof parsed.decision === "string"
        ? parsed.decision
        : "(none)";

  const lines = [
    `mode: ${mode ?? "(unknown)"}`,
    `trigger: ${trigger ?? "(unknown)"}`,
    `decision: ${parsed.decision ?? "(unparsed)"}`,
    `action: ${action}`,
    `next_mode: ${nextMode}`,
  ];

  const maybeReason = typeof payload?.reason === "string" ? payload.reason.trim() : "";
  if (maybeReason) {
    lines.push(`reason: ${maybeReason}`);
  }
  const maybeAdvice = typeof payload?.advice === "string" ? payload.advice.trim() : "";
  if (maybeAdvice) {
    lines.push(`advice: ${maybeAdvice}`);
  }
  return lines.join("\n");
}

function formatModeAssessmentBlock(modeAssessment: Record<string, unknown> | null): string | null {
  if (!modeAssessment) return null;
  const lines: string[] = [];
  if (typeof modeAssessment.current_mode_stop_satisfied === "boolean") {
    lines.push(`current_mode_stop_satisfied: ${String(modeAssessment.current_mode_stop_satisfied)}`);
  }
  if (typeof modeAssessment.recommended_action === "string") {
    lines.push(`recommended_action: ${modeAssessment.recommended_action}`);
  }
  const ranked = Array.isArray(modeAssessment.candidate_modes_ranked)
    ? modeAssessment.candidate_modes_ranked
    : [];
  for (const candidate of ranked) {
    if (!candidate || typeof candidate !== "object") continue;
    const mode = typeof (candidate as { mode?: unknown }).mode === "string"
      ? (candidate as { mode: string }).mode
      : "(unknown)";
    const confidence = typeof (candidate as { confidence?: unknown }).confidence === "string"
      ? (candidate as { confidence: string }).confidence
      : "unknown";
    const evidence = typeof (candidate as { evidence?: unknown }).evidence === "string"
      ? (candidate as { evidence: string }).evidence.trim()
      : "";
    lines.push(`candidate_${mode}: ${confidence}${evidence ? ` - ${evidence}` : ""}`);
  }
  return lines.length > 0 ? lines.join("\n") : null;
}

function buildReviewBlocks(review: ReviewEntry): ConversationBlock[] {
  const parsed = parseSupervisorResponse(review.responseText);
  const payload = parsed.payload;
  const blocks: ConversationBlock[] = [
    {
      kind: "text",
      title: "Review Context",
      content: formatReviewContextBlock(review),
      raw: review.promptText,
    },
    {
      kind: "text",
      title: "Supervisor Decision",
      content: formatDecisionBlock(review.promptText, review.responseText),
      raw: review.responseText ?? review.promptText,
    },
  ];

  if (!review.responseText) {
    blocks.push({
      kind: "text",
      title: "Supervisor Status",
      content: "Review in progress; response has not been written yet.",
      raw: review.promptText,
    });
    return blocks;
  }

  if (typeof payload?.message === "string" && payload.message.trim()) {
    blocks.push({
      kind: "text",
      title: "Supervisor Message",
      content: payload.message.trim(),
      raw: review.responseText,
    });
  }

  const userMessage =
    payload?.mode_payload &&
    typeof payload.mode_payload === "object" &&
    typeof (payload.mode_payload as { user_message?: unknown }).user_message === "string"
      ? ((payload.mode_payload as { user_message: string }).user_message || "").trim()
      : "";
  if (userMessage) {
    blocks.push({
      kind: "text",
      title: "Mode Handoff",
      content: userMessage,
      raw: review.responseText,
    });
  }

  const assessment = formatModeAssessmentBlock(parsed.modeAssessment);
  if (assessment) {
    blocks.push({
      kind: "text",
      title: "Mode Assessment",
      content: assessment,
      raw: review.responseText,
    });
  }

  if (parsed.reasoning) {
    blocks.push({
      kind: "text",
      title: "Supervisor Reasoning",
      content: parsed.reasoning,
      raw: review.responseText,
    });
  }

  return blocks;
}

async function readSuperState(runId: string): Promise<{
  conversationId: string | null;
  activeForkId: string | null;
}> {
  const statePath = path.join(runDir(runId), "super", "state.json");
  try {
    const payload = JSON.parse(await fs.readFile(statePath, "utf-8")) as SuperStateFile;
    return {
      conversationId: normalizeString(payload.conversationId),
      activeForkId: normalizeString(payload.activeForkId),
    };
  } catch {
    return {
      conversationId: null,
      activeForkId: null,
    };
  }
}

async function readRunHistoryConversationIds(runId: string): Promise<string[]> {
  const indexPath = path.join(
    runDir(runId),
    ".ai-supervisor",
    "supervisor",
    "run_history",
    "index.json"
  );
  try {
    const payload = JSON.parse(await fs.readFile(indexPath, "utf-8")) as {
      conversations?: Array<{
        conversationId?: unknown;
        lastForkAt?: unknown;
        firstForkAt?: unknown;
      }>;
    };
    return (payload.conversations ?? [])
      .map((entry) => ({
        conversationId: normalizeString(entry.conversationId),
        sortKey: Math.max(
          parseTime(normalizeString(entry.lastForkAt)),
          parseTime(normalizeString(entry.firstForkAt))
        ),
      }))
      .filter((entry): entry is { conversationId: string; sortKey: number } => Boolean(entry.conversationId))
      .sort((a, b) => b.sortKey - a.sortKey || a.conversationId.localeCompare(b.conversationId))
      .map((entry) => entry.conversationId);
  } catch {
    return [];
  }
}

async function listConversationIds(runId: string): Promise<string[]> {
  const conversationsDir = path.join(runDir(runId), ".ai-supervisor", "conversations");
  try {
    const entries = await fs.readdir(conversationsDir, { withFileTypes: true });
    return entries
      .filter((entry) => entry.isDirectory())
      .map((entry) => entry.name)
      .sort();
  } catch {
    return [];
  }
}

async function resolveConversationCandidates(runId: string): Promise<
  Array<{ conversationId: string; activeForkId: string | null }>
> {
  const [superState, runHistoryIds, conversationIds] = await Promise.all([
    readSuperState(runId),
    readRunHistoryConversationIds(runId),
    listConversationIds(runId),
  ]);
  const ordered = new Map<string, string | null>();

  if (superState.conversationId) {
    ordered.set(superState.conversationId, superState.activeForkId);
  }
  for (const conversationId of runHistoryIds) {
    if (!ordered.has(conversationId)) {
      ordered.set(conversationId, null);
    }
  }
  for (const conversationId of conversationIds) {
    if (!ordered.has(conversationId)) {
      ordered.set(conversationId, null);
    }
  }

  return Array.from(ordered, ([conversationId, activeForkId]) => ({
    conversationId,
    activeForkId,
  }));
}

async function readConversationReviews(
  runId: string,
  conversationId: string
): Promise<ReviewEntry[]> {
  const reviewsDir = path.join(
    runDir(runId),
    ".ai-supervisor",
    "conversations",
    conversationId,
    "reviews"
  );
  let reviewFiles: string[] = [];
  try {
    reviewFiles = await fs.readdir(reviewsDir);
  } catch {
    return [];
  }

  const reviewIds = Array.from(
    new Set(
      reviewFiles
        .map((file) => file.match(/^(review_[^_]+(?:-[^_]+)*)_(prompt|response)\.txt$/)?.[1] ?? null)
        .filter((value): value is string => Boolean(value))
    )
  );

  const reviews = await Promise.all(
    reviewIds.map(async (id): Promise<ReviewEntry | null> => {
      const promptPath = path.join(reviewsDir, `${id}_prompt.txt`);
      const responsePath = path.join(reviewsDir, `${id}_response.txt`);
      try {
        const [promptText, promptStat, responseText] = await Promise.all([
          fs.readFile(promptPath, "utf-8"),
          fs.stat(promptPath),
          fs.readFile(responsePath, "utf-8").catch(() => null),
        ]);
        return {
          id,
          at: promptStat.mtime.toISOString(),
          promptText,
          responseText,
        };
      } catch {
        return null;
      }
    })
  );

  return reviews
    .filter((review): review is ReviewEntry => Boolean(review))
    .sort((a, b) => parseTime(a.at) - parseTime(b.at) || a.id.localeCompare(b.id));
}

export async function resolveActiveSupervisorConversation(
  runId: string
): Promise<ResolvedSupervisorConversation | null> {
  const candidates = await resolveConversationCandidates(runId);
  for (const candidate of candidates) {
    const reviews = await readConversationReviews(runId, candidate.conversationId);
    if (reviews.length === 0) continue;
    return {
      conversationId: candidate.conversationId,
      activeForkId: candidate.activeForkId,
      reviews,
    };
  }
  return null;
}

export async function readSupervisorConversationDocument(
  runId: string,
  options: { hiddenEvents?: number; maxEvents?: number }
): Promise<SupervisorConversationDocument> {
  const activeConversation = await resolveActiveSupervisorConversation(runId);
  if (!activeConversation) {
    return emptyConversationDocument();
  }

  const rawEvents = await loadRawEvents(runId, activeConversation.conversationId);

  const frontmatter = [
    `conversation_id: ${activeConversation.conversationId}`,
    `active_fork_id: ${activeConversation.activeForkId ?? "(unknown)"}`,
    `reviews: ${activeConversation.reviews.length}`,
  ].join("\n");
  const blocks: ConversationBlock[] = [
    {
      kind: "frontmatter",
      content: frontmatter,
      raw: frontmatter,
    },
    ...activeConversation.reviews.flatMap((review, index) => {
      const previousReview = activeConversation.reviews[index - 1] ?? null;
      const toolSummary = combineToolBursts(
        summarizeToolBursts(rawEvents, previousReview?.at ?? null, review.at)
      );
      return [
        ...(toolSummary ? [buildToolActivityBlock(toolSummary)] : []),
        ...buildReviewBlocks(review),
      ];
    }),
  ];
  const trailingToolSummary = combineToolBursts(
    summarizeToolBursts(rawEvents, activeConversation.reviews.at(-1)?.at ?? null, null)
  );
  if (trailingToolSummary) {
    blocks.push(buildToolActivityBlock(trailingToolSummary, "Recent Tool Activity"));
  }
  const windowed = sliceConversationBlocks(blocks, options);
  return {
    blocks: windowed.blocks,
    source: `${activeConversation.conversationId} supervisor reviews`,
    totalLines: blocks.reduce((sum, block) => sum + block.content.split("\n").length, 0),
    totalEvents: windowed.totalEvents,
    shownEvents: windowed.shownEvents,
    hiddenEvents: windowed.hiddenEvents,
  };
}
