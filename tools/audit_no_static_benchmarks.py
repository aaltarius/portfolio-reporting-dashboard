#!/usr/bin/env python3
"""Audit statico: nessun catalogo benchmark hardcoded in produzione. Adattato
da HANDOFF_PROGRAMMATORE_BENCHMARK_CDS/tools/audit_no_static_benchmarks.py
per essere richiamabile sia da CLI sia da test (run_audit)."""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Iterator

BANNED_IDENTIFIERS = {
    "BENCHMARK_BY_TICKER", "BENCHMARK_BY_ISIN", "BENCHMARK_BY_TYPE",
    "BENCHMARK_BY_MACRO", "BENCHMARK_BY_INDEX_PATTERN", "LEGACY_BENCH",
}

#: Le fixture di regressione (111 strumenti noti + baseline C/D/S congelata)
#: sono materiale di test: se il codice di produzione le importasse, il motore
#: risponderebbe da un catalogo statico invece che dalle fonti online — cioe'
#: esattamente cio' che BANNED_IDENTIFIERS vieta, con un altro nome (spec
#: sezione 10). Vietato anche il modulo che le carica.
BANNED_FIXTURE_REFERENCES = {
    "fixtures_loader",
    "known_instruments.json",
    "cds_regression_baseline_111.json",
}

SKIP_DIRS = {
    ".git", ".venv", "venv", "__pycache__", "node_modules",
    ".mypy_cache", ".pytest_cache", "tests", "test", "fixtures",
    "reference", "docs", "HANDOFF_PROGRAMMATORE_BENCHMARK_CDS",
}

_SELF_PATH = Path(__file__).resolve()


def production_python_files(root: Path) -> Iterator[Path]:
    for path in root.rglob("*.py"):
        if path.resolve() == _SELF_PATH:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        yield path


def fixture_reference_failures(rel: Path, text: str) -> list[str]:
    """Riferimenti alle fixture di test trovati in un file di produzione."""
    found: list[str] = []
    for name in sorted(BANNED_FIXTURE_REFERENCES):
        # `\b` non funziona a ridosso di un punto: i nomi di file sono
        # cercati come letterali, l'identificatore di modulo con i confini.
        pattern = re.escape(name) if "." in name else rf"\b{re.escape(name)}\b"
        if re.search(pattern, text):
            found.append(f"{rel}: test fixture reference {name} in production code")
    return found


def run_audit(root: Path) -> tuple[bool, list[str]]:
    failures: list[str] = []
    for path in production_python_files(root):
        text = path.read_text(encoding="utf-8", errors="replace")
        rel = path.relative_to(root)
        for name in BANNED_IDENTIFIERS:
            if re.search(rf"\b{re.escape(name)}\b", text):
                failures.append(f"{rel}: banned identifier {name}")
        if re.search(r"""["']NON\s+RISOLTO["']""", text, flags=re.I):
            failures.append(f"{rel}: normal NON RISOLTO literal found")
        failures.extend(fixture_reference_failures(rel, text))
    return (not failures, failures)


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    passed, failures = run_audit(root)
    if not passed:
        print("AUDIT FAILED")
        for failure in failures:
            print(" -", failure)
        return 1
    print("AUDIT PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
