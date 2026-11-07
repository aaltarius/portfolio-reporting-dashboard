"""Comandi dell'utente sul benchmark: ricalcolo della scelta e aggiornamento dei prezzi delle serie scelte.

Entrambi partono solo da un click esplicito (ADR-0018), mai dal render. Una rete assente o un
fallimento non cancella nulla di quanto e' gia' salvato.
"""
from __future__ import annotations

from typing import Callable

from core.domain.instrument_status import active_fetch_tickers

from .decide import CandidateSource
from .runner import run_for_instrument


def _tickers(data: dict, target: str | None) -> list[str]:
    known = [str(s["ticker"]) for s in data.get("strumenti", []) if isinstance(s, dict) and s.get("ticker")]
    if target is not None:
        if target not in known:
            raise ValueError("Strumento sconosciuto: " + target)
        return [target]
    active = active_fetch_tickers(data)
    return [tk for tk in known if tk in active]


def _source(source: CandidateSource | None) -> CandidateSource:
    if source is not None:
        return source
    from .yahoo_source import YahooSource
    return YahooSource()


def rediscover(data: dict, *, store=None, source: CandidateSource | None = None, target_instrument: str | None = None,
               progress: Callable[[str, int, int], None] | None = None) -> dict:
    """Ricerca di nuovo il benchmark degli strumenti attivi (o di uno solo) e salva le decisioni."""
    from core.verified_benchmarks import IndexStore
    store = store or IndexStore()
    src = _source(source)
    tickers = _tickers(data, target_instrument)
    items, pending = [], []
    for i, tk in enumerate(tickers, 1):
        if progress:
            progress(tk, i, len(tickers))
        try:
            d = run_for_instrument(data, tk, store=store, source=src)
        except Exception as exc:  # un fallimento non ferma gli altri strumenti
            items.append({"ticker": tk, "status": "ERRORE", "benchmark": "", "grade": "", "detail": f"{type(exc).__name__}: {exc}"[:200]})
            pending.append(tk)
            continue
        if d is None or d.status != "SCELTO":
            items.append({"ticker": tk, "status": "IN_ATTESA", "benchmark": "", "grade": "",
                          "detail": "nessun candidato disponibile: decisione precedente conservata"})
            pending.append(tk)
        else:
            items.append({"ticker": tk, "status": "SCELTO", "benchmark": d.choice.symbol, "grade": d.grade,
                          "detail": d.choice.name})
    references = {}
    if target_instrument is None:  # il ricalcolo completo comprende i riferimenti del benchmark di portafoglio
        from .portfolio import discover_references
        references = discover_references(store, src)
    return {"requested": len(tickers), "resolved": len(tickers) - len(pending), "pending": pending, "items": items,
            "references": references}


def refresh_series(data: dict, *, store=None, source: CandidateSource | None = None,
                   target_instrument: str | None = None) -> dict:
    """Riscarica i prezzi delle serie GIA' scelte, senza cambiare la scelta."""
    from core.verified_benchmarks import IndexStore
    store = store or IndexStore()
    src = _source(source)
    updated = failed = 0
    items = []
    for tk in _tickers(data, target_instrument):
        override = store.override(tk)
        a = store.assignment(tk)
        codes = ([override["benchmark_code"]] if override else []) or (
            [a["ticker"]] if a and a.get("discovery") and not str(a.get("ticker", "")).startswith("BLEND:") else [])
        if a and a.get("discovery") and str(a.get("ticker", "")).startswith("BLEND:") and not override:
            codes = [c["series_id"] for c in (a.get("components") or []) if c.get("series_id")]
        if not codes:
            continue
        got_any = False
        for code in codes:
            series = src.history(code)
            if series:
                store.upsert(code, series, source="discovery", replace_existing=True)
                store.mark_fetch(code, "ok", "discovery")
                got_any = True
            else:
                store.mark_fetch(code, "failed", "discovery")
        if got_any and a and str(a.get("ticker", "")).startswith("BLEND:") and not override:
            _rebuild_blend(store, tk, a)
        updated += int(got_any)
        failed += int(not got_any)
        items.append({"ticker": tk, "status": "AGGIORNATO" if got_any else "FALLITO", "codes": codes})
    if target_instrument is None:  # l'aggiornamento completo comprende i riferimenti del benchmark di portafoglio
        from .portfolio import REFERENCE_PROFILES
        for family in REFERENCE_PROFILES:
            a = store.assignment("PORTFOLIO:" + family)
            code = str(a.get("ticker") or "") if a and a.get("discovery") else ""
            if not code:
                continue
            series = src.history(code)
            if series:
                store.upsert(code, series, source="discovery", replace_existing=True)
                store.mark_fetch(code, "ok", "discovery")
            else:
                store.mark_fetch(code, "failed", "discovery")
            updated += int(bool(series))
            failed += int(not series)
            items.append({"ticker": "PORTFOLIO:" + family, "status": "AGGIORNATO" if series else "FALLITO", "codes": [code]})
    return {"requested": len(items), "updated": updated, "failed": failed, "items": items}


def _rebuild_blend(store, ticker: str, assignment: dict) -> None:
    from .scoring import blend_series
    legs = [(store.read(c["series_id"]), c["weight_pct"]) for c in assignment.get("components", [])]
    series = blend_series(legs)
    if series:
        store.upsert(assignment["ticker"], series, source="discovery", replace_existing=True)
