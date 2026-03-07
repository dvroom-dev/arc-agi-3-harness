"use client";

import { useState, useEffect } from "react";

interface FileViewerProps {
  runId: string;
  filePath: string | null;
}

export function FileViewer({ runId, filePath }: FileViewerProps) {
  const [content, setContent] = useState<string | null>(null);

  useEffect(() => {
    if (!filePath) return;
    fetch(`/api/runs/${runId}/files?path=${encodeURIComponent(filePath)}`)
      .then((r) => r.json())
      .then((d) => setContent(d.content ?? d.error ?? "Error loading file"))
      .catch((e) => setContent(`Error: ${e}`));
  }, [runId, filePath]);

  if (!filePath) {
    return (
      <div className="flex items-center justify-center h-full text-zinc-600 text-sm">
        Select a file to view
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      <div className="text-xs text-zinc-500 px-3 py-1.5 border-b border-zinc-800 font-mono shrink-0">
        {filePath}
      </div>
      <div className="flex-1 overflow-auto">
        <pre className="text-xs font-mono text-zinc-300 p-3 leading-relaxed whitespace-pre-wrap">
          {content ?? "Loading..."}
        </pre>
      </div>
    </div>
  );
}
