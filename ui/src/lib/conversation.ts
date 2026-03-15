export interface ConversationBlock {
  kind: "frontmatter" | "chat" | "file" | "text" | "tool_call" | "tool_result" | "tool" | "reasoning";
  title?: string;
  role?: string;
  content: string;
  header?: string;
  meta?: Record<string, string>;
  tool?: {
    name: string;
    status: "ok" | "error" | "pending";
    call: string;
    result: string | null;
    toolUseId: string | null;
  };
  raw: string;
}

const COMPACT_TOOL_DETAILS_OMITTED = "(details omitted in compact view)";

function parseFenceHeader(
  line: string
): { fence: string; kind: string; meta: Record<string, string> } | null {
  const match = line.match(/^(`{3,})([a-z_]+)(?:\s+(.*))?$/i);
  if (!match) return null;
  const [, fence, kind, rest] = match;
  const meta: Record<string, string> = {};
  if (rest) {
    for (const pair of rest.matchAll(/([a-z_]+)=([^\s]+)/gi)) {
      meta[pair[1]] = pair[2];
    }
  }
  return { fence, kind, meta };
}

export function parseConversationBlocks(content: string): ConversationBlock[] {
  const lines = content.split("\n");
  const blocks: ConversationBlock[] = [];
  let i = 0;

  if (lines[0] === "---") {
    let j = 1;
    while (j < lines.length && lines[j] !== "---") j += 1;
    if (j < lines.length) {
      blocks.push({
        kind: "frontmatter",
        content: lines.slice(1, j).join("\n"),
        raw: lines.slice(0, j + 1).join("\n"),
      });
      i = j + 1;
    }
  }

  while (i < lines.length) {
    const line = lines[i] ?? "";
    if (!line.trim()) {
      i += 1;
      continue;
    }

    const fileMatch = line.match(/^==>\s+(.+?)\s+<==$/);
    if (fileMatch) {
      const start = i;
      const title = fileMatch[1];
      const fileLines: string[] = [];
      i += 1;
      while (
        i < lines.length &&
        !lines[i].startsWith("==> ") &&
        !lines[i].startsWith("```")
      ) {
        fileLines.push(lines[i]);
        i += 1;
      }
      blocks.push({
        kind: "file",
        title,
        content: fileLines.join("\n").trim(),
        raw: lines.slice(start, i).join("\n").trim(),
      });
      continue;
    }

    const fence = parseFenceHeader(line);
    if (fence) {
      const start = i;
      const fenceLines: string[] = [];
      i += 1;
      while (i < lines.length && lines[i] !== fence.fence) {
        fenceLines.push(lines[i]);
        i += 1;
      }
      if (i < lines.length && lines[i] === fence.fence) i += 1;

      const kind =
        fence.kind === "chat" ||
        fence.kind === "tool_call" ||
        fence.kind === "tool_result"
          ? (fence.kind as ConversationBlock["kind"])
          : "text";

      blocks.push({
        kind,
        role: fence.kind === "chat" ? fence.meta.role : undefined,
        header: line,
        meta: fence.meta,
        content: fenceLines.join("\n").trim(),
        raw: lines.slice(start, i).join("\n").trim(),
      });
      continue;
    }

    const start = i;
    const textLines: string[] = [];
    while (
      i < lines.length &&
      !/^`{3,}$/.test(lines[i] ?? "") &&
      !lines[i].startsWith("==> ") &&
      !/^`{3,}[a-z_]/i.test(lines[i] ?? "")
    ) {
      textLines.push(lines[i]);
      i += 1;
    }
    const text = textLines.join("\n").trim();
    if (text) {
      blocks.push({
        kind: "text",
        content: text,
        raw: lines.slice(start, i).join("\n").trim(),
      });
    }

    if (i < lines.length && /^`{3,}$/.test(lines[i] ?? "")) {
      i += 1;
    }
  }

  return blocks;
}

export function countConversationEvents(blocks: ConversationBlock[]) {
  return blocks.filter((block) => block.kind !== "frontmatter").length;
}

function blockIdentity(block: ConversationBlock) {
  return JSON.stringify([
    block.kind,
    block.role ?? "",
    block.title ?? "",
    block.content,
    block.tool ?? null,
  ]);
}

export function trimSeedOverlap(
  seedBlocks: ConversationBlock[],
  appendedBlocks: ConversationBlock[]
) {
  const seedEvents = seedBlocks.filter((block) => block.kind !== "frontmatter");
  const maxOverlap = Math.min(seedEvents.length, appendedBlocks.length);
  let overlap = 0;

  for (let size = maxOverlap; size > 0; size -= 1) {
    const seedSlice = seedEvents.slice(-size);
    const appendedSlice = appendedBlocks.slice(0, size);
    const matches = seedSlice.every(
      (block, index) => blockIdentity(block) === blockIdentity(appendedSlice[index]!)
    );
    if (matches) {
      overlap = size;
      break;
    }
  }

  return appendedBlocks.slice(overlap);
}

export function sliceConversationBlocks(
  blocks: ConversationBlock[],
  options: { hiddenEvents?: number; maxEvents?: number }
) {
  const frontmatter = blocks.find((block) => block.kind === "frontmatter") || null;
  const events = blocks.filter((block) => block.kind !== "frontmatter");
  const totalEvents = events.length;
  const hiddenEvents = Math.max(
    0,
    Math.min(totalEvents, options.hiddenEvents ?? Math.max(0, totalEvents - (options.maxEvents ?? totalEvents)))
  );
  const shownBlocks = events.slice(hiddenEvents);

  return {
    blocks: frontmatter ? [frontmatter, ...shownBlocks] : shownBlocks,
    totalEvents,
    shownEvents: shownBlocks.length,
    hiddenEvents,
  };
}

function parseLegacyToolCall(block: ConversationBlock) {
  const headerName = typeof block.meta?.name === "string" ? block.meta.name.trim() : "";
  try {
    const payload = JSON.parse(block.content) as {
      type?: string;
      summary?: string;
    };
    const summary = typeof payload.summary === "string" ? payload.summary : block.raw;
    const nameMatch = summary.match(/^tool_call\s+(.+)$/);
    return {
      type: typeof payload.type === "string" ? payload.type : null,
      name: headerName || nameMatch?.[1] || summary || "tool",
      call: COMPACT_TOOL_DETAILS_OMITTED,
    };
  } catch {
    return {
      type: null,
      name: headerName || block.raw || "tool",
      call: COMPACT_TOOL_DETAILS_OMITTED,
    };
  }
}

function parseLegacyToolResult(block: ConversationBlock) {
  const lines = block.content.split("\n");
  const statusLine = lines.find((line) => line.startsWith("status: "));
  const rawStatus = statusLine?.replace(/^status:\s*/, "").trim().toLowerCase() || "ok";
  const status =
    rawStatus === "completed" || rawStatus === "ok"
      ? "ok"
      : rawStatus === "error" || rawStatus === "failed"
        ? "error"
        : "pending";
  return {
    status,
    body: status === "pending" ? "(result pending)" : COMPACT_TOOL_DETAILS_OMITTED,
  };
}

export function compactConversationBlocks(blocks: ConversationBlock[]) {
  const compacted: ConversationBlock[] = [];

  for (let index = 0; index < blocks.length; index += 1) {
    const block = blocks[index]!;

    if (block.kind === "chat" && block.content.startsWith("Reasoning summary:\n")) {
      compacted.push({
        kind: "reasoning",
        title: "Reasoning Summary",
        content: block.content.replace(/^Reasoning summary:\n/, "").trim(),
        raw: block.raw,
      });
      continue;
    }

    if (block.kind !== "tool_call") {
      if (block.kind === "tool_result") {
        const parsedResult = parseLegacyToolResult(block);
        compacted.push({
          kind: "tool",
          content: `tool call tool ${parsedResult.status.toUpperCase()}`,
          tool: {
            name: "tool",
            status: parsedResult.status,
            call: "(call details unavailable)",
            result: parsedResult.body,
            toolUseId: null,
          },
          raw: block.raw,
        });
        continue;
      }
      compacted.push(block);
      continue;
    }

    const parsedCall = parseLegacyToolCall(block);
    const nextBlock = blocks[index + 1];
    const pairedResult = nextBlock?.kind === "tool_result" ? parseLegacyToolResult(nextBlock) : null;

    if (parsedCall.type === "assistant.reasoning") {
      compacted.push({
        kind: "reasoning",
        title: "Reasoning Summary",
        content: pairedResult?.body || "(reasoning summary unavailable)",
        raw: [block.raw, nextBlock?.raw || ""].filter(Boolean).join("\n"),
      });
      if (pairedResult) index += 1;
      continue;
    }

    compacted.push({
      kind: "tool",
      content: [
        `tool call ${parsedCall.name} ${(pairedResult?.status || "pending").toUpperCase()}`,
        `Call: ${parsedCall.call}`,
        pairedResult ? `Result ${pairedResult.status.toUpperCase()}: ${pairedResult.body}` : "Result pending",
      ].join("\n"),
      tool: {
        name: parsedCall.name,
        status: pairedResult?.status || "pending",
        call: parsedCall.call,
        result: pairedResult?.body || null,
        toolUseId: null,
      },
      raw: [block.raw, nextBlock?.raw || ""].filter(Boolean).join("\n"),
    });
    if (pairedResult) index += 1;
  }

  return compacted;
}
