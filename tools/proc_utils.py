from __future__ import annotations

from pathlib import Path


def read_proc_start_ticks(pid: int) -> int | None:
    stat_path = Path("/proc") / str(int(pid)) / "stat"
    try:
        raw = stat_path.read_text(encoding="utf-8")
    except Exception:
        return None
    try:
        # /proc/<pid>/stat field 22 is process starttime in clock ticks.
        return int(raw.rsplit(")", 1)[1].split()[19])
    except Exception:
        return None

