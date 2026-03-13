export interface ConversationBlock {
  kind: "frontmatter" | "chat" | "file" | "text" | "tool_call" | "tool_result";
  title?: string;
  role?: string;
  content: string;
  header?: string;
  meta?: Record<string, string>;
  raw: string;
}

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
