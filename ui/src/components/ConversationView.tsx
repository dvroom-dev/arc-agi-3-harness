"use client";

import { useCallback, useLayoutEffect, useMemo, useState } from "react";
import {
  ContentPreview,
  FileCard,
  isSupervisorDecisionBlock,
  SupervisorDecisionBlock,
  ToolBlock,
} from "@/components/ConversationBlocks";
import type { ConversationBlock } from "@/lib/conversation";
import { usePolling } from "@/lib/hooks";
import { useAutoFollowScroll } from "@/lib/useAutoFollowScroll";
interface ConversationViewProps {
  runId: string;
  source?: "agent" | "supervisor";
}
interface ContentSegment {
  kind: "text" | "file";
  title?: string;
  content: string;
}

function parseInlineSegments(content: string): ContentSegment[] {
  const lines = content.split("\n");
  const segments: ContentSegment[] = [];
  let i = 0;

  while (i < lines.length) {
    const fileMatch = (lines[i] ?? "").match(/^==>\s+(.+?)\s+<==$/);
    if (fileMatch) {
      const title = fileMatch[1];
      const fileLines: string[] = [];
      i += 1;
      while (i < lines.length && !lines[i].startsWith("==> ")) {
        fileLines.push(lines[i]);
        i += 1;
      }
      segments.push({
        kind: "file",
        title,
        content: fileLines.join("\n").trim(),
      });
      continue;
    }

    const textLines: string[] = [];
    while (i < lines.length && !lines[i].startsWith("==> ")) {
      textLines.push(lines[i]);
      i += 1;
    }
    const text = textLines.join("\n").trim();
    if (text) {
      segments.push({
        kind: "text",
        content: text,
      });
    }
  }

  return segments;
}

function roleTone(role: string | undefined) {
  switch (role) {
    case "user":
      return {
        badge: "border-blue-800 bg-blue-950/70 text-blue-300",
        panel: "border-blue-900/70 bg-blue-950/15",
        text: "text-blue-50",
      };
    case "assistant":
      return {
        badge: "border-emerald-800 bg-emerald-950/70 text-emerald-300",
        panel: "border-emerald-900/70 bg-emerald-950/15",
        text: "text-emerald-50",
      };
    case "system":
      return {
        badge: "border-fuchsia-800 bg-fuchsia-950/70 text-fuchsia-300",
        panel: "border-fuchsia-900/70 bg-fuchsia-950/15",
        text: "text-fuchsia-50",
      };
    default:
      return {
        badge: "border-zinc-700 bg-zinc-900 text-zinc-300",
        panel: "border-zinc-800 bg-zinc-950/60",
        text: "text-zinc-100",
      };
  }
}

export function ConversationView({ runId, source = "supervisor" }: ConversationViewProps) {
  const [windowState, setWindowState] = useState<{
    runId: string;
    hiddenEvents: number | null;
  }>({ runId, hiddenEvents: null });
  const hiddenEvents = windowState.runId === runId ? windowState.hiddenEvents : null;
  const conversationUrl = useMemo(() => {
    const params = new URLSearchParams();
    if (hiddenEvents === null) {
      params.set("events", "80");
    } else {
      params.set("hidden", String(hiddenEvents));
    }
    const basePath =
      source === "agent"
        ? `/api/runs/${runId}/conversation/agent`
        : `/api/runs/${runId}/conversation`;
    return `${basePath}?${params.toString()}`;
  }, [runId, hiddenEvents, source]);

  const handleConversationData = useCallback(
    (next: {
      hiddenEvents: number;
    }) => {
      setWindowState((current) => {
        if (current.runId !== runId) {
          return { runId, hiddenEvents: next.hiddenEvents };
        }
        if (current.hiddenEvents === null) {
          return { runId, hiddenEvents: next.hiddenEvents };
        }
        return current;
      });
    },
    [runId]
  );

  const { data } = usePolling<{
    blocks: ConversationBlock[];
    totalLines: number;
    source: string | null;
    totalEvents: number;
    shownEvents: number;
    hiddenEvents: number;
  }>(conversationUrl, 5000, {
    blocks: [],
    totalLines: 0,
    source: null,
    totalEvents: 0,
    shownEvents: 0,
    hiddenEvents: 0,
  }, handleConversationData);

  const { scrollRef, handleScroll, syncScrollPosition } = useAutoFollowScroll();

  useLayoutEffect(() => {
    syncScrollPosition();
  }, [data.blocks.length, syncScrollPosition]);

  if (data.blocks.length === 0) {
    return <div className="p-4 text-sm text-zinc-600">No conversation data</div>;
  }

  const missingEvents = Math.max(0, data.totalEvents - data.shownEvents);
  const loadEarlierCount = Math.min(50, missingEvents);
  const showingAll = missingEvents === 0;

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="flex items-center justify-between gap-3 px-3 py-2 border-b border-zinc-800 shrink-0 bg-zinc-950/80">
        <div className="min-w-0 flex items-center gap-2 text-xs text-zinc-400">
          <span className="truncate">{data.source || "conversation"}</span>
          <span className="rounded-full border border-zinc-800 bg-zinc-900 px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.12em] text-zinc-500">
            {data.shownEvents} of {data.totalEvents} events
          </span>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <button
            type="button"
            onClick={() =>
              setWindowState((current) => ({
                runId,
                hiddenEvents: Math.max(0, ((current.runId === runId ? current.hiddenEvents : null) ?? 0) - loadEarlierCount),
              }))
            }
            disabled={showingAll}
            className="rounded-full border border-zinc-700 bg-zinc-900 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-zinc-300 disabled:border-zinc-800 disabled:text-zinc-600"
          >
            {showingAll ? "All shown" : `Load ${loadEarlierCount} earlier`}
          </button>
          {!showingAll ? (
            <button
              type="button"
              onClick={() => setWindowState({ runId, hiddenEvents: 0 })}
              className="rounded-full border border-zinc-700 bg-zinc-900 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-zinc-300"
            >
              {`Load all ${missingEvents}`}
            </button>
          ) : null}
          <div className="rounded-full border border-zinc-800 bg-zinc-900 px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.12em] text-zinc-500">
            {data.totalLines} lines
          </div>
        </div>
      </div>
      <div
        className="flex-1 overflow-y-auto px-3 py-3 space-y-3 bg-[linear-gradient(180deg,rgba(24,24,27,0.55)_0%,rgba(9,9,11,0)_100%)]"
        ref={scrollRef}
        onScroll={handleScroll}
      >
        {data.blocks.map((block, index) => {
          if (block.kind === "frontmatter") {
            return (
              <div key={index} className="rounded-lg border border-zinc-800 bg-zinc-950/80 p-3">
                <div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-zinc-500">
                  Session
                </div>
                <ContentPreview content={block.content} textClassName="text-zinc-400" previewLines={12} />
              </div>
            );
          }

          if (block.kind === "chat") {
            const tone = roleTone(block.role);
            const segments = parseInlineSegments(block.content);
            return (
              <div key={index} className={`rounded-lg border p-3 ${tone.panel}`}>
                <div className="mb-3">
                  <span className={`inline-flex rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.14em] ${tone.badge}`}>
                    {block.role || "chat"}
                  </span>
                </div>
                <div className="space-y-3">
                  {segments.map((segment, segmentIndex) =>
                    segment.kind === "file" ? (
                      <FileCard
                        key={`${index}-${segmentIndex}`}
                        title={segment.title}
                        content={segment.content}
                      />
                    ) : (
                      <div key={`${index}-${segmentIndex}`} className="rounded-lg border border-white/5 bg-black/10 p-3">
                        <ContentPreview
                          content={segment.content}
                          textClassName={tone.text}
                          previewLines={16}
                        />
                      </div>
                    )
                  )}
                </div>
              </div>
            );
          }

          if (block.kind === "tool_call" || block.kind === "tool_result") {
            return <ToolBlock key={index} runId={runId} block={block} />;
          }

          if (block.kind === "file") {
            return <FileCard key={index} title={block.title} content={block.content} />;
          }

          if (isSupervisorDecisionBlock(block.content)) {
            return <SupervisorDecisionBlock key={index} content={block.content} />;
          }

          return (
            <div key={index} className="rounded-lg border border-zinc-800 bg-zinc-950/60 p-3">
              <ContentPreview content={block.content} textClassName="text-zinc-300" previewLines={16} />
            </div>
          );
        })}
      </div>
    </div>
  );
}
