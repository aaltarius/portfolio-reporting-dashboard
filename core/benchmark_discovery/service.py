"""Comandi dell'utente sul benchmark: ricalcolo della scelta e aggiornamento dei prezzi delle serie scelte.

Entrambi partono solo da un click esplicito (ADR-0018), mai dal render. Una rete assente o un
fallimento non cancella nulla di quanto e' gia' salvato.
"""
from __future__ import annotations

import logging
from typing import Callable

from core.domain.instrument_status import active_fetch_tickers

from .decide import CandidateSource
from .runner import run_for_instrument

logger = logging.getLogger("portafoglio.core.benchmark_discovery.service")


def _tickers(data: dict, target: str | None) -> list[str]:
    known = [str(s["ticker"]) for s in data.get("strumenti", []) if isinstance(s, dict) and s.get("ticker")]
    if target is not None:
        if target not in known:
            raise ValueError("Strumento sconosciuto: " + target)
        return [target]
    active = active_fetch_tickers(data)
    return [tk for tk in known if tk in active]


def _decided_at(store, ticker: str) -> str:
    """Istante dell'ultima decisione salvata: serve a sapere se il ricalcolo ha davvero scritto."""
    a = store.assignment(ticker) or {}
    return str((a.get("discovery") or {}).get("decided_at") or "")


def _why(src, symbol: str) -> str:
    """Motivo dell'ultimo fallimento di rete per un simbolo, se la sorgente lo registra."""
    errors = getattr(src, "errors", None)
    return str(errors.get(symbol, "")) if isinstance(errors, dict) else ""


def _pull(store, src, code: str) -> bool:
    """Riscarica e salva la serie `code`. Il fallimento e' registrato (archivio e log) con il suo motivo."""
    series = src.history(code)
    if series:
        store.upsert(code, series, source="discovery", replace_existing=True)
        store.mark_fetch(code, "ok", "discovery")
        return True
    store.mark_fetch(code, "failed", "discovery")
    logger.warning("Aggiornamento prezzi benchmark: serie non scaricata (%s)", _why(src, code) or "motivo non registrato")
    return False


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
    logger.info("Ricalcolo benchmark: avvio su %d strumenti", len(tickers))
    for i, tk in enumerate(tickers, 1):
        if progress:
            progress(tk, i, len(tickers))
        before = _decided_at(store, tk)
        logger.info("Ricalcolo benchmark %d/%d: %s", i, len(tickers), tk)  # avanzamento: l'operazione dura decine di minuti
        try:
            d = run_for_instrument(data, tk, store=store, source=src)
        except Exception as exc:  # un fallimento non ferma gli altri strumenti
            logger.exception("Ricalcolo benchmark: errore su uno strumento (%d/%d)", i, len(tickers))
            items.append({"ticker": tk, "status": "ERRORE", "benchmark": "", "grade": "", "detail": f"{type(exc).__name__}: {exc}"[:200]})
            pending.append(tk)
            continue
        if d is None or d.status != "SCELTO":
            items.append({"ticker": tk, "status": "IN_ATTESA", "benchmark": "", "grade": "",
                          "detail": "nessun candidato disponibile: decisione precedente conservata"})
            pending.append(tk)
        elif _decided_at(store, tk) == before:
            # scelta fatta ma nulla scritto: la serie del benchmark non e' stata scaricata
            detail = _why(src, d.choice.symbol) or "serie del benchmark non scaricata"
            logger.warning("Ricalcolo benchmark: scelta non salvata (%d/%d): %s", i, len(tickers), detail)
            items.append({"ticker": tk, "status": "NON_SALVATO", "benchmark": d.choice.symbol, "grade": d.grade, "detail": detail})
            pending.append(tk)
        else:
            items.append({"ticker": tk, "status": "SCELTO", "benchmark": d.choice.symbol, "grade": d.grade,
                          "detail": d.choice.name})
    references = {}
    if target_instrument is None:  # il ricalcolo completo comprende i riferimenti del benchmark di portafoglio
        from .portfolio import discover_references
        try:
            references = discover_references(store, src)
        except Exception:
            logger.exception("Ricalcolo benchmark: errore nei riferimenti di portafoglio")
            references = {}
    logger.info("Ricalcolo benchmark: %d/%d strumenti salvati, in attesa=%d, riferimenti salvati=%d/%d",
                len(tickers) - len(pending), len(tickers), len(pending),
                sum(1 for v in references.values() if v), len(references))
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
    logger.info("Aggiornamento prezzi benchmark: avvio")
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
            got_any = _pull(store, src, code) or got_any
        if got_any and a and str(a.get("ticker", "")).startswith("BLEND:") and not override:
            _rebuild_blend(store, tk, a)
        updated += int(got_any)
        failed += int(not got_any)
        items.append({"ticker": tk, "status": "AGGIORNATO" if got_any else "FALLITO", "codes": codes,
                      "reason": "" if got_any else "; ".join(f"{c}: {_why(src, c)}" for c in codes if _why(src, c))})
    if target_instrument is None:  # l'aggiornamento completo comprende i riferimenti del benchmark di portafoglio
        from .portfolio import REFERENCE_PROFILES
        for family in REFERENCE_PROFILES:
            a = store.assignment("PORTFOLIO:" + family)
            code = str(a.get("ticker") or "") if a and a.get("discovery") else ""
            if not code:
                continue
            ok = _pull(store, src, code)
            updated += int(ok)
            failed += int(not ok)
            items.append({"ticker": "PORTFOLIO:" + family, "status": "AGGIORNATO" if ok else "FALLITO", "codes": [code],
                          "reason": "" if ok else _why(src, code)})
    logger.info("Aggiornamento prezzi benchmark: %d aggiornati, %d falliti su %d", updated, failed, len(items))
    return {"requested": len(items), "updated": updated, "failed": failed, "items": items}


def _rebuild_blend(store, ticker: str, assignment: dict) -> None:
    from .scoring import blend_series
    legs = [(store.read(c["series_id"]), c["weight_pct"]) for c in assignment.get("components", [])]
    series = blend_series(legs)
    if series:
        store.upsert(assignment["ticker"], series, source="discovery", replace_existing=True)
