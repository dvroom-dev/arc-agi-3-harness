"use client";

import { useState } from "react";
import type { ConversationBlock } from "@/lib/conversation";

const COMPACT_TOOL_DETAILS_OMITTED = "(details omitted in compact view)";

function fileTone(title: string | undefined) {
  const lower = (title || "").toLowerCase();
  if (lower.endsWith(".py")) {
    return {
      badge: "border-sky-800 bg-sky-950/60 text-sky-300",
      text: "text-sky-100",
    };
  }
  if (lower.endsWith(".md")) {
    return {
      badge: "border-amber-800 bg-amber-950/60 text-amber-300",
      text: "text-amber-100",
    };
  }
  if (lower.endsWith(".json")) {
    return {
      badge: "border-violet-800 bg-violet-950/60 text-violet-300",
      text: "text-violet-100",
    };
  }
  return {
    badge: "border-zinc-700 bg-zinc-900 text-zinc-300",
    text: "text-zinc-100",
  };
}

function toolTone(status: "ok" | "error" | "pending") {
  if (status === "pending") {
    return {
      badge: "border-orange-800 bg-orange-950/70 text-orange-300",
      panel: "border-orange-900/70 bg-orange-950/15",
      text: "text-orange-50",
    };
  }
  if (status === "ok") {
    return {
      badge: "border-sky-800 bg-sky-950/70 text-sky-300",
      panel: "border-sky-900/70 bg-sky-950/15",
      text: "text-sky-50",
    };
  }
  return {
    badge: "border-rose-800 bg-rose-950/70 text-rose-300",
    panel: "border-rose-900/70 bg-rose-950/15",
    text: "text-rose-50",
  };
}

function reasoningTone() {
  return {
    badge: "border-emerald-800 bg-emerald-950/70 text-emerald-300",
    panel: "border-emerald-900/70 bg-emerald-950/15",
    text: "text-emerald-50",
  };
}

function parseKeyValueLines(content: string) {
  const rows = content
    .split("\n")
    .map((line) => line.match(/^([a-z_]+):\s*(.*)$/i))
    .filter((match): match is RegExpMatchArray => Boolean(match))
    .map((match) => ({
      key: match[1],
      value: match[2] || "(empty)",
    }));
  return rows.length >= 4 ? rows : [];
}

function humanizeSupervisorDecision(rows: Array<{ key: string; value: string }>) {
  const map = new Map(rows.map((row) => [row.key, row.value]));
  const decision = map.get("decision");
  const action = map.get("action");
  const nextMode = map.get("next_mode");
  const trigger = map.get("trigger");

  let summary = "Supervisor updated the run state.";
  if (decision === "resume_mode_head" && nextMode && nextMode !== "(none)") {
    summary = `Switched mode to ${nextMode} by resuming the existing conversation.`;
  } else if (decision === "fork_new_conversation" && nextMode && nextMode !== "(none)") {
    summary = `Switched mode to ${nextMode} by starting a new conversation.`;
  } else if (action === "continue") {
    summary = "Kept the run in the current mode.";
  } else if (action) {
    summary = action;
  }

  return {
    summary,
    trigger: trigger && trigger !== "(none)" ? trigger : null,
    nextMode: nextMode && nextMode !== "(none)" ? nextMode : null,
    actionLine:
      nextMode && nextMode !== "(none)"
        ? `switch_mode to ${nextMode}`
        : action && action !== "(none)"
          ? action
          : null,
  };
}

export function isSupervisorDecisionBlock(content: string) {
  const rows = parseKeyValueLines(content);
  if (rows.length === 0) return false;
  const keys = new Set(rows.map((row) => row.key));
  return (
    keys.has("mode") &&
    keys.has("trigger") &&
    keys.has("decision") &&
    (keys.has("action") || keys.has("resume"))
  );
}

function parseToolBlock(block: ConversationBlock) {
  if (block.tool) {
    return {
      name: block.tool.name,
      status: block.tool.status,
      toolUseId: block.tool.toolUseId,
      call: block.tool.call,
      result: block.tool.result,
    };
  }

  const lines = block.content.split("\n");
  const summaryLine = lines.find((line) => line.startsWith("summary: "));
  const statusLine = lines.find((line) => line.startsWith("status: "));
  const toolUseIdMatch = summaryLine?.match(/toolu_[A-Za-z0-9]+/);
  const bodyStart = lines.findIndex((line) => line.trim() === "" && summaryLine && statusLine);
  const body =
    bodyStart >= 0
      ? lines.slice(bodyStart + 1).join("\n").trim()
      : lines.join("\n").trim();

  return {
    name: summaryLine?.replace(/^summary:\s*/, "") || block.kind,
    status: (() => {
      const rawStatus = statusLine?.replace(/^status:\s*/, "").trim().toLowerCase() || "pending";
      if (rawStatus === "completed" || rawStatus === "ok") return "ok";
      if (rawStatus === "error") return "error";
      return "pending";
    })(),
    toolUseId: toolUseIdMatch?.[0] || null,
    call: body,
    result: null,
  };
}

function buildSingleLinePreview(content: string) {
  const normalized = content.replace(/\r/g, "");
  const preview = normalized
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .join(" ")
    .replace(/\s+/g, " ")
    .trim();
  return preview || "(empty)";
}

function OneLinePreview({
  content,
  textClassName,
}: {
  content: string;
  textClassName: string;
}) {
  return (
    <div className={`overflow-hidden text-ellipsis whitespace-nowrap text-[11px] leading-6 ${textClassName}`}>
      {content}
    </div>
  );
}

export function ContentPreview({
  content,
  textClassName,
  previewLines = 18,
  expandLabel = "Show full",
  collapseLabel = "Show less",
}: {
  content: string;
  textClassName: string;
  previewLines?: number;
  expandLabel?: string;
  collapseLabel?: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const lines = content.split("\n");
  const isLong = lines.length > previewLines || content.length > 1800;
  const preview = isLong ? lines.slice(0, previewLines).join("\n") : content;

  return (
    <div>
      <pre className={`whitespace-pre-wrap text-[11px] leading-6 ${textClassName}`}>
        {expanded || !isLong ? content : `${preview}\n...`}
      </pre>
      {isLong ? (
        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          className="mt-2 rounded border border-zinc-700 bg-zinc-900/80 px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-zinc-400 hover:border-zinc-600 hover:text-zinc-200"
        >
          {expanded ? collapseLabel : expandLabel}
        </button>
      ) : null}
    </div>
  );
}

export function FileCard({ title, content }: { title?: string; content: string }) {
  const tone = fileTone(title);
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950/75 overflow-hidden">
      <div className="flex items-center justify-between gap-3 border-b border-zinc-800 bg-zinc-900/70 px-3 py-2">
        <span
          className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.14em] ${tone.badge}`}
        >
          {title || "file"}
        </span>
      </div>
      <div className="p-3">
        <ContentPreview content={content} textClassName={tone.text} previewLines={14} />
      </div>
    </div>
  );
}

export function ToolBlock({ block }: { block: ConversationBlock }) {
  const parsed = parseToolBlock(block);
  const tone = toolTone(parsed.status);
  const [expanded, setExpanded] = useState(false);
  const callPreview = buildSingleLinePreview(parsed.call);
  const resultPreview = parsed.result ? buildSingleLinePreview(parsed.result) : null;
  const hasCallDetails =
    parsed.call.trim().length > 0 && parsed.call.trim() !== COMPACT_TOOL_DETAILS_OMITTED;
  const hasResultDetails =
    Boolean(parsed.result?.trim()) && parsed.result?.trim() !== COMPACT_TOOL_DETAILS_OMITTED;
  const isExpandable = hasCallDetails || hasResultDetails;
  const statusLabel = parsed.status.toUpperCase();
  const icon = expanded ? "v" : ">";
  return (
    <div className={`rounded-lg border p-3 ${tone.panel}`}>
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        disabled={!isExpandable}
        aria-expanded={expanded}
        className="w-full text-left disabled:cursor-default"
      >
        <div className="mb-2 flex items-center gap-2">
          <span className={`text-[11px] font-semibold ${tone.text}`}>{icon}</span>
          <span className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.14em] ${tone.badge}`}>
            tool
          </span>
          <span className="text-[11px] font-semibold text-zinc-100">
            {`call ${parsed.name} ${statusLabel}`}
          </span>
        </div>
        <div className="space-y-1">
          <OneLinePreview content={`Call: ${callPreview}`} textClassName={tone.text} />
          <OneLinePreview
            content={
              resultPreview === null
                ? "Result pending"
                : `Result ${statusLabel}: ${resultPreview}`
            }
            textClassName={tone.text}
          />
        </div>
      </button>
      {expanded ? (
        <div className="mt-3 space-y-3 border-t border-white/10 pt-3">
          <div>
            <div className="mb-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-zinc-400">
              Call
            </div>
            <pre className={`whitespace-pre-wrap text-[11px] leading-6 ${tone.text}`}>
              {parsed.call}
            </pre>
          </div>
          <div>
            <div className="mb-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-zinc-400">
              {resultPreview === null ? "Result Pending" : `Result ${statusLabel}`}
            </div>
            <pre className={`whitespace-pre-wrap text-[11px] leading-6 ${tone.text}`}>
              {parsed.result ?? "(awaiting result)"}
            </pre>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export function ReasoningBlock({ block }: { block: ConversationBlock }) {
  const tone = reasoningTone();
  return (
    <div className={`rounded-lg border p-3 ${tone.panel}`}>
      <div className="mb-3">
        <span className={`inline-flex rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.14em] ${tone.badge}`}>
          reasoning summary
        </span>
      </div>
      <ContentPreview content={block.content} textClassName={tone.text} previewLines={8} />
    </div>
  );
}

export function SupervisorDecisionBlock({ content }: { content: string }) {
  const rows = parseKeyValueLines(content);
  const details = humanizeSupervisorDecision(rows);
  const visibleRows = rows
    .filter((row) => !["mode", "decision", "action", "resume", "next_mode"].includes(row.key))
    .map((row) => ({
      ...row,
      key: row.key === "reasons" ? "reason" : row.key,
    }));
  return (
    <div className="rounded-lg border border-cyan-900/70 bg-cyan-950/15 p-3">
      <div className="mb-3">
        <span className="inline-flex rounded-full border border-cyan-800 bg-cyan-950/70 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-cyan-300">
          supervisor decision
        </span>
      </div>
      <div className="mb-3 rounded border border-cyan-950/60 bg-black/10 px-3 py-2">
        <div className="text-sm font-semibold text-cyan-50">{details.summary}</div>
        <div className="mt-1 text-xs text-cyan-200/80">
          {details.actionLine ? `Action: ${details.actionLine}` : "No mode change"}
          {details.trigger ? ` · Trigger: ${details.trigger}` : ""}
        </div>
      </div>
      <div className="grid gap-2">
        {visibleRows.map((row) => (
          <div
            key={row.key}
            className="grid grid-cols-[120px_minmax(0,1fr)] gap-3 rounded border border-cyan-950/60 bg-black/10 px-3 py-2"
          >
            <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-cyan-400">
              {row.key}
            </div>
            <div className="min-w-0 break-words text-[11px] leading-6 text-cyan-50">
              {row.value}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
