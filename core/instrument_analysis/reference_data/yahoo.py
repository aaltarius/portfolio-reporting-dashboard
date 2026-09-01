"""Adapter Yahoo per il motore InstrumentAnalysis. Riusa core/market_data.py
(gia' esistente, con cache/timeout propri) invece di reimplementare le
chiamate HTTP a Yahoo — nessuna logica di rete duplicata."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import yfinance as yf

from core.instrument_analysis.contracts import ProvenanceItem
from core.market_data import find_ticker_candidates, get_yahoo_price_history_full


@dataclass(slots=True)
class YahooIdentity:
    ticker: str
    name: str
    quote_type: str
    exchange: str
    provenance: ProvenanceItem


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def resolve_yahoo_identity(ticker: str, isin: str) -> YahooIdentity | None:
    candidates = find_ticker_candidates(isin, ticker_hint=ticker)
    if not candidates:
        return None
    chosen = next((c for c in candidates if c.proposto), candidates[0])
    return YahooIdentity(
        ticker=chosen.ticker,
        name=chosen.nome,
        quote_type=chosen.quote_type,
        exchange=chosen.borsa,
        provenance=ProvenanceItem(
            source="yahoo", field="identity", value=chosen.ticker,
            confidence=0.9 if chosen.proposto else 0.6, fetched_at=_now_iso(),
        ),
    )


def lookup_index(query: str) -> list[tuple[str, str]]:
    q = str(query or "").strip()
    if not q or not hasattr(yf, "Lookup"):
        return []
    try:
        df = yf.Lookup(q, timeout=3, raise_errors=False).get_index(count=15)
    except Exception:
        return []
    if df is None or df.empty:
        return []
    out: list[tuple[str, str]] = []
    reset = df.reset_index()
    columns = {str(c).casefold(): c for c in reset.columns}
    symbol_col = columns.get("symbol")
    name_col = columns.get("name") or columns.get("longname") or columns.get("shortname")
    for _, row in reset.iterrows():
        symbol = str(row.get(symbol_col) if symbol_col is not None else row.iloc[0]).strip()
        name = str(row.get(name_col)).strip() if name_col is not None else symbol
        if symbol:
            out.append((symbol, name))
    return out


def fetch_history(ticker: str, period: str = "5y") -> dict[str, float]:
    return get_yahoo_price_history_full(ticker, period=period)
