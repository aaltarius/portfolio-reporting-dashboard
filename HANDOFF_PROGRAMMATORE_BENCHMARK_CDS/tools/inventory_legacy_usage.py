#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path

PATTERNS = [
    r"\bresolve_instrument_benchmark\b",
    r"\bBenchmarkAssignment\b",
    r"\bBENCHMARK_BY_[A-Z_]+\b",
    r"\bLEGACY_BENCH\b",
    r"\bknown_benchmark_catalog\b",
    r"\bbenchmark_ticker\b",
    r"\bbenchmark_label\b",
    r"\bbenchmark_source\b",
    r"\bcore_pct\b",
    r"\bdefensive_pct\b",
    r"\bsatellite_pct\b",
]

SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules", ".mypy_cache", ".pytest_cache"}

def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    rx = re.compile("|".join(f"(?:{p})" for p in PATTERNS))
    hits = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in {".py", ".json", ".toml", ".yaml", ".yml", ".md", ".txt"}:
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            continue
        for no, line in enumerate(lines, 1):
            if rx.search(line):
                hits += 1
                print(f"{path.relative_to(root)}:{no}: {line.strip()}")
    print(f"\nTOTAL_HITS={hits}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
