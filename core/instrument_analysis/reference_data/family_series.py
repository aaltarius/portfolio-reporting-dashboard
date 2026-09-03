"""Fetch cache-first delle serie storiche del catalogo `REFERENCE_FAMILIES`
per il ladder intermedio (gap 1, Task L4) e per la scelta del miglior
candidato per geometria (Task O). Rete reale via `core/market_data.py`
(stesso adapter gia' usato da `reference_data/yahoo.py` per l'identita'),
cache giornaliera via `cache.py` (Task L3)."""
from __future__ import annotations

from core.instrument_analysis import cache as ia_cache
from core.instrument_analysis.reference_families import REFERENCE_FAMILIES
from core.market_data import get_yahoo_price_history_full

#: TTL giornaliero per gli storici (spec sezione 9: "Cache storici/curve
#: operative... TTL giornaliero, separata dalla risoluzione").
SERIES_TTL_DAYS = 1.0
#: 252 osservazioni bastano a `geometry.py` (che tronca comunque a 252) —
#: nessun motivo di scaricare storici piu' lunghi per un indice di famiglia.
_FETCH_PERIOD = "1y"


def fetch_family_candidates(family: str) -> list[tuple[str, dict[str, float]]]:
    """Ritorna (ticker, storico) per OGNI ticker della famiglia con dati
    utilizzabili, cache-first — non si ferma al primo disponibile (Task O:
    scegliere il migliore per geometria richiede vederli tutti, es.
    XDBC.MI traccia `^BCOM` molto meglio di `^SPGSCI`, 82,0 contro 63,8,
    pur essendo entrambi candidati legittimi della stessa famiglia
    COMMODITY). Lista vuota se la famiglia non e' nel catalogo o nessun
    suo ticker produce dati (mai bloccante — regola non negoziabile 0)."""
    tickers = REFERENCE_FAMILIES.get(family, ())
    if not tickers:
        return []

    cache = ia_cache.load_series_cache()
    dirty = False
    results: list[tuple[str, dict[str, float]]] = []
    try:
        for ticker in tickers:
            cached = ia_cache.get_cached_series(cache, ticker, ttl_days=SERIES_TTL_DAYS)
            if cached:
                results.append((ticker, cached))
                continue
            history = get_yahoo_price_history_full(ticker, period=_FETCH_PERIOD)
            if history:
                ia_cache.put_cached_series(cache, ticker, history)
                dirty = True
                results.append((ticker, history))
        return results
    finally:
        if dirty:
            ia_cache.save_series_cache(cache)
