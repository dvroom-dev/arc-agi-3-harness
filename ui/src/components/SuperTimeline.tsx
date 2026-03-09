"use client";

import { useMemo, useState } from "react";
import { usePolling } from "@/lib/hooks";
import type {
  SuperCheckResult,
  SuperCycleEntry,
  SuperConversationSummary,
  SuperInterventionEntry,
  SuperTimelinePayload,
} from "@/lib/types";

interface SuperTimelineProps {
  runId: string;
}

function formatDuration(durationMs: number | null) {
  if (durationMs == null) return "unknown";
  const totalSeconds = Math.max(0, Math.round(durationMs / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes === 0) return `${seconds}s`;
  return `${minutes}m ${String(seconds).padStart(2, "0")}s`;
}

function formatClock(value: string | null) {
  if (!value) return "unknown";
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return value;
  return date.toLocaleTimeString("en-US", {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function cycleTone(mode: string | null) {
  switch (mode) {
    case "explore_game":
      return "border-cyan-900/80 bg-cyan-950/15";
    case "code_model":
      return "border-violet-900/80 bg-violet-950/15";
    case "solve_model":
      return "border-emerald-900/80 bg-emerald-950/15";
    case "solve_game":
      return "border-sky-900/80 bg-sky-950/15";
    default:
      return "border-zinc-800 bg-zinc-950/60";
  }
}

function interventionTone(summary: string | null) {
  if ((summary || "").includes("(hard)")) {
    return "border-red-900/80 bg-red-950/15";
  }
  if ((summary || "").includes("(soft)")) {
    return "border-amber-900/80 bg-amber-950/15";
  }
  return "border-zinc-800 bg-zinc-950/60";
}

function SummaryPill({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-zinc-800 bg-zinc-950/70 px-3 py-2">
      <div className="text-[10px] uppercase tracking-[0.12em] text-zinc-500">{label}</div>
      <div className="mt-1 text-sm font-semibold text-zinc-100">{value}</div>
    </div>
  );
}

function failedChecks(checks: SuperCheckResult[] | null) {
  return (checks ?? []).filter((check) => check.status === "fail");
}

function CycleCard({ entry }: { entry: SuperCycleEntry }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <article className={`rounded-lg border p-3 ${cycleTone(entry.mode)}`}>
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        className="w-full text-left"
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <span className="rounded border border-zinc-700 bg-zinc-900/80 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-zinc-300">
                Cycle
              </span>
              <span className="rounded border border-zinc-700 bg-zinc-900/80 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-zinc-200">
                {entry.mode || "unknown mode"}
              </span>
            </div>
            <div className="mt-2 text-sm font-semibold text-zinc-100">
              {formatClock(entry.startedAt)} to {formatClock(entry.endedAt)}
            </div>
            <div className="mt-1 text-xs text-zinc-400">
              {formatDuration(entry.durationMs)} · {entry.toolCallCount} tool calls ·{" "}
              {entry.assistantTextCount} assistant msgs
            </div>
          </div>
          <div className="text-right text-[11px] text-zinc-400">
            <div>{entry.provider || "provider?"}</div>
            <div className="truncate">{entry.model || "model?"}</div>
          </div>
        </div>
      </button>

      {expanded ? (
        <div className="mt-3 space-y-3 border-t border-zinc-800/80 pt-3">
          <div className="grid grid-cols-2 gap-2 text-[11px] text-zinc-300">
            <SummaryPill label="First Tool" value={formatDuration(entry.firstToolLatencyMs)} />
            <SummaryPill label="Last Event" value={formatClock(entry.lastEventAt)} />
            <SummaryPill label="Results" value={String(entry.toolResultCount)} />
            <SummaryPill label="Errors" value={String(entry.toolErrorCount)} />
            <SummaryPill label="User Msgs" value={String(entry.userTextCount)} />
            <SummaryPill label="Events" value={String(entry.totalEvents)} />
          </div>

          <div>
            <div className="mb-2 text-[10px] uppercase tracking-[0.12em] text-zinc-500">
              Tool Mix
            </div>
            <div className="flex flex-wrap gap-2">
              {entry.toolCounts.length > 0 ? (
                entry.toolCounts.map((tool) => (
                  <span
                    key={tool.name}
                    className="rounded border border-zinc-700 bg-zinc-900/80 px-2 py-1 text-[11px] text-zinc-200"
                  >
                    {tool.name} × {tool.count}
                  </span>
                ))
              ) : (
                <span className="text-xs text-zinc-500">No tool calls recorded.</span>
              )}
            </div>
          </div>

          <div>
            <div className="mb-2 text-[10px] uppercase tracking-[0.12em] text-zinc-500">
              Enabled Tools
            </div>
            <div className="flex flex-wrap gap-2">
              {entry.enabledTools.map((tool) => (
                <span
                  key={tool}
                  className="rounded border border-zinc-700 bg-zinc-900/80 px-2 py-1 text-[11px] text-zinc-300"
                >
                  {tool}
                </span>
              ))}
            </div>
          </div>

          {entry.sessionId ? (
            <div className="text-[11px] text-zinc-500">session {entry.sessionId}</div>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}

function InterventionCard({ entry }: { entry: SuperInterventionEntry }) {
  const [expanded, setExpanded] = useState(false);
  const failedRuleChecks = failedChecks(entry.ruleChecks);
  const failedViolationChecks = failedChecks(entry.violationChecks);
  const reasonMentionsViolations = /violation/i.test(entry.reason || "");

  return (
    <article className={`rounded-lg border p-3 ${interventionTone(entry.actionSummary)}`}>
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        className="w-full text-left"
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <span className="rounded border border-zinc-700 bg-zinc-900/80 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-zinc-300">
                Intervention
              </span>
              <span className="text-sm font-semibold text-zinc-100">
                {entry.forkSummary || entry.actionSummary || "Supervisor event"}
              </span>
            </div>
            <div className="mt-1 text-xs text-zinc-400">
              {formatClock(entry.at)} · {entry.actionSummary || "event"}
            </div>
            {entry.reason ? (
              <div className="mt-2 line-clamp-3 text-xs text-zinc-300">
                {entry.reason}
              </div>
            ) : null}
            {failedViolationChecks.length > 0 ? (
              <div className="mt-2 text-xs text-red-300">
                {failedViolationChecks.length} failed violation check
                {failedViolationChecks.length === 1 ? "" : "s"}
              </div>
            ) : null}
          </div>
          <div className="text-right text-[11px] text-zinc-400">
            {entry.prevMode || "?"} → {entry.nextMode || "?"}
          </div>
        </div>
      </button>

      {expanded ? (
        <div className="mt-3 space-y-3 border-t border-zinc-800/80 pt-3">
          {entry.reason ? (
            <div>
              <div className="mb-2 text-[10px] uppercase tracking-[0.12em] text-zinc-500">
                Supervisor Reason
              </div>
              <div className="rounded border border-zinc-800 bg-zinc-950/80 px-3 py-2 text-xs text-zinc-300">
                {entry.reason}
              </div>
            </div>
          ) : null}
          <div className="grid grid-cols-2 gap-2">
            <SummaryPill
              label="Elapsed In Prior Cycle"
              value={formatDuration(entry.elapsedSincePrevCycleMs)}
            />
            <SummaryPill
              label="Gap To Next Cycle"
              value={formatDuration(entry.gapToNextCycleMs)}
            />
            <SummaryPill label="Agent Model" value={entry.model || "unknown"} />
            <SummaryPill label="Supervisor Model" value={entry.supervisorModel || "unknown"} />
          </div>
          {failedViolationChecks.length > 0 ? (
            <div>
              <div className="mb-2 text-[10px] uppercase tracking-[0.12em] text-zinc-500">
                Failed Violation Checks
              </div>
              <div className="space-y-2">
                {failedViolationChecks.map((check) => (
                  <div
                    key={check.rule}
                    className="rounded border border-red-900/70 bg-red-950/20 px-3 py-2 text-xs text-red-100"
                  >
                    <div className="font-medium">{check.rule}</div>
                    {check.comment ? <div className="mt-1 text-red-200/90">{check.comment}</div> : null}
                  </div>
                ))}
              </div>
            </div>
          ) : null}
          {failedRuleChecks.length > 0 ? (
            <div>
              <div className="mb-2 text-[10px] uppercase tracking-[0.12em] text-zinc-500">
                Failed Rule Checks
              </div>
              <div className="space-y-2">
                {failedRuleChecks.map((check) => (
                  <div
                    key={check.rule}
                    className="rounded border border-amber-900/70 bg-amber-950/20 px-3 py-2 text-xs text-amber-100"
                  >
                    <div className="font-medium">{check.rule}</div>
                    {check.comment ? (
                      <div className="mt-1 text-amber-200/90">{check.comment}</div>
                    ) : null}
                  </div>
                ))}
              </div>
            </div>
          ) : null}
          {failedViolationChecks.length === 0 &&
          failedRuleChecks.length === 0 &&
          reasonMentionsViolations ? (
            <div className="rounded border border-zinc-800 bg-zinc-950/80 px-3 py-2 text-xs text-zinc-400">
              Supervisor referenced failed violation checks, but this fork did not preserve the
              structured check list in its stored metadata.
            </div>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}

function ConversationSummaryCard({ entry }: { entry: SuperConversationSummary }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <article className="rounded-lg border border-zinc-800 bg-zinc-950/60 p-3">
      <button type="button" onClick={() => setExpanded((value) => !value)} className="w-full text-left">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="rounded border border-zinc-700 bg-zinc-900/80 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-zinc-300">
                Fork
              </span>
              <span className="rounded border border-zinc-700 bg-zinc-900/80 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-zinc-200">
                {entry.mode || "unknown mode"}
              </span>
            </div>
            <div className="mt-2 text-sm font-semibold text-zinc-100">
              {entry.conversationId.slice(0, 12)}… / {entry.forkId}
            </div>
            <div className="mt-1 text-xs text-zinc-400">
              {formatClock(entry.createdAt)} · {entry.toolCallCount} tool calls ·{" "}
              {entry.assistantTurns} assistant turns
            </div>
          </div>
          <div className="text-right text-[11px] text-zinc-500">
            <div>{entry.actionSummary || "(none)"}</div>
          </div>
        </div>
      </button>

      {expanded ? (
        <div className="mt-3 space-y-3 border-t border-zinc-800/80 pt-3">
          <div className="grid grid-cols-2 gap-2 text-[11px] text-zinc-300">
            <SummaryPill label="User Turns" value={String(entry.userTurns)} />
            <SummaryPill label="Assistant Turns" value={String(entry.assistantTurns)} />
            <SummaryPill label="Tool Calls" value={String(entry.toolCallCount)} />
            <SummaryPill label="Tool Results" value={String(entry.toolResultCount)} />
          </div>
          <div className="space-y-2 text-xs">
            <div>
              <div className="mb-1 text-[10px] uppercase tracking-[0.12em] text-zinc-500">
                Initial User
              </div>
              <div className="rounded border border-zinc-800 bg-zinc-950/80 px-3 py-2 text-zinc-300">
                {entry.initialUserPreview || "(none)"}
              </div>
            </div>
            <div>
              <div className="mb-1 text-[10px] uppercase tracking-[0.12em] text-zinc-500">
                Last Assistant
              </div>
              <div className="rounded border border-zinc-800 bg-zinc-950/80 px-3 py-2 text-zinc-300">
                {entry.lastAssistantPreview || "(none)"}
              </div>
            </div>
            <div>
              <div className="mb-1 text-[10px] uppercase tracking-[0.12em] text-zinc-500">
                Tool Mix
              </div>
              <div className="flex flex-wrap gap-2">
                {entry.toolCounts.length > 0 ? (
                  entry.toolCounts.map((tool) => (
                    <span
                      key={tool.name}
                      className="rounded border border-zinc-700 bg-zinc-900/80 px-2 py-1 text-[11px] text-zinc-200"
                    >
                      {tool.name} × {tool.count}
                    </span>
                  ))
                ) : (
                  <span className="text-xs text-zinc-500">No tool calls recorded.</span>
                )}
              </div>
            </div>
            <div className="text-[11px] text-zinc-500">skeleton {entry.skeletonPath || "(none)"}</div>
          </div>
        </div>
      ) : null}
    </article>
  );
}

const EMPTY_PAYLOAD: SuperTimelinePayload = {
  runId: "",
  conversationId: null,
  active: false,
  totalCycles: 0,
  totalInterventions: 0,
  totalDurationMs: 0,
  totalToolCalls: 0,
  totalToolErrors: 0,
  modeDurations: [],
  conversationSummaries: [],
  entries: [],
};

export function SuperTimeline({ runId }: SuperTimelineProps) {
  const { data, loading } = usePolling<SuperTimelinePayload>(
    `/api/runs/${runId}/super`,
    4000,
    EMPTY_PAYLOAD
  );

  const modeSummary = useMemo(
    () =>
      data.modeDurations.map((item) => (
        <span
          key={item.mode}
          className="rounded border border-zinc-700 bg-zinc-900/80 px-2 py-1 text-[11px] text-zinc-300"
        >
          {item.mode} · {formatDuration(item.durationMs)}
        </span>
      )),
    [data.modeDurations]
  );

  if (!loading && data.entries.length === 0 && data.conversationSummaries.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-zinc-500">
        No supervisor timeline data available.
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="border-b border-zinc-800 px-4 py-3">
        <div className="grid grid-cols-2 gap-2">
          <SummaryPill label="Cycles" value={String(data.totalCycles)} />
          <SummaryPill label="Interventions" value={String(data.totalInterventions)} />
          <SummaryPill label="Time In Cycles" value={formatDuration(data.totalDurationMs)} />
          <SummaryPill label="Tool Calls" value={String(data.totalToolCalls)} />
        </div>
        <div className="mt-3">
          <div className="mb-2 text-[10px] uppercase tracking-[0.12em] text-zinc-500">
            Time By Mode
          </div>
          <div className="flex flex-wrap gap-2">
            {modeSummary.length > 0 ? (
              modeSummary
            ) : (
              <span className="text-xs text-zinc-500">No completed cycles yet.</span>
            )}
          </div>
        </div>
      </div>

      <div className="min-h-0 flex-1 space-y-3 overflow-auto px-4 py-4">
        {data.conversationSummaries.length > 0 ? (
          <div className="space-y-3">
            <div className="text-[10px] uppercase tracking-[0.12em] text-zinc-500">
              Conversation Skeletons
            </div>
            {data.conversationSummaries.map((entry) => (
              <ConversationSummaryCard key={entry.key} entry={entry} />
            ))}
          </div>
        ) : null}
        {data.entries.map((entry) =>
          entry.kind === "cycle" ? (
            <CycleCard key={entry.id} entry={entry} />
          ) : (
            <InterventionCard key={entry.id} entry={entry} />
          )
        )}
      </div>
    </div>
  );
}
