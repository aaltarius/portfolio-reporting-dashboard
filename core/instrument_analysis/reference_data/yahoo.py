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
    if candidates:
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
    return resolve_mutual_fund_identity(isin)


def resolve_mutual_fund_identity(isin: str) -> YahooIdentity | None:
    """Fallback dedicato per fondi comuni/SICAV senza ticker di borsa (es.
    fondi Fineco AM proprietari: FAM-EMD/FLEX/PU6/PU8). `find_ticker_candidates`
    (core/market_data.py, uso condiviso con la ricerca ticker per aggiungere
    strumenti) scarta deliberatamente i simboli Yahoo "0P..." — qui invece li
    vogliamo: sono fondi comuni reali con NAV storico e composizione (vedi
    `fetch_fund_asset_mix`). Verificato in diretta (2026-09-03): l'ISIN passato
    come simbolo a `yf.Ticker` risolve i 4 fondi FAM a un ticker "0P..." con
    storico e `funds_data` reali."""
    isin = str(isin or "").strip().upper()
    if not isin:
        return None
    try:
        info = yf.Ticker(isin).info
    except Exception:
        return None
    if str(info.get("quoteType") or "").upper() != "MUTUALFUND":
        return None
    symbol = str(info.get("symbol") or "").strip()
    if not symbol:
        return None
    name = str(info.get("longName") or info.get("shortName") or "").strip()
    return YahooIdentity(
        ticker=symbol, name=name, quote_type="MUTUALFUND", exchange="",
        provenance=ProvenanceItem(
            source="yahoo_mutualfund", field="identity", value=symbol,
            confidence=0.7, fetched_at=_now_iso(),
        ),
    )


def fetch_fund_asset_mix(ticker: str) -> dict[str, float] | None:
    """Composizione reale (equity/bond/cash/altro, in percentuale 0-100) di un
    fondo comune via `yfinance` `funds_data.asset_classes` — non un'euristica
    testuale. Ritorna None se il ticker non e' un fondo o il dato non e'
    disponibile (mai un dizionario vuoto/fittizio)."""
    ticker = str(ticker or "").strip()
    if not ticker:
        return None
    try:
        raw = yf.Ticker(ticker).funds_data.asset_classes
    except Exception:
        return None
    if not raw:
        return None
    try:
        equity = 100.0 * float(
            (raw.get("stockPosition") or 0.0)
            + (raw.get("preferredPosition") or 0.0)
            + (raw.get("convertiblePosition") or 0.0)
        )
        bond = 100.0 * float(raw.get("bondPosition") or 0.0)
        cash = 100.0 * float(raw.get("cashPosition") or 0.0)
        other = 100.0 * float(raw.get("otherPosition") or 0.0)
    except (TypeError, ValueError):
        return None
    return {"equity": equity, "bond": bond, "cash": cash, "other": other}


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
