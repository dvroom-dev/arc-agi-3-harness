"use client";

import { arcColor } from "@/lib/colors";

interface ArcGridProps {
  grid: number[][];
  cellSize?: number;
  showGridLines?: boolean;
  className?: string;
}

export function ArcGrid({
  grid,
  cellSize = 8,
  showGridLines = true,
  className = "",
}: ArcGridProps) {
  if (!grid || grid.length === 0) return null;

  const rows = grid.length;
  const cols = grid[0].length;
  const gap = showGridLines ? 1 : 0;
  const width = cols * cellSize + (cols + 1) * gap;
  const height = rows * cellSize + (rows + 1) * gap;

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className={className}
      style={{ backgroundColor: showGridLines ? "#333" : "transparent" }}
    >
      {grid.map((row, y) =>
        row.map((val, x) => (
          <rect
            key={`${y}-${x}`}
            x={x * (cellSize + gap) + gap}
            y={y * (cellSize + gap) + gap}
            width={cellSize}
            height={cellSize}
            fill={arcColor(val)}
          />
        ))
      )}
    </svg>
  );
}
