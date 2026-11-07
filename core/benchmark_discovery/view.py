"""Modello dati del pannello «Benchmark scelto dal web»: legge solo l'archivio (mai la rete)."""
from __future__ import annotations

from datetime import date, datetime

from core.asset_categories import get_selected_category_codes
from core.domain.instrument_status import active_fetch_tickers
from core.domain.positions import held_tickers
from persistence.storage import macro_cat
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


CHANGE_NOTE_DAYS = 3  # la «novita'» resta visibile per qualche giorno, poi la riga torna neutra


def change_note(change: dict | None, *, now: datetime | None = None) -> str:
    """Data («gg/mm») in cui il benchmark e' stato sostituito, se di recente; vuoto altrimenti.

    Il benchmark precedente non sta nella cella (la colonna e' stretta): lo mostra il dettaglio dello strumento."""
    if not change:
        return ""
    try:
        when = datetime.fromisoformat(str(change["changed_at"]).replace("Z", "+00:00")).astimezone()
    except (KeyError, ValueError):
        return ""
    if ((now or datetime.now().astimezone()) - when).total_seconds() > CHANGE_NOTE_DAYS * 86400:
        return ""
    return when.strftime("%d/%m")


def category_rank(settings: dict | None) -> dict[str, int]:
    """Posizione di ogni categoria nell'ordine scelto nelle impostazioni (lo stesso delle schede di Quotazioni)."""
    return {code: i for i, code in enumerate(get_selected_category_codes(settings))}


def decision_rows(data: dict, store) -> list[dict]:
    """Una riga per strumento attivo, in ordine di categoria: benchmark, grado, misura, data dei dati e stato."""
    active = active_fetch_tickers(data)
    held = held_tickers(data)
    settings = data.get("settings") if isinstance(data.get("settings"), dict) else None
    if settings is None:  # i dati non sempre portano le impostazioni: l'ordine di categoria lo decidono loro
        try:
            from persistence.storage import load_settings
            settings = load_settings()
        except Exception:
            settings = None
    rank = category_rank(settings)
    try:
        changes = store.benchmark_changes()
    except Exception:  # la storia e' solo un'informazione in piu': mai un errore di pagina
        changes = {}
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
            "change": change_note(changes.get(tk)),
            "change_prev": str((changes.get(tk) or {}).get("previous") or ""),
            "category": macro_cat(str(s.get("tipo") or "")),
            # stessa simbologia della colonna «Ptf» di Quotazioni: - in portafoglio, ★ candidato, ☆ osservato
            "ptf": "-" if tk in held else ("★" if bool(s.get("candidato_acquisto", False)) else "☆"),
        })
    ptf_order = {"-": 0, "★": 1, "☆": 2}
    rows.sort(key=lambda r: (rank.get(r["category"], len(rank)), r["category"], ptf_order[r["ptf"]], r["ticker"]))
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
