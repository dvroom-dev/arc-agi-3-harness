"use client";

import { useState, useEffect } from "react";
import type { FileNode } from "@/lib/types";
import { ChevronRight, ChevronDown, FileText, Folder } from "lucide-react";

interface FileTreeProps {
  runId: string;
  onSelectFile: (path: string) => void;
  selectedPath: string | null;
}

function TreeNode({
  node,
  depth,
  onSelectFile,
  selectedPath,
}: {
  node: FileNode;
  depth: number;
  onSelectFile: (path: string) => void;
  selectedPath: string | null;
}) {
  const [expanded, setExpanded] = useState(depth < 2);

  if (node.type === "directory") {
    return (
      <div>
        <button
          onClick={() => setExpanded(!expanded)}
          className="flex items-center gap-1 w-full text-left px-1 py-0.5 hover:bg-zinc-800/50 text-zinc-400 text-xs"
          style={{ paddingLeft: `${depth * 12 + 4}px` }}
        >
          {expanded ? (
            <ChevronDown size={12} />
          ) : (
            <ChevronRight size={12} />
          )}
          <Folder size={12} className="text-zinc-500" />
          <span>{node.name}</span>
        </button>
        {expanded &&
          node.children?.map((child) => (
            <TreeNode
              key={child.path}
              node={child}
              depth={depth + 1}
              onSelectFile={onSelectFile}
              selectedPath={selectedPath}
            />
          ))}
      </div>
    );
  }

  const isSelected = selectedPath === node.path;
  return (
    <button
      onClick={() => onSelectFile(node.path)}
      className={`flex items-center gap-1 w-full text-left px-1 py-0.5 hover:bg-zinc-800/50 text-xs ${
        isSelected ? "bg-blue-900/30 text-blue-300" : "text-zinc-300"
      }`}
      style={{ paddingLeft: `${depth * 12 + 4}px` }}
    >
      <FileText size={12} className="text-zinc-600 shrink-0" />
      <span className="truncate">{node.name}</span>
    </button>
  );
}

export function FileTree({ runId, onSelectFile, selectedPath }: FileTreeProps) {
  const [tree, setTree] = useState<FileNode[]>([]);

  useEffect(() => {
    fetch(`/api/runs/${runId}/files`)
      .then((r) => r.json())
      .then(setTree)
      .catch(console.error);
  }, [runId]);

  return (
    <div className="overflow-y-auto text-xs">
      {tree.map((node) => (
        <TreeNode
          key={node.path}
          node={node}
          depth={0}
          onSelectFile={onSelectFile}
          selectedPath={selectedPath}
        />
      ))}
      {tree.length === 0 && (
        <div className="p-2 text-zinc-600 text-center">No agent files</div>
      )}
    </div>
  );
}
