/**
 * Parse a hex character to a number (0-15).
 * Handles 0-9, A-F, a-f.
 */
export function hexCharToNumber(ch: string): number {
  const code = ch.charCodeAt(0);
  if (code >= 48 && code <= 57) return code - 48;       // '0'-'9'
  if (code >= 65 && code <= 70) return code - 65 + 10;   // 'A'-'F'
  if (code >= 97 && code <= 102) return code - 97 + 10;  // 'a'-'f'
  return 0;
}

/**
 * Parse a grid from hex-encoded text lines (one hex char per cell).
 */
export function parseHexGrid(text: string): number[][] {
  const lines = text.trim().split("\n").filter(Boolean);
  return lines.map((line) =>
    Array.from(line.trim()).map(hexCharToNumber)
  );
}

function isHexGridBlock(block: string): boolean {
  const lines = block
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  if (lines.length < 2) return false;
  const width = lines[0]?.length ?? 0;
  if (width === 0) return false;
  return lines.every((line) => line.length === width && /^[0-9A-Fa-f]+$/.test(line));
}

function extractGridBlockForSection(raw: string, sectionTitle: string): string | null {
  const escapedTitle = sectionTitle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = raw.match(
    new RegExp(`## ${escapedTitle}\\s*\\n\`\`\`(?:[A-Za-z0-9_-]+)?\\n([\\s\\S]*?)\\n\`\`\``, "m")
  );
  if (!match?.[1]) return null;
  return isHexGridBlock(match[1]) ? match[1] : null;
}

/**
 * Parse a grid from a turn trace markdown file.
 * Prefer the labeled Final/Initial Grid sections, then fall back to the
 * last fenced block that actually looks like a hex grid.
 */
export function parseGridFromTrace(raw: string): number[][] | null {
  const labeledGrid =
    extractGridBlockForSection(raw, "Final Grid") ??
    extractGridBlockForSection(raw, "Initial Grid");
  if (labeledGrid) {
    return parseHexGrid(labeledGrid);
  }

  const blocks = Array.from(
    raw.matchAll(/```(?:[A-Za-z0-9_-]+)?\n([\s\S]*?)\n```/g),
    (match) => match[1]
  ).filter((block): block is string => Boolean(block) && isHexGridBlock(block));

  if (blocks.length === 0) return null;
  return parseHexGrid(blocks[blocks.length - 1]);
}
