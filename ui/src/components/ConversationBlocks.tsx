"use client";

import { useState } from "react";
import type { ConversationBlock } from "@/lib/conversation";

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

function toolTone(kind: "tool_call" | "tool_result") {
  if (kind === "tool_call") {
    return {
      badge: "border-orange-800 bg-orange-950/70 text-orange-300",
      panel: "border-orange-900/70 bg-orange-950/15",
      text: "text-orange-50",
    };
  }
  return {
    badge: "border-rose-800 bg-rose-950/70 text-rose-300",
    panel: "border-rose-900/70 bg-rose-950/15",
    text: "text-rose-50",
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
    summary: summaryLine?.replace(/^summary:\s*/, "") || block.kind,
    status: statusLine?.replace(/^status:\s*/, "") || "",
    toolUseId: toolUseIdMatch?.[0] || null,
    body,
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

function ToolResultBody({
  runId,
  toolUseId,
  inlineBody,
  textClassName,
}: {
  runId: string;
  toolUseId: string | null;
  inlineBody: string;
  textClassName: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [fullBody, setFullBody] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const hasBody = inlineBody.trim().length > 0;
  const isExpandable = hasBody;
  const preview = buildSingleLinePreview(inlineBody);

  async function handleToggle() {
    if (expanded) {
      setExpanded(false);
      return;
    }
    if (!toolUseId || fullBody) {
      setExpanded(true);
      return;
    }
    setLoading(true);
    setLoadError(null);
    try {
      const response = await fetch(
        `/api/runs/${runId}/conversation/tool-result?toolUseId=${encodeURIComponent(toolUseId)}`
      );
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || "Failed to load full tool result");
      }
      if (typeof payload.content === "string" && payload.content.trim()) {
        setFullBody(payload.content);
      }
      setExpanded(true);
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : String(error));
      setExpanded(true);
    } finally {
      setLoading(false);
    }
  }

  const displayed = expanded ? fullBody || inlineBody : preview;

  return (
    <div>
      {expanded ? (
        <pre className={`whitespace-pre-wrap text-[11px] leading-6 ${textClassName}`}>
          {displayed}
        </pre>
      ) : (
        <OneLinePreview content={displayed} textClassName={textClassName} />
      )}
      {loadError ? (
        <div className="mt-2 text-[10px] text-red-300">{loadError}</div>
      ) : null}
      {isExpandable ? (
        <button
          type="button"
          onClick={handleToggle}
          disabled={loading}
          className="mt-2 rounded border border-zinc-700 bg-zinc-900/80 px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-zinc-400 hover:border-zinc-600 hover:text-zinc-200 disabled:opacity-60"
        >
          {expanded ? "Show less" : loading ? "Loading..." : "Show full"}
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

export function ToolBlock({ runId, block }: { runId: string; block: ConversationBlock }) {
  const tone = toolTone(block.kind as "tool_call" | "tool_result");
  const parsed = parseToolBlock(block);
  const [expanded, setExpanded] = useState(false);
  const preview = buildSingleLinePreview(parsed.body);
  const hasBody = parsed.body.trim().length > 0;
  const isExpandable = hasBody;
  return (
    <div className={`rounded-lg border p-3 ${tone.panel}`}>
      <div className="mb-3 flex items-center gap-2">
        <span
          className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.14em] ${tone.badge}`}
        >
          {block.kind.replace("_", " ")}
        </span>
        {parsed.status ? (
          <span className="text-[10px] uppercase tracking-[0.12em] text-zinc-500">
            {parsed.status}
          </span>
        ) : null}
      </div>
      <div className="mb-2 overflow-hidden text-ellipsis whitespace-nowrap text-[11px] font-semibold text-zinc-200">
        {parsed.summary}
      </div>
      {block.kind === "tool_result" ? (
        <ToolResultBody
          runId={runId}
          toolUseId={parsed.toolUseId}
          inlineBody={parsed.body}
          textClassName={tone.text}
        />
      ) : (
        <div>
          {expanded ? (
            <pre className={`whitespace-pre-wrap text-[11px] leading-6 ${tone.text}`}>
              {parsed.body}
            </pre>
          ) : (
            <OneLinePreview content={preview} textClassName={tone.text} />
          )}
          {isExpandable ? (
            <button
              type="button"
              onClick={() => setExpanded((value) => !value)}
              className="mt-2 rounded border border-zinc-700 bg-zinc-900/80 px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-zinc-400 hover:border-zinc-600 hover:text-zinc-200"
            >
              {expanded ? "Show less" : "Show full"}
            </button>
          ) : null}
        </div>
      )}
    </div>
  );
}

export function SupervisorDecisionBlock({ content }: { content: string }) {
  const rows = parseKeyValueLines(content);
  const details = humanizeSupervisorDecision(rows);
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
          {details.nextMode ? `Next mode: ${details.nextMode}` : "No mode change"}
          {details.trigger ? ` · Trigger: ${details.trigger}` : ""}
        </div>
      </div>
      <div className="grid gap-2">
        {rows
          .filter((row) => row.key !== "mode")
          .map((row) => (
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
