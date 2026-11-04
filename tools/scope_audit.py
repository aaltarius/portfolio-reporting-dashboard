"""Inventario delle chiamate di cache e della firma dati che ciascuna usa (PF-05).

Trova, con l'analisi del codice, le chiamate a ``get_or_build`` /
``get_or_build_registered_figure`` che passano ``chart_id`` e ``data_sig``
e classifica la firma come *globale* (variabile o espressione sulla firma
dell'intero portafoglio) oppure *scopata* (costruita da una funzione
``build_*_signature``). Serve a decidere quali figure migrare a firme per
ambito.

Uso::

    python -m tools.scope_audit            # stampa la tabella Markdown
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCAN_DIRS = ("ui", "core")
_CALL_NAMES = {"get_or_build", "get_or_build_registered_figure"}


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def find_cache_calls(source: str, filename: str) -> list[dict[str, Any]]:
    """Chiamate di cache con ``chart_id`` e ``data_sig`` in un sorgente Python."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    # Assegnazioni semplici ``nome = espressione``: permettono di risalire alla
    # firma quando la chiamata riceve una variabile locale.
    assigned: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            value = ast.unparse(node.value)
            if is_scoped(value):
                assigned[node.targets[0].id] = value
    found: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _call_name(node) not in _CALL_NAMES:
            continue
        kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg}
        if "chart_id" not in kwargs or "data_sig" not in kwargs:
            continue
        chart = kwargs["chart_id"]
        chart_id = chart.value if isinstance(chart, ast.Constant) else ast.unparse(chart)
        found.append(
            {
                "file": filename,
                "line": node.lineno,
                "chart_id": str(chart_id),
                "data_sig": assigned.get(ast.unparse(kwargs["data_sig"]), ast.unparse(kwargs["data_sig"])),
            }
        )
    return sorted(found, key=lambda item: (item["file"], item["line"]))


def is_scoped(signature_source: str) -> bool:
    """Firma costruita da una funzione ``build_*_signature`` = per ambito."""
    return "build_" in signature_source and "signature" in signature_source and "(" in signature_source


def format_markdown(calls: list[dict[str, Any]]) -> str:
    out = ["| chart_id | file:riga | firma | ambito |", "|---|---|---|---|"]
    for item in calls:
        scope = "scopata" if is_scoped(item["data_sig"]) else "globale"
        sig = item["data_sig"].replace("|", "\\|")
        if len(sig) > 70:
            sig = sig[:67] + "..."
        out.append(f"| {item['chart_id']} | {item['file']}:{item['line']} | `{sig}` | {scope} |")
    return "\n".join(out)


def scan_repository() -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for directory in SCAN_DIRS:
        for path in sorted((ROOT / directory).rglob("*.py")):
            rel = path.relative_to(ROOT).as_posix()
            calls.extend(find_cache_calls(path.read_text(encoding="utf-8", errors="ignore"), rel))
    return calls


def main() -> int:
    print(format_markdown(scan_repository()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
