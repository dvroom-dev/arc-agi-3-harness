export function hexCharToNumber(ch: string): number {
  const code = ch.charCodeAt(0);
  if (code >= 48 && code <= 57) return code - 48;
  if (code >= 65 && code <= 70) return code - 65 + 10;
  if (code >= 97 && code <= 102) return code - 97 + 10;
  return 0;
}

export function parseHexGrid(text: string): number[][] {
  const lines = text.trim().split("\n").filter(Boolean);
  return lines.map((line) => Array.from(line.trim()).map(hexCharToNumber));
}
