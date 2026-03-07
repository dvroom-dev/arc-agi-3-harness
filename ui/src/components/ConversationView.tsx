"use client";

import { useEffect, useRef } from "react";
import { usePolling } from "@/lib/hooks";

interface ConversationViewProps {
  runId: string;
}

export function ConversationView({ runId }: ConversationViewProps) {
  const { data } = usePolling<{ content: string | null; totalLines: number }>(
    `/api/runs/${runId}/conversation?tail=300`,
    5000,
    { content: null, totalLines: 0 }
  );

  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [data.content]);

  if (!data.content) {
    return <div className="p-4 text-sm text-zinc-600">No conversation data</div>;
  }

  return (
    <div className="flex flex-col h-full">
      <div className="text-xs text-zinc-600 px-2 py-1 border-b border-zinc-800 shrink-0">
        session.md ({data.totalLines} lines)
      </div>
      <div className="flex-1 overflow-y-auto" ref={scrollRef}>
        <pre className="text-xs font-mono text-zinc-400 p-2 whitespace-pre-wrap leading-relaxed">
          {data.content}
        </pre>
      </div>
    </div>
  );
}
