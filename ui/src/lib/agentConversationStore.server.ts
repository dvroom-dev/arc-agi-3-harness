import fs from "fs/promises";
import path from "path";
import { parseConversationBlocks, type ConversationBlock } from "@/lib/conversation";
import { runDir } from "@/lib/paths";

interface PatchOp {
  op: "equal" | "delete" | "insert";
  lines?: string[];
}

interface ForkPatch {
  ops: PatchOp[];
}

interface ConversationIndexFork {
  id?: string;
  parentId?: string | null;
  createdAt?: string;
  actionSummary?: string | null;
}

interface ConversationIndexFile {
  headId?: string;
  headIds?: string[];
  forks?: ConversationIndexFork[];
}

interface ForkFile {
  id?: string;
  parentId?: string | null;
  storage?: "snapshot" | "patch";
  documentText?: string;
  patch?: ForkPatch;
}

export interface StoredConversationBranch {
  key: string;
  conversationId: string;
  forkId: string;
  parentId: string | null;
  createdAt: string;
  mode: string | null;
  active: boolean;
  head: boolean;
  actionSummary: string | null;
  documentText: string;
  initialUserPreview: string | null;
  nextCreatedAt: string | null;
}

function splitLines(text: string): string[] {
  return text === "" ? [""] : text.split(/\r?\n/);
}

function applyPatch(baseText: string, patch: ForkPatch): string {
  const baseLines = splitLines(baseText);
  let index = 0;
  const out: string[] = [];

  for (const op of patch.ops ?? []) {
    const lines = op.lines ?? [];
    if (op.op === "equal") {
      for (const line of lines) {
        if (baseLines[index] !== line) {
          throw new Error("patch mismatch: equal segment does not match base");
        }
        out.push(line);
        index += 1;
      }
      continue;
    }

    if (op.op === "delete") {
      for (const line of lines) {
        if (baseLines[index] !== line) {
          throw new Error("patch mismatch: delete segment does not match base");
        }
        index += 1;
      }
      continue;
    }

    if (op.op === "insert") {
      out.push(...lines);
    }
  }

  if (index !== baseLines.length) {
    throw new Error("patch mismatch: base length mismatch");
  }

  return out.join("\n");
}

function parseTime(value: string | null | undefined): number {
  const parsed = value ? Date.parse(value) : Number.NaN;
  return Number.isFinite(parsed) ? parsed : 0;
}

function frontmatterValue(documentText: string, key: string): string | null {
  const match = documentText.match(new RegExp(`^${key}:\\s*(.+)$`, "m"));
  return match?.[1]?.trim() || null;
}

function firstUserPreview(documentText: string): string | null {
  const blocks = parseConversationBlocks(documentText);
  const block = blocks.find((entry) => entry.kind === "chat" && entry.role === "user");
  if (!block) return null;
  return block.content.replace(/\s+/g, " ").trim().slice(0, 240) || null;
}

async function loadForkFiles(
  runId: string,
  conversationId: string
): Promise<{ index: ConversationIndexFile; forkMap: Map<string, ForkFile> }> {
  const conversationDir = path.join(
    runDir(runId),
    ".ai-supervisor",
    "conversations",
    conversationId
  );
  const index = JSON.parse(
    await fs.readFile(path.join(conversationDir, "index.json"), "utf-8")
  ) as ConversationIndexFile;
  const forkMap = new Map<string, ForkFile>();

  for (const fork of index.forks ?? []) {
    if (typeof fork.id !== "string") continue;
    const forkPath = path.join(conversationDir, "forks", `${fork.id}.json`);
    const payload = JSON.parse(await fs.readFile(forkPath, "utf-8")) as ForkFile;
    forkMap.set(fork.id, payload);
  }

  return { index, forkMap };
}

function reconstructForkDocument(
  forkMap: Map<string, ForkFile>,
  forkId: string,
  memo: Map<string, string>
): string {
  const cached = memo.get(forkId);
  if (cached !== undefined) return cached;
  const fork = forkMap.get(forkId);
  if (!fork) throw new Error(`missing fork ${forkId}`);

  let documentText: string;
  if (fork.storage !== "patch") {
    documentText = typeof fork.documentText === "string" ? fork.documentText : "";
  } else {
    const parentId = typeof fork.parentId === "string" ? fork.parentId : null;
    if (!parentId) throw new Error(`fork ${forkId} missing parent`);
    const parentText = reconstructForkDocument(forkMap, parentId, memo);
    if (!fork.patch) throw new Error(`fork ${forkId} missing patch payload`);
    documentText = applyPatch(parentText, fork.patch);
  }

  memo.set(forkId, documentText);
  return documentText;
}

export async function loadStoredConversationBranches(
  runId: string,
  conversationId: string
): Promise<StoredConversationBranch[]> {
  const { index, forkMap } = await loadForkFiles(runId, conversationId);
  const memo = new Map<string, string>();
  const forks = (index.forks ?? [])
    .filter((fork): fork is Required<Pick<ConversationIndexFork, "id" | "createdAt">> & ConversationIndexFork =>
      typeof fork.id === "string" && typeof fork.createdAt === "string"
    )
    .sort((a, b) => parseTime(a.createdAt) - parseTime(b.createdAt));
  const headForkIds = new Set(
    Array.isArray(index.headIds)
      ? index.headIds.filter((forkId): forkId is string => typeof forkId === "string")
      : []
  );
  const activeForkId =
    typeof index.headId === "string"
      ? index.headId
      : Array.isArray(index.headIds) && typeof index.headIds[0] === "string"
        ? index.headIds[0]
        : null;

  return forks.map((fork, idx) => {
    const documentText = reconstructForkDocument(forkMap, fork.id, memo);
    return {
      key: fork.id,
      conversationId,
      forkId: fork.id,
      parentId: typeof fork.parentId === "string" ? fork.parentId : null,
      createdAt: fork.createdAt,
      mode: frontmatterValue(documentText, "mode"),
      active: fork.id === activeForkId,
      head: headForkIds.has(fork.id),
      actionSummary:
        typeof fork.actionSummary === "string"
          ? fork.actionSummary ?? null
          : null,
      documentText,
      initialUserPreview: firstUserPreview(documentText),
      nextCreatedAt: forks[idx + 1]?.createdAt ?? null,
    } satisfies StoredConversationBranch;
  });
}

export function sliceBranchDocumentSeed(documentText: string): ConversationBlock[] {
  return parseConversationBlocks(documentText);
}
