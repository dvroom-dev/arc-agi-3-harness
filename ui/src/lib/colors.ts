// ARC-AGI-3 16-color palette (0-F hex)
// Matches game_state.py ARC_COLORS_RGB / ARC web preview renderer
export const ARC_COLORS: Record<number, string> = {
  0: "#FFFFFF",  // white
  1: "#CCCCCC",  // light-grey
  2: "#999999",  // grey
  3: "#666666",  // dark-grey
  4: "#333333",  // charcoal
  5: "#000000",  // black
  6: "#E53AA3",  // magenta
  7: "#FF7BCC",  // pink
  8: "#F93C31",  // red
  9: "#1E93FF",  // blue
  10: "#88D8F1", // light-cyan
  11: "#FFDC00", // yellow
  12: "#FF851B", // orange
  13: "#921231", // maroon
  14: "#4FCC30", // green
  15: "#A356D6", // purple
};

export function arcColor(value: number): string {
  return ARC_COLORS[value] ?? "#FF00FF"; // magenta fallback for unknown
}
