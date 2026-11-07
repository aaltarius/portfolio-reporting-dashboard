"""Modello dati del pannello «Benchmark scelto dal web»: legge solo l'archivio (mai la rete)."""
from __future__ import annotations

from datetime import date

from core.domain.instrument_status import active_fetch_tickers
from core.verified_benchmarks.freshness import MAX_REFERENCE_AGE_DAYS, age_days


def data_end(store, assignment: dict | None) -> str:
    """Ultimo giorno di dati del benchmark scelto, letto dall'archivio dei prezzi.

    `coverage_end` dell'assegnazione e' la data al momento della scelta e non segue gli aggiornamenti dei prezzi:
    e' solo il ripiego quando la serie non e' in archivio."""
    if not assignment:
        return ""
    code = str(assignment.get("ticker") or "")
    try:
        last = store.last_date(code) if code else None
    except Exception:
        last = None
    return str(last or assignment.get("coverage_end") or "")


def _state(override: dict | None, assignment: dict | None, end: str = "") -> str:
    if override:
        return "manual"
    if not assignment or not assignment.get("discovery"):
        return "pending"
    age = age_days(end or assignment.get("coverage_end"), as_of=date.today())
    return "stale" if age is None or age > MAX_REFERENCE_AGE_DAYS else "ok"


def decision_rows(data: dict, store) -> list[dict]:
    """Una riga per strumento attivo: benchmark, grado, misura, data dei dati e stato."""
    active = active_fetch_tickers(data)
    rows = []
    for s in data.get("strumenti", []):
        if not isinstance(s, dict) or not s.get("ticker") or str(s["ticker"]) not in active:
            continue
        tk = str(s["ticker"])
        override, a = store.override(tk), store.assignment(tk)
        disc = (a or {}).get("discovery") or {}
        end = data_end(store, a) if disc else ""
        rows.append({
            "ticker": tk, "name": str(s.get("nome") or ""),
            "benchmark": (override or {}).get("benchmark_code") or ((a or {}).get("ticker", "") if disc else ""),
            "label": (override or {}).get("benchmark_label") or ((a or {}).get("label", "") if disc else ""),
            "grade": "MANUALE" if override else ((a or {}).get("grade", "") if disc else ""),
            "corr": disc.get("corr"), "te_pct": disc.get("te_pct"),
            "updated": end,
            "state": _state(override, a, end),
        })
    return rows


def decision_detail(store, ticker: str) -> dict | None:
    """Il «perche'» di una scelta: profilo, frasi cercate, candidati valutati, scelta."""
    a = store.assignment(ticker)
    disc = (a or {}).get("discovery")
    if not disc:
        return None
    trace = disc.get("trace") or {}
    candidates = []
    for lv in trace.get("levels", []):
        candidates.extend(lv.get("evaluated", []))
    candidates.sort(key=lambda e: -(e.get("score") or -1))
    queries = [q for lv in trace.get("levels", []) for q in lv.get("queries", [])]
    return {"benchmark": a.get("ticker"), "label": a.get("label"), "grade": a.get("grade"),
            "profile": trace.get("profile", {}), "queries": queries, "candidates": candidates,
            "choice": trace.get("choice") or {"symbol": a.get("ticker")}, "legs": trace.get("legs", []),
            "decided_at": disc.get("decided_at", "")}
