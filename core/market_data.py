"""
core/market_data.py — Recupero prezzi da Yahoo Finance e Borsa Italiana.
Nessuna dipendenza da streamlit.
"""
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any

import requests
import yfinance as yf
from bs4 import BeautifulSoup

_LOOKUP_CACHE_RUNTIME: dict[str, dict[str, Any]] = {}
logger = logging.getLogger("portafoglio.core.market_data")


def _log_fallback_debug(step: str, identifier: str, exc: Exception) -> None:
    logger.debug("Fallback market data step=%s target=%s error=%s: %s", step, identifier, type(exc).__name__, exc)


def _to_price_date(value: Any) -> str | None:
    """Converte timestamp/data in ISO date YYYY-MM-DD, se possibile."""
    if value is None:
        return None
    try:
        if hasattr(value, "date"):
            return str(value.date())
        if isinstance(value, (int, float)):
            return str(datetime.fromtimestamp(float(value), tz=timezone.utc).date())
        txt = str(value)
        if len(txt) >= 10:
            return txt[:10]
    except Exception:
        return None
    return None


def get_yahoo_price_details(tk: str) -> tuple[float | None, str | None]:
    """Restituisce prezzo Yahoo e data effettiva del dato, quando disponibile."""
    try:
        h = yf.Ticker(tk).history(period="7d", auto_adjust=True, actions=False)
        if not h.empty and "Close" in h.columns:
            close = h["Close"].dropna()
            if not close.empty:
                return float(close.iloc[-1]), _to_price_date(close.index[-1])
    except Exception as exc:
        _log_fallback_debug("yahoo_history", tk, exc)

    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{tk}?interval=1d&range=7d"
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}, timeout=12)
        js = r.json()
        result = js["chart"]["result"][0]
        timestamps = result.get("timestamp") or []
        closes = result["indicators"]["quote"][0].get("close") or []
        valid = [(ts, c) for ts, c in zip(timestamps, closes) if c is not None]
        if valid:
            ts, c = valid[-1]
            return float(c), _to_price_date(ts)
    except Exception as exc:
        _log_fallback_debug("yahoo_chart_api", tk, exc)

    try:
        p = yf.Ticker(tk).fast_info.last_price
        if p is not None and float(p) > 0:
            return float(p), None
    except Exception as exc:
        _log_fallback_debug("yahoo_fast_info", tk, exc)

    return None, None


def get_yahoo_price(tk: str) -> float | None:
    """Compatibilità: restituisce solo il prezzo."""
    price, _price_date = get_yahoo_price_details(tk)
    return price

def get_yahoo_ticker(isin: str) -> str | None:
    try:
        r = requests.get(
            f"https://query2.finance.yahoo.com/v1/finance/search?q={isin}&quotesCount=5&newsCount=0",
            headers={"User-Agent": "Mozilla/5.0"}, timeout=10
        ).json()
        for q in r.get("quotes", []):
            if q.get("symbol", "").endswith(".MI"):
                return q["symbol"]
        for q in r.get("quotes", []):
            s = q.get("symbol", "")
            if not s.startswith("0P") and "." in s:
                return s
        if r.get("quotes"):
            return r["quotes"][0].get("symbol", "")
    except Exception as exc:
        _log_fallback_debug("yahoo_search_ticker", isin, exc)
    return None


def get_yahoo_name(isin: str) -> str:
    try:
        r = requests.get(
            f"https://query2.finance.yahoo.com/v1/finance/search?q={isin}&quotesCount=1&newsCount=0",
            headers={"User-Agent": "Mozilla/5.0"}, timeout=10
        ).json()
        q = r.get("quotes", [])
        if q:
            return q[0].get("longname") or q[0].get("shortname", "")
    except Exception as exc:
        _log_fallback_debug("yahoo_search_name", isin, exc)
    return ""


def get_borsa_italiana_etf_name(isin: str) -> str:
    try:
        r = requests.get(
            f"https://www.borsaitaliana.it/borsa/etf/scheda/{isin}-ETFP.html?lang=it",
            headers={"User-Agent": "Mozilla/5.0"}, timeout=10
        )
        t = BeautifulSoup(r.text, "html.parser").find("title")
        if t:
            n = t.text.strip()
            for sfx in [" - Borsa Italiana", " quotazioni", f" | {isin}"]:
                n = n.split(sfx)[0]
            if len(n) > 5 and "borsa italiana" not in n.lower() and "error" not in n.lower():
                return n
    except Exception as exc:
        _log_fallback_debug("borsa_italiana_etf_name", isin, exc)
    return ""


def get_btp_price(isin: str) -> float | None:
    urls = [
        f"https://www.borsaitaliana.it/borsa/obbligazioni/mot/btp/dati-completi.html?isin={isin}&lang=it",
        f"https://www.borsaitaliana.it/borsa/obbligazioni/mot/btp/scheda/{isin}-MOTX.html?lang=it",
    ]
    for url in urls:
        try:
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "it-IT"}, timeout=10)
            for term in ["Prezzo Ultimo Contratto", "Prezzo di Riferimento", "prezzo_rif"]:
                idx = resp.text.lower().find(term.lower())
                if idx >= 0:
                    for el in BeautifulSoup(resp.text[idx:idx + 500], "html.parser").find_all(string=True):
                        txt = el.strip().replace(".", "").replace(",", ".")
                        try:
                            v = float(txt)
                            if 30 < v < 200:
                                return v
                        except Exception:
                            continue
        except Exception as exc:
            _log_fallback_debug("borsa_italiana_btp_price", isin, exc)
            continue
    return None


def find_ticker(isin: str) -> str:
    if isin.startswith("IT"):
        return f"BTP-{isin[-4:]}"
    tk = get_yahoo_ticker(isin)
    if tk and not tk.startswith("0P"):
        return tk
    return f"F-{isin[4:8]}"


def find_name(isin: str) -> str:
    n = get_borsa_italiana_etf_name(isin)
    return n if n else (get_yahoo_name(isin) or "")


def deduce_type(isin: str, tk: str, name: str) -> str:
    n = name.lower()
    t = tk.upper()
    if isin.startswith("IT") and ("btp" in n or t.startswith("BTP")):
        return "Titolo di Stato"
    if "etf" in n or "ucits" in n:
        if "emerging" in n:
            return "ETF Az. Emergenti"
        if "world" in n or "global" in n:
            return "ETF Az. Globale"
        if "mib" in n or "italia" in n:
            return "ETF Az. Italia"
        if "overnight" in n or "swap" in n:
            return "ETF Monetario"
        if "energy" in n:
            return "ETF Energia"
        if "real estate" in n:
            return "ETF Real Estate"
        if "intel" in n or "big data" in n:
            return "ETF IA"
        if "commod" in n or "bloom" in n or "agri" in n:
            return "ETF Materie prime"
        return "ETF"
    if "debt" in n or "bond" in n:
        return "Fondo Obbligazionario"
    if "flexible" in n:
        return "Fondo Bilan. Flessibile"
    if "equity" in n or "passive" in n:
        return "Fondo Azionario"
    if name:
        return "Fondo"
    return ""


def _get_cached_price_record(key: str, timeout_seconds: int) -> dict[str, Any] | None:
    cached = _LOOKUP_CACHE_RUNTIME.get(key)
    if cached and (time.time() - cached.get("ts", 0) <= timeout_seconds):
        return cached
    return None


def _get_cached_price(key: str, timeout_seconds: int) -> tuple[float | None, str] | None:
    cached = _get_cached_price_record(key, timeout_seconds)
    if cached is not None:
        return cached.get("price"), cached.get("source", "Cache")
    return None


def _set_cached_price(key: str, price: float | None, source: str, price_date: str | None = None) -> None:
    _LOOKUP_CACHE_RUNTIME[key] = {
        "price": price,
        "source": source,
        "price_date": price_date,
        "ts": time.time(),
    }


def clear_runtime_price_cache() -> None:
    """Svuota la cache runtime dei lookup prezzo."""
    _LOOKUP_CACHE_RUNTIME.clear()
    logger.info("Cache runtime prezzi svuotata")


def get_price_details(isin: str, tk: str, timeout_seconds: int = 300) -> dict[str, Any]:
    """Recupera prezzo, fonte e data effettiva del prezzo quando disponibile."""
    key = f"{isin}|{tk}"
    cached = _get_cached_price_record(key, timeout_seconds)
    if cached is not None:
        logger.debug("Prezzo servito da cache runtime: key=%s source=%s", key, cached.get("source"))
        return {
            "price": cached.get("price"),
            "source": cached.get("source", "Cache"),
            "price_date": cached.get("price_date"),
        }

    if tk.upper().startswith("BTP"):
        p = get_btp_price(isin)
        if p:
            _set_cached_price(key, p, "Borsa Italiana", None)
            logger.info("Prezzo trovato da Borsa Italiana: key=%s", key)
            return {"price": p, "source": "Borsa Italiana", "price_date": None}

    if "." in tk and not tk.upper().startswith("0P"):
        p, p_date = get_yahoo_price_details(tk)
        if p:
            _set_cached_price(key, p, f"Yahoo [{tk}]", p_date)
            logger.info("Prezzo trovato da Yahoo ticker diretto: key=%s ticker=%s date=%s", key, tk, p_date)
            return {"price": p, "source": f"Yahoo [{tk}]", "price_date": p_date}

    auto = get_yahoo_ticker(isin)
    if auto and auto.upper() != tk.upper():
        p, p_date = get_yahoo_price_details(auto)
        if p:
            _set_cached_price(key, p, f"Yahoo [{auto}]", p_date)
            logger.info("Prezzo trovato da Yahoo ticker auto-detect: key=%s ticker=%s date=%s", key, auto, p_date)
            return {"price": p, "source": f"Yahoo [{auto}]", "price_date": p_date}

    p, p_date = get_yahoo_price_details(tk)
    if p:
        _set_cached_price(key, p, f"Yahoo [{tk}]", p_date)
        logger.info("Prezzo trovato da Yahoo fallback finale: key=%s ticker=%s date=%s", key, tk, p_date)
        return {"price": p, "source": f"Yahoo [{tk}]", "price_date": p_date}

    logger.warning("Prezzo non trovato: key=%s", key)
    return {"price": None, "source": "Non trovato", "price_date": None}


def get_price(isin: str, tk: str, timeout_seconds: int = 300) -> tuple[float | None, str]:
    """Compatibilità: restituisce solo prezzo e fonte."""
    info = get_price_details(isin, tk, timeout_seconds=timeout_seconds)
    return info.get("price"), info.get("source", "Non trovato")
