#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path

BANNED_IDENTIFIERS = {
    "BENCHMARK_BY_TICKER",
    "BENCHMARK_BY_ISIN",
    "BENCHMARK_BY_TYPE",
    "BENCHMARK_BY_MACRO",
    "BENCHMARK_BY_INDEX_PATTERN",
    "LEGACY_BENCH",
    "REFERENCE_FAMILIES",
    "BENCHMARK_IDENTITIES",
    "STATIC_FAMILY",
}

PRODUCTION_HINTS = ("benchmark", "resolver", "analysis", "classification", "portfolio", "core")

SKIP_DIRS = {
    ".git", ".venv", "venv", "__pycache__", "node_modules",
    ".mypy_cache", ".pytest_cache", "tests", "test", "fixtures",
    "reference", "docs",
}

def production_python_files(root: Path):
    for path in root.rglob("*.py"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        yield path

def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    failures: list[str] = []

    for path in production_python_files(root):
        text = path.read_text(encoding="utf-8", errors="replace")
        rel = path.relative_to(root)

        for name in BANNED_IDENTIFIERS:
            if re.search(rf"\b{re.escape(name)}\b", text):
                failures.append(f"{rel}: banned identifier {name}")

        # Detect suspicious direct dictionaries in benchmark/resolver-oriented modules.
        lower_path = str(rel).lower()
        if any(h in lower_path for h in PRODUCTION_HINTS):
            if re.search(r"\b(?:ticker|isin)\s*[:=].{0,50}\bbenchmark\b", text, flags=re.I | re.S):
                failures.append(f"{rel}: suspicious ticker/ISIN -> benchmark coupling")

        # Explicit normal output string must not be unresolved.
        if re.search(r"""["']NON\s+RISOLTO["']""", text, flags=re.I):
            failures.append(f"{rel}: normal NON RISOLTO literal found")

    if failures:
        print("AUDIT FAILED")
        for x in failures:
            print(" -", x)
        return 1

    print("AUDIT PASS")
    print("No legacy static benchmark catalogs found in production Python code.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
