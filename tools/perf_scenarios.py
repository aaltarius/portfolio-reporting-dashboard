"""Misura ripetibile degli scenari di avvio di Sestante (PF-01).

Esegue ``app.py`` con ``streamlit.testing.v1.AppTest`` (nessun browser) e
legge i tempi dalle righe ``[PAGE_RENDER]`` / ``[DASHBOARD_RENDER]`` del log
dell'applicazione. Gli scenari con browser reale e quelli di aggiornamento
quotazioni si misurano a mano con lo stesso protocollo (vedi
``docs/performance/``): questo strumento copre ``cold_start`` e ``warm_rerun``.

Uso::

    python -m tools.perf_scenarios cold_start 3
    python -m tools.perf_scenarios warm_rerun 3
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

from tools.perf_render_log_analyzer import _plain_page_name

ROOT = Path(__file__).resolve().parent.parent
LOG_FILE = ROOT / "data" / "logs" / "portafoglio.log"

SCENARIOS = ("cold_start", "warm_rerun")

_PAGE_RE = re.compile(r"\[PAGE_RENDER\] step=\d+/\d+ label=(?P<label>.+?) status=\S+ elapsed=(?P<sec>[\d.]+)s")
_TOTAL_RE = re.compile(r"\[DASHBOARD_RENDER\] .*elapsed=(?P<sec>[\d.]+)s")


def parse_app_log_lines(lines: Iterable[str]) -> list[dict[str, Any]]:
    """Raggruppa le righe del log in run completi (terminano con DASHBOARD_RENDER).

    Un run senza riga finale (interrotto o ancora in corso) non viene restituito.
    """
    runs: list[dict[str, Any]] = []
    pages: dict[str, float] = {}
    for line in lines:
        page = _PAGE_RE.search(line)
        if page:
            pages[_plain_page_name(page.group("label"))] = float(page.group("sec"))
            continue
        total = _TOTAL_RE.search(line)
        if total:
            runs.append({"dashboard_seconds": float(total.group("sec")), "pages": pages})
            pages = {}
    return runs


def format_markdown_table(rows: list[dict[str, Any]]) -> str:
    """Tabella Markdown con una riga per esecuzione."""
    page_names: list[str] = []
    for row in rows:
        for name in row.get("pages", {}):
            if name not in page_names:
                page_names.append(name)
    header = ["scenario", "run", "dashboard (s)", *page_names]
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    for row in rows:
        cells = [str(row["scenario"]), str(row["run"]), f"{row['dashboard_seconds']:.3f}"]
        cells += [f"{row['pages'].get(name, 0.0):.3f}" for name in page_names]
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


def _log_position() -> int:
    return LOG_FILE.stat().st_size if LOG_FILE.exists() else 0


def _runs_since(position: int) -> list[dict[str, Any]]:
    with open(LOG_FILE, "rb") as fh:
        fh.seek(position)
        text = fh.read().decode("utf-8", errors="replace")
    return parse_app_log_lines(text.splitlines())


_CHILD = (
    "import sys; sys.path.insert(0, r'{root}'); "
    "from streamlit.testing.v1 import AppTest; "
    "at = AppTest.from_file(r'{app}', default_timeout=300); "
    "[at.run() for _ in range({n})]"
)


def _run_child(n_runs: int) -> None:
    code = _CHILD.format(root=str(ROOT), app=str(ROOT / "app.py"), n=n_runs)
    subprocess.run([sys.executable, "-c", code], cwd=str(ROOT), check=True)


def run_scenarios(scenario: str, repeats: int, *, watcher: str = "poll") -> list[dict[str, Any]]:
    """Esegue ``repeats`` misure dello scenario e ne restituisce i tempi.

    ``cold_start``: un processo nuovo per ogni ripetizione (primo run).
    ``warm_rerun``: un solo processo, si scarta il primo run e si misurano i successivi.
    ``watcher`` è registrato nel risultato (AppTest non avvia il server).
    """
    if scenario not in SCENARIOS:
        raise ValueError(f"scenario non supportato: {scenario}")
    results: list[dict[str, Any]] = []
    if scenario == "cold_start":
        for i in range(1, repeats + 1):
            position = _log_position()
            _run_child(1)
            runs = _runs_since(position)
            if runs:
                results.append({"scenario": scenario, "run": i, "watcher": watcher, **runs[-1]})
        return results
    position = _log_position()
    _run_child(repeats + 1)
    for i, run in enumerate(_runs_since(position)[1:], start=1):
        results.append({"scenario": scenario, "run": i, "watcher": watcher, **run})
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", choices=SCENARIOS)
    parser.add_argument("repeats", type=int, nargs="?", default=3)
    args = parser.parse_args()
    rows = run_scenarios(args.scenario, args.repeats)
    print(format_markdown_table(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
