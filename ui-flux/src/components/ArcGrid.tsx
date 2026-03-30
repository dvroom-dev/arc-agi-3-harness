"use client";

import { arcColor } from "@/lib/colors";

interface ArcGridProps {
  grid: number[][];
  cellSize?: number;
}

export default function ArcGrid({ grid, cellSize = 8 }: ArcGridProps) {
  if (!grid.length) return null;
  const rows = grid.length;
  const cols = grid[0]?.length ?? 0;
  const gap = 1;
  const width = cols * cellSize + (cols + 1) * gap;
  const height = rows * cellSize + (rows + 1) * gap;
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className="rounded-xl bg-black/35 shadow-[0_0_0_1px_rgba(255,255,255,0.08)]">
      {grid.map((row, y) =>
        row.map((value, x) => (
          <rect
            key={`${y}-${x}`}
            x={x * (cellSize + gap) + gap}
            y={y * (cellSize + gap) + gap}
            width={cellSize}
            height={cellSize}
            fill={arcColor(value)}
          />
        )),
      )}
    </svg>
  );
}
