"""Audit statico: individua calcoli finanziari fatti localmente in ui/
invece che richiamando core/ (regola non negoziabile del repo). Stesso
pattern di tools/cache_surface_audit.py, applicato a una classe diversa di
problema — trovato per la prima volta il 2026-08-13/14 (vedi
docs/superpowers/specs/2026-08-14-pianificazione-confronto-strumenti-design.md).

Uso: `python tools/finance_formula_audit.py` stampa un report markdown.
Ogni hit va rivisto a mano: il tool segnala pattern sospetti, non prova
automaticamente una violazione (falsi positivi noti: percentuali di un
subtotale gia' pronto per un grafico a torta, scostamenti spesa/budget)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = ("ui",)

PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("return_normalization", re.compile(r"\.pct_change\(|/\s*\w+(\.iloc\[0\]|\[0\])\s*-\s*1|\.cumprod\(")),
    ("statistics", re.compile(r"\.std\(|\.corr\(|\bsharpe\b|\bcagr\b|\bdrawdown\b|tracking.?error|\bbeta\b", re.IGNORECASE)),
    ("tax_rate", re.compile(r"aliquota|tax_rate|imposta", re.IGNORECASE)),
)


@dataclass(frozen=True)
class FormulaHit:
    family: str
    path: Path
    line_no: int
    text: str


def _iter_files() -> list[Path]:
    files: list[Path] = []
    for root in SCAN_ROOTS:
        path = PROJECT_ROOT / root
        if path.is_dir():
            files.extend(
                p
                for p in path.rglob("*.py")
                if "__pycache__" not in p.parts and not any(part.startswith(".") for part in p.parts)
            )
    return sorted(files)


def collect_formula_hits() -> list[FormulaHit]:
    hits: list[FormulaHit] = []
    for path in _iter_files():
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        for idx, line in enumerate(lines, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            for family, pattern in PATTERNS:
                if pattern.search(stripped):
                    hits.append(FormulaHit(family, path.relative_to(PROJECT_ROOT), idx, stripped[:180]))
    return hits


def build_markdown_report() -> str:
    hits = collect_formula_hits()
    by_family: dict[str, list[FormulaHit]] = {}
    for hit in hits:
        by_family.setdefault(hit.family, []).append(hit)

    lines = [
        "# Audit statico formule finanziarie fuori da core/",
        "",
        "Generato da `tools/finance_formula_audit.py`. Ogni hit va rivisto a",
        "mano: il tool segnala pattern sospetti in `ui/`, non prova una",
        "violazione automaticamente. Se un hit richiama una funzione gia'",
        "in core/ (formattazione/etichette di un valore gia' calcolato), non",
        "e' una violazione.",
        "",
        "## Sintesi",
        "",
        "| Famiglia | Occorrenze |",
        "|---|---:|",
    ]
    for family in sorted(by_family):
        lines.append(f"| `{family}` | {len(by_family[family])} |")

    lines.extend(["", "## Dettaglio", ""])
    for family in sorted(by_family):
        lines.append(f"### {family}")
        lines.append("")
        for hit in by_family[family]:
            lines.append(f"- `{hit.path}:{hit.line_no}` - `{hit.text}`")
        lines.append("")
    if not hits:
        lines.append("Nessuna occorrenza trovata.")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    print(build_markdown_report(), end="")


if __name__ == "__main__":
    main()
