#!/usr/bin/env python3
"""Repository lint checks."""

from __future__ import annotations

from pathlib import Path


MAX_LINES = 500
ROOT = Path(__file__).resolve().parent.parent
CHECK_SUFFIXES = {".py"}
EXCLUDED_DIRS = {
    ".git",
    ".venv",
    ".ctxs",
    "runs",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "environment_files",
}


def iter_candidate_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        if any(part in EXCLUDED_DIRS for part in rel.parts):
            continue
        if path.suffix not in CHECK_SUFFIXES:
            continue
        files.append(path)
    return sorted(files)


def main() -> int:
    violations: list[tuple[str, int]] = []
    for path in iter_candidate_files():
        line_count = len(path.read_text(encoding="utf-8").splitlines())
        if line_count > MAX_LINES:
            rel = path.relative_to(ROOT).as_posix()
            violations.append((rel, line_count))

    if not violations:
        print("lint ok: no files exceed 500 lines")
        return 0

    print("lint failed: files over 500 lines")
    for rel, count in violations:
        print(f"- {rel}: {count} lines")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
