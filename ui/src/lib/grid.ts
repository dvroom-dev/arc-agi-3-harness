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
  const lines = text.trim().split("\n");
  return lines.map((line) =>
    Array.from(line.trim()).map(hexCharToNumber)
  );
}

/**
 * Parse a grid from a turn trace markdown file.
 * Looks for the grid inside a fenced code block.
 */
export function parseGridFromTrace(raw: string): number[][] | null {
  const gridMatch = raw.match(/```\n([\s\S]*?)\n```/);
  if (!gridMatch) return null;
  return parseHexGrid(gridMatch[1]);
}
