export const ARC_COLORS: Record<number, string> = {
  0: "#FFFFFF",
  1: "#CCCCCC",
  2: "#999999",
  3: "#666666",
  4: "#333333",
  5: "#000000",
  6: "#E53AA3",
  7: "#FF7BCC",
  8: "#F93C31",
  9: "#1E93FF",
  10: "#88D8F1",
  11: "#FFDC00",
  12: "#FF851B",
  13: "#921231",
  14: "#4FCC30",
  15: "#A356D6",
};

export function arcColor(value: number): string {
  return ARC_COLORS[value] ?? "#FF00FF";
}
