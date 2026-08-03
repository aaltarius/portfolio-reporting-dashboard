"""
core/market_data.py — Recupero prezzi da Yahoo Finance e Borsa Italiana.
Nessuna dipendenza da streamlit.
"""
import json
import logging
import math
import re
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests
import yfinance as yf
from bs4 import BeautifulSoup

from core.cache_orchestrator import get_registered_runtime_cache

_LOOKUP_CACHE_RUNTIME = get_registered_runtime_cache("market_data.lookup_cache", namespace="prices", max_entries=512)
_ISIN_YAHOO_TICKER_CACHE = get_registered_runtime_cache("market_data.lookup_cache", namespace="isin_ticker", max_entries=1024)
logger = logging.getLogger("portafoglio.core.market_data")

_BTP_TRADE_TIME_CACHE_FILE = Path(__file__).parent.parent / "data" / "cache" / "btp_last_trade_times.json"


def _cache_get(cache: Any, key: str, default: Any = None, *, max_age_seconds: int | float | None = None) -> Any:
    if hasattr(cache, "get"):
        try:
            if max_age_seconds is not None:
                return cache.get(key, default, max_age_seconds=max_age_seconds)
            return cache.get(key, default)
        except TypeError:
            return cache.get(key, default)
    return default


def _cache_set(cache: Any, key: str, value: Any) -> None:
    if hasattr(cache, "set"):
        cache.set(key, value)
    elif isinstance(cache, dict):
        cache[key] = value


def _cache_update(cache: Any, values: dict[str, Any]) -> None:
    if hasattr(cache, "update"):
        cache.update(values)
    elif isinstance(cache, dict):
        cache.update(values)


def _cache_as_dict(cache: Any) -> dict[str, Any]:
    if hasattr(cache, "as_dict"):
        return cache.as_dict()
    if isinstance(cache, dict):
        return dict(cache)
    return {}


def _coerce_positive_price(value: Any) -> float | None:
    try:
        price = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(price) or price <= 0:
        return None
    return price


def _load_btp_trade_time_cache() -> dict[str, Any]:
    try:
        if _BTP_TRADE_TIME_CACHE_FILE.exists():
            return json.loads(_BTP_TRADE_TIME_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        _log_fallback_debug("load_btp_trade_time_cache", str(_BTP_TRADE_TIME_CACHE_FILE), exc)
    return {}


def _save_btp_trade_time_cache(cache: dict[str, Any]) -> None:
    try:
        _BTP_TRADE_TIME_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _BTP_TRADE_TIME_CACHE_FILE.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:
        _log_fallback_debug("save_btp_trade_time_cache", str(_BTP_TRADE_TIME_CACHE_FILE), exc)


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


def _to_price_datetime(value: Any) -> str | None:
    """Converte timestamp UNIX in 'YYYY-MM-DD HH:MM' in ora locale (es. 2026-06-22 17:35)."""
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(float(value)).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return None
    return None


def get_yahoo_price_details(tk: str) -> tuple[float | None, str | None, dict[str, float]]:
    """Restituisce (prezzo, data_prezzo, storico_recente_7gg).

    Strategia "più recente vince": confronta meta.regularMarketPrice (data
    dell'ultimo scambio, affidabile per ETF/azioni) con l'ultimo close
    confermato in history (affidabile per fondi OICVM dove regularMarketTime
    è sistematicamente T-1 rispetto all'ultimo NAV pubblicato).
    Il recente storico serve per il backfill dei giorni mancanti.
    """
    meta_price: float | None = None
    meta_date: str | None = None      # solo data, usata per confronto e chiavi storico
    meta_datetime: str | None = None  # data+ora in ora locale, usata come price_date di ritorno
    hist_price: float | None = None
    hist_date: str | None = None
    recent_history: dict[str, float] = {}

    # 1. chart API v8 range=7d: un solo call per meta + storico recente
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{tk}?interval=1d&range=7d"
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}, timeout=12)
        js = r.json()
        result = js["chart"]["result"][0]
        meta = result.get("meta", {})
        rmp = meta.get("regularMarketPrice")
        rmt = meta.get("regularMarketTime")
        parsed_meta_price = _coerce_positive_price(rmp)
        if parsed_meta_price is not None and rmt:
            meta_price = parsed_meta_price
            meta_date = _to_price_date(rmt)
            meta_datetime = _to_price_datetime(rmt)
        timestamps = result.get("timestamp") or []
        closes = result["indicators"]["quote"][0].get("close") or []
        for ts_val, c in zip(timestamps, closes):
            parsed_close = _coerce_positive_price(c)
            if parsed_close is not None:
                d = _to_price_date(ts_val)
                if d:
                    recent_history[d] = parsed_close
        if recent_history:
            hist_date = max(recent_history.keys())
            hist_price = recent_history[hist_date]
    except Exception as exc:
        _log_fallback_debug("yahoo_chart_api_v8", tk, exc)

    # 2. Fallback con yf.history solo se il chart API ha fallito del tutto
    if not meta_price and not recent_history:
        try:
            h = yf.Ticker(tk).history(period="7d", auto_adjust=True, actions=False)
            if not h.empty and "Close" in h.columns:
                for idx in h.index:
                    c = h.loc[idx, "Close"]
                    d = _to_price_date(idx)
                    parsed_close = _coerce_positive_price(c)
                    if d and parsed_close is not None:
                        recent_history[d] = parsed_close
                if recent_history:
                    hist_date = max(recent_history.keys())
                    hist_price = recent_history[hist_date]
        except Exception as exc:
            _log_fallback_debug("yahoo_history_fallback", tk, exc)

    # 3. Prendi il più recente tra meta e history
    # Confronto su date pure; ritorno usa sempre data+ora (meta_datetime ha l'ora,
    # quando vince history la combiniamo con hist_date per mantenere l'ora del NAV)
    meta_time_suffix = meta_datetime[10:] if meta_datetime and len(meta_datetime) > 10 else ""

    if meta_date and hist_date:
        if meta_date >= hist_date:
            if meta_date not in recent_history and meta_price:
                recent_history[meta_date] = meta_price
            return meta_price, meta_datetime or meta_date, recent_history
        else:
            # hist più recente: combina hist_date con l'ora di meta (es. fondi OICVM)
            hist_datetime = hist_date + meta_time_suffix if meta_time_suffix else hist_date
            return hist_price, hist_datetime, recent_history
    if meta_date:
        if meta_date not in recent_history and meta_price:
            recent_history[meta_date] = meta_price
        return meta_price, meta_datetime or meta_date, recent_history
    if hist_date:
        hist_datetime = hist_date + meta_time_suffix if meta_time_suffix else hist_date
        return hist_price, hist_datetime, recent_history

    # 4. Ultimo fallback: fast_info (nessuna data, nessuno storico)
    try:
        p = yf.Ticker(tk).fast_info.last_price
        parsed_price = _coerce_positive_price(p)
        if parsed_price is not None:
            return parsed_price, None, recent_history
    except Exception as exc:
        _log_fallback_debug("yahoo_fast_info", tk, exc)

    return None, None, recent_history


def get_yahoo_live_quote(tk: str) -> dict[str, Any]:
    """Restituisce una quotazione Yahoo il piu' possibile corrente.

    La pagina Mercati usa questo dato per il movimento giornaliero: lo storico
    daily resta invece separato e serve per trend 5g/1m/YTD e grafici.
    """
    symbol = str(tk or "").strip()
    if not symbol:
        return {}
    try:
        encoded_ticker = quote(symbol, safe="")
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded_ticker}?interval=1m&range=1d"
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}, timeout=12)
        r.raise_for_status()
        result = (r.json().get("chart", {}).get("result") or [None])[0]
        if not isinstance(result, dict):
            return {}

        meta = result.get("meta") or {}
        quote_block = ((result.get("indicators") or {}).get("quote") or [{}])[0]
        closes = quote_block.get("close") or []
        timestamps = result.get("timestamp") or []

        price = _coerce_positive_price(meta.get("regularMarketPrice"))
        price_ts = meta.get("regularMarketTime")
        if price is None:
            for ts, close in reversed(list(zip(timestamps, closes))):
                parsed = _coerce_positive_price(close)
                if parsed is not None:
                    price = parsed
                    price_ts = ts
                    break

        previous_close = _coerce_positive_price(meta.get("previousClose"))
        if previous_close is None:
            previous_close = _coerce_positive_price(meta.get("chartPreviousClose"))

        pct = None
        points = None
        if price is not None and previous_close is not None and abs(previous_close) > 1e-12:
            pct = (price / previous_close) - 1.0
            points = price - previous_close

        return {
            "ticker": symbol,
            "price": price,
            "previous_close": previous_close,
            "pct": pct,
            "points": points,
            "price_date": _to_price_date(price_ts),
            "regular_market_time": int(price_ts) if isinstance(price_ts, (int, float)) else None,
            "exchange_timezone": str(meta.get("exchangeTimezoneName") or ""),
            "currency": str(meta.get("currency") or ""),
            "source": "yahoo_chart_live",
        }
    except Exception:
        return {}


def _get_yahoo_chart_history(tk: str, period: str = "max") -> dict[str, float]:
    """Recupera uno storico giornaliero dalla Chart API Yahoo.

    E' piu' affidabile di yf.Ticker(...).history() per molti indici Yahoo con
    simboli speciali, ad esempio ^GDAXI e ^FTSE.
    """
    history: dict[str, float] = {}
    try:
        encoded_ticker = quote(str(tk or "").strip(), safe="")
        encoded_period = quote(str(period or "max").strip(), safe="")
        if not encoded_ticker:
            return history
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded_ticker}?interval=1d&range={encoded_period}"
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}, timeout=12)
        if hasattr(r, "raise_for_status"):
            r.raise_for_status()
        js = r.json()
        result = (js.get("chart", {}).get("result") or [None])[0]
        if not isinstance(result, dict):
            return history
        timestamps = result.get("timestamp") or []
        closes = ((result.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
        for ts_val, close in zip(timestamps, closes):
            date_key = _to_price_date(ts_val)
            price = _coerce_positive_price(close)
            if date_key and price is not None:
                history[date_key] = price
    except Exception as exc:
        _log_fallback_debug("yahoo_chart_history", tk, exc)
    return history


def get_yahoo_price_history_full(tk: str, period: str = "max") -> dict[str, float]:
    """Scarica lo storico prezzi completo (o per il periodo indicato) per un ticker.

    A differenza di get_yahoo_price_details (limitato a 7 giorni, pensato per il
    refresh quotidiano), questa funzione recupera fino a tutto lo storico
    disponibile su Yahoo. Serve al recupero manuale one-shot per uno strumento
    con storico troppo corto per un giudizio SATOR affidabile.
    """
    history = _get_yahoo_chart_history(tk, period=period)
    if history:
        return history

    history: dict[str, float] = {}
    try:
        h = yf.Ticker(tk).history(period=period, auto_adjust=True, actions=False)
        if not h.empty and "Close" in h.columns:
            for idx in h.index:
                c = h.loc[idx, "Close"]
                d = _to_price_date(idx)
                parsed_close = _coerce_positive_price(c)
                if d and parsed_close is not None:
                    history[d] = parsed_close
    except Exception as exc:
        _log_fallback_debug("yahoo_history_full", tk, exc)
    return history


def backfill_storico_prezzi(
    storico: dict[str, dict[str, float]],
    ticker: str,
    history: dict[str, float],
    since: str | None = None,
) -> int:
    """Aggiunge allo storico solo le date mancanti per il ticker indicato.

    Non sovrascrive mai un prezzo gia' presente: lo storico costruito giorno per
    giorno dall'app resta la fonte di verita', il backfill riempie solo i vuoti
    (tipicamente le date piu' vecchie della prima gia' salvata). Se since e'
    indicato (YYYY-MM-DD), ignora le date precedenti: l'utente decide da quando
    vuole storico, invece di importare automaticamente tutto cio' che Yahoo
    restituisce. Ritorna il numero di date aggiunte.
    """
    added = 0
    for date_str, price in history.items():
        if since and date_str < since:
            continue
        parsed_price = _coerce_positive_price(price)
        if parsed_price is None:
            continue
        day = storico.setdefault(date_str, {})
        if ticker not in day:
            day[ticker] = parsed_price
            added += 1
    return added


def earliest_storico_date(storico: dict[str, dict[str, float]]) -> str | None:
    """Prima data (YYYY-MM-DD) gia' presente nello storico, per qualunque strumento.

    Usata come proposta di default per il campo "data di partenza" del recupero
    manuale: il sistema suggerisce di allineare il nuovo strumento alla stessa
    profondita' storica degli altri, invece di scaricare tutto cio' che Yahoo ha.
    """
    dates = [d for d in storico.keys() if d]
    return min(dates) if dates else None


def delete_storico_prezzi_range(
    storico: dict[str, dict[str, float]],
    ticker: str,
    date_from: str | None = None,
    date_to: str | None = None,
) -> int:
    """Rimuove i prezzi salvati per un ticker in un intervallo di date (incluso).

    date_from/date_to assenti = nessun limite su quel lato (es. solo date_to
    per cancellare "tutto fino a"). Tocca solo il ticker indicato: le date
    restano con i prezzi degli altri strumenti intatti. Ritorna il numero di
    date rimosse.
    """
    removed = 0
    for date_str in list(storico.keys()):
        if date_from and date_str < date_from:
            continue
        if date_to and date_str > date_to:
            continue
        day = storico.get(date_str)
        if isinstance(day, dict) and ticker in day:
            del day[ticker]
            removed += 1
            if not day:
                del storico[date_str]
    return removed


def get_yahoo_ticker(isin: str) -> str | None:
    cached_ticker = _cache_get(_ISIN_YAHOO_TICKER_CACHE, isin)
    if cached_ticker:
        logger.debug("Ticker Yahoo da cache persistente: isin=%s ticker=%s", isin, cached_ticker)
        return cached_ticker
    try:
        r = requests.get(
            f"https://query2.finance.yahoo.com/v1/finance/search?q={isin}&quotesCount=5&newsCount=0",
            headers={"User-Agent": "Mozilla/5.0"}, timeout=10
        ).json()
        result = None
        for q in r.get("quotes", []):
            if q.get("symbol", "").endswith(".MI"):
                result = q["symbol"]
                break
        if not result:
            for q in r.get("quotes", []):
                s = q.get("symbol", "")
                if not s.startswith("0P") and "." in s:
                    result = s
                    break
        if not result and r.get("quotes"):
            result = r["quotes"][0].get("symbol", "")
        if result:
            _cache_set(_ISIN_YAHOO_TICKER_CACHE, isin, result)
            logger.info("Ticker Yahoo risolto e messo in cache: isin=%s ticker=%s", isin, result)
        return result
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


_MESI_IT = {"gennaio":"01","febbraio":"02","marzo":"03","aprile":"04","maggio":"05",
            "giugno":"06","luglio":"07","agosto":"08","settembre":"09","ottobre":"10",
            "novembre":"11","dicembre":"12"}


def get_btp_price_details(isin: str) -> dict[str, Any]:
    """Recupera prezzo e data+ora ultimo contratto BTP.

    Catena fonti:
    1. Borsa Italiana dati-completi → prezzo + data/ora da 'Ultimo Contratto'
    2. Borsa Italiana scheda        → stessa logica
    3. Il Sole 24 Ore widget        → prezzo + data/ora (solo se mercato aperto)
    Pre-apertura: data da 'Data Pr Ufficiale' + orario dalla cache locale.
    """
    _headers_bi = {"User-Agent": "Mozilla/5.0", "Accept-Language": "it-IT"}
    price: float | None = None
    price_datetime: str | None = None

    # --- 1+2. Borsa Italiana ---
    for url in [
        f"https://www.borsaitaliana.it/borsa/obbligazioni/mot/btp/dati-completi.html?isin={isin}&lang=it",
        f"https://www.borsaitaliana.it/borsa/obbligazioni/mot/btp/scheda/{isin}-MOTX.html?lang=it",
    ]:
        try:
            resp = requests.get(url, headers=_headers_bi, timeout=10)
            txt_bi = resp.text

            # Data+ora da "Ultimo Contratto"
            if not price_datetime:
                try:
                    idx_uc = txt_bi.lower().find("ultimo contratto")
                    if idx_uc >= 0:
                        strong = BeautifulSoup(txt_bi[idx_uc:idx_uc + 300], "html.parser").find("strong")
                        if strong:
                            raw = strong.get_text(separator=" ", strip=True).replace("\xa0", " ").strip()
                            parts = raw.split()
                            if len(parts) >= 2:
                                dd, mm, yy = parts[0].split("/")
                                year = f"20{yy}" if len(yy) == 2 else yy
                                hh, mn = parts[1].split(".")[:2]
                                price_datetime = f"{year}-{mm}-{dd} {hh.zfill(2)}:{mn}"
                except Exception:
                    pass

            # Fallback data-only da "Data Pr Ufficiale" (pre-apertura)
            if not price_datetime:
                try:
                    idx_dpu = txt_bi.lower().find("data pr ufficiale")
                    if idx_dpu >= 0:
                        snippet = BeautifulSoup(txt_bi[idx_dpu:idx_dpu + 200], "html.parser").get_text(" ", strip=True)
                        m = re.search(r'(\d{2})/(\d{2})/(\d{2,4})', snippet)
                        if m:
                            dd2, mm2, yy2 = m.group(1), m.group(2), m.group(3)
                            year2 = f"20{yy2}" if len(yy2) == 2 else yy2
                            price_datetime = f"{year2}-{mm2}-{dd2}"  # solo data
                except Exception:
                    pass

            # Prezzo
            if price is None:
                for term in ["Prezzo Ultimo Contratto", "Prezzo di Riferimento", "prezzo_rif"]:
                    idx_p = txt_bi.lower().find(term.lower())
                    if idx_p >= 0:
                        for el in BeautifulSoup(txt_bi[idx_p:idx_p + 500], "html.parser").find_all(string=True):
                            t = el.strip().replace(".", "").replace(",", ".")
                            try:
                                v = float(t)
                                if 30 < v < 200:
                                    price = v
                                    break
                            except Exception:
                                continue
                    if price is not None:
                        break

            if price is not None and price_datetime and len(price_datetime) >= 16:
                break  # prezzo + orario completo: non serve altro
        except Exception as exc:
            _log_fallback_debug("borsa_italiana_btp_price", isin, exc)

    # --- 3. Il Sole 24 Ore (fallback solo per prezzo) ---
    # Nota: il widget S24 mostra l'ora corrente (con 20-min delay), NON l'orario dell'ultimo contratto.
    # È utile solo come fallback per il PREZZO quando Borsa Italiana non risponde.
    if price is None:
        try:
            s24_url = f"https://mercatiwdg.ilsole24ore.com/FinanzaMercati/WidgetSelector/header-dettaglio?topicName={isin}.MOT"
            r24 = requests.get(s24_url, headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://mercati.ilsole24ore.com/",
            }, timeout=10)
            soup24 = BeautifulSoup(r24.text, "html.parser")
            huge = soup24.find("span", class_=lambda c: c and "fmw-value--huge" in c)
            if huge:
                t = huge.get_text(strip=True).replace(".", "").replace(",", ".")
                try:
                    v = float(t)
                    if 30 < v < 200:
                        price = v
                        logger.info("BTP Il Sole 24 Ore fallback: isin=%s price=%s", isin, price)
                except Exception:
                    pass
        except Exception as exc:
            _log_fallback_debug("sole24ore_btp", isin, exc)

    if price is not None:
        btp_cache = _load_btp_trade_time_cache()
        if price_datetime and len(price_datetime) >= 16:
            # Orario confermato (da "Ultimo Contratto"): salva in cache
            btp_cache[isin] = {"price_date": price_datetime}
            _save_btp_trade_time_cache(btp_cache)
        elif price_datetime and len(price_datetime) == 10:
            # Solo data (pre-apertura): recupera orario dal cache se la data coincide
            cached = btp_cache.get(isin, {})
            if str(cached.get("price_date", ""))[:10] == price_datetime:
                price_datetime = cached["price_date"]
                logger.info("BTP pre-apertura: orario da cache per %s → %s", isin, price_datetime)
        logger.info("BTP: isin=%s price=%s datetime=%s", isin, price, price_datetime)
        return {"price": price, "price_date": price_datetime}
    return {"price": None, "price_date": None}


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


def _classify_focus_etf(focus: str) -> str:
    """Sotto-categoria ETF dal campo 'focus_etf' di justETF (testo gia' in
    minuscolo). L'ordine conta: 'monetario' va controllato prima di 'globale'
    perche' un fondo monetario globale (es. 'Mercato monetario, EUR, Globale')
    contiene entrambe le parole; allo stesso modo 'informatica' va controllato
    prima di 'globale' (es. 'Azioni, Globale, Informatica' e' un ETF tecnologico,
    non generico globale)."""
    if "monetario" in focus:
        return "ETF Monetario"
    if "materie prime" in focus or "metalli preziosi" in focus:
        return "ETF Materie prime"
    if "emergenti" in focus:
        return "ETF Az. Emergenti"
    if "italia" in focus:
        return "ETF Az. Italia"
    if "informatica" in focus or "tecnolog" in focus:
        return "ETF IA"
    if "energia" in focus:
        return "ETF Energia"
    if "immobiliare" in focus:
        return "ETF Real Estate"
    if "globale" in focus or "global" in focus:
        return "ETF Az. Globale"
    return "ETF"


def deduce_type(isin: str, tk: str, name: str, focus_etf: str = "") -> str:
    n = name.lower()
    t = tk.upper()
    if isin.startswith("IT") and ("btp" in n or t.startswith("BTP")):
        return "Titolo di Stato"
    if focus_etf:
        return _classify_focus_etf(focus_etf.lower())
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
    cached = _cache_get(_LOOKUP_CACHE_RUNTIME, key, max_age_seconds=timeout_seconds)
    if cached:
        return cached
    return None


def _set_cached_price(key: str, price: float | None, source: str, price_date: str | None = None, recent_history: dict | None = None) -> None:
    _cache_set(_LOOKUP_CACHE_RUNTIME, key, {
        "price": price,
        "source": source,
        "price_date": price_date,
        "recent_history": recent_history or {},
        "ts": time.time(),
    })


def prime_isin_ticker_cache(cache_dict: dict) -> None:
    """Carica il mapping ISIN→ticker Yahoo dalla cache persistente (chiamare all'avvio)."""
    if isinstance(cache_dict, dict):
        _cache_update(_ISIN_YAHOO_TICKER_CACHE, {k: v for k, v in cache_dict.items() if isinstance(v, str) and v})
        logger.debug("Cache ISIN→ticker Yahoo inizializzata: %d voci", len(_ISIN_YAHOO_TICKER_CACHE))


def get_isin_ticker_cache() -> dict[str, str]:
    """Restituisce il mapping ISIN→ticker Yahoo corrente per la persistenza su disco."""
    return {str(k): str(v) for k, v in _cache_as_dict(_ISIN_YAHOO_TICKER_CACHE).items() if isinstance(v, str) and v}


@dataclass(frozen=True)
class TickerCandidate:
    ticker: str
    borsa: str
    nome: str
    quote_type: str
    prezzo: float | None
    fonte: str
    proposto: bool


def find_ticker_candidates(isin: str, ticker_hint: str = "") -> list[TickerCandidate]:
    """Tutti i candidati Yahoo per l'ISIN (non solo il primo), ciascuno con
    prezzo gia' risolto. Per ISIN italiani (BTP) restituisce un solo
    candidato deterministico. Un fallimento nel recupero prezzo di un
    singolo candidato non blocca gli altri.

    Se il chiamante conosce gia' un ticker (ticker_hint), viene verificato
    (prezzo reale) e proposto al posto dell'euristica automatica: un utente
    che digita un ticker che conosce e' piu' affidabile di un'euristica.

    La ricerca ISIN di Yahoo spesso non include la quotazione di Borsa
    Italiana (.MI) anche quando esiste ed e' quotabile direttamente: se
    nessun candidato trovato finisce per .MI, si tenta {base}.MI per ogni
    simbolo base distinto tra i candidati, aggiungendolo se risponde con un
    prezzo reale."""
    isin = isin.strip().upper()
    ticker_hint = ticker_hint.strip().upper()

    if isin.startswith("IT"):
        ticker = f"BTP-{isin[-4:]}"
        try:
            btp = get_btp_price_details(isin)
        except Exception as exc:
            _log_fallback_debug("btp_candidate_price", isin, exc)
            btp = {"price": None}
        price = btp.get("price")
        return [TickerCandidate(
            ticker=ticker, borsa="MOT", nome="", quote_type="BOND",
            prezzo=price, fonte="Borsa Italiana" if price is not None else "n/d",
            proposto=True,
        )]

    try:
        r = requests.get(
            f"https://query2.finance.yahoo.com/v1/finance/search?q={isin}&quotesCount=5&newsCount=0",
            headers={"User-Agent": "Mozilla/5.0"}, timeout=10
        ).json()
    except Exception as exc:
        _log_fallback_debug("yahoo_search_candidates", isin, exc)
        return []

    quotes = [q for q in (r.get("quotes") or []) if not str(q.get("symbol", "")).startswith("0P")]
    if not quotes:
        return []

    proposed_symbol = None
    for q in quotes:
        if str(q.get("symbol", "")).endswith(".MI"):
            proposed_symbol = q["symbol"]
            break
    if proposed_symbol is None:
        for q in quotes:
            s = str(q.get("symbol", ""))
            if "." in s:
                proposed_symbol = s
                break
    if proposed_symbol is None:
        proposed_symbol = quotes[0].get("symbol", "")

    candidates: list[TickerCandidate] = []
    for q in quotes:
        symbol = str(q.get("symbol", ""))
        if not symbol:
            continue
        try:
            price, _price_date, _recent = get_yahoo_price_details(symbol)
        except Exception as exc:
            _log_fallback_debug("yahoo_candidate_price", symbol, exc)
            price = None
        candidates.append(TickerCandidate(
            ticker=symbol,
            borsa=str(q.get("exchange", "")) or (symbol.split(".")[-1] if "." in symbol else ""),
            nome=q.get("longname") or q.get("shortname") or "",
            quote_type=str(q.get("quoteType", "")),
            prezzo=price,
            fonte=f"Yahoo [{symbol}]" if price is not None else "n/d",
            proposto=(symbol == proposed_symbol),
        ))

    if ticker_hint:
        existing = next((c for c in candidates if c.ticker.upper() == ticker_hint), None)
        if existing is not None:
            candidates = [replace(c, proposto=(c.ticker.upper() == ticker_hint)) for c in candidates]
        else:
            try:
                hint_price, _hint_date, _hint_recent = get_yahoo_price_details(ticker_hint)
            except Exception as exc:
                _log_fallback_debug("yahoo_ticker_hint_probe", ticker_hint, exc)
                hint_price = None
            if hint_price is not None:
                candidates = [replace(c, proposto=False) for c in candidates]
                candidates.append(TickerCandidate(
                    ticker=ticker_hint,
                    borsa=ticker_hint.split(".")[-1] if "." in ticker_hint else "",
                    nome=find_name(isin) or "", quote_type="",
                    prezzo=hint_price, fonte=f"Yahoo [{ticker_hint}]", proposto=True,
                ))

    if candidates and not any(c.ticker.upper().endswith(".MI") for c in candidates):
        seen_bases: list[str] = []
        for c in candidates:
            base = c.ticker.split(".")[0]
            if base not in seen_bases:
                seen_bases.append(base)
        for base in seen_bases:
            mi_ticker = f"{base}.MI"
            try:
                mi_price, _mi_date, _mi_recent = get_yahoo_price_details(mi_ticker)
            except Exception as exc:
                _log_fallback_debug("yahoo_mi_probe", mi_ticker, exc)
                mi_price = None
            if mi_price is not None:
                candidates = [replace(c, proposto=False) for c in candidates]
                candidates.append(TickerCandidate(
                    ticker=mi_ticker, borsa="MIL", nome=find_name(isin) or "", quote_type="",
                    prezzo=mi_price, fonte=f"Yahoo [{mi_ticker}]", proposto=True,
                ))
                break

    return candidates


def set_isin_ticker(isin: str, ticker: str) -> None:
    """Registra il ticker scelto/confermato per un ISIN (es. dopo conferma
    utente in fase di aggiunta strumento), cosi' un futuro refresh prezzi
    dello stesso ISIN usa direttamente questo ticker."""
    if isin and ticker:
        _cache_set(_ISIN_YAHOO_TICKER_CACHE, isin, ticker)


def get_price_details(isin: str, tk: str, timeout_seconds: int = 300) -> dict[str, Any]:
    """Recupera prezzo, fonte, data effettiva e storico recente (per backfill)."""
    key = f"{isin}|{tk}"
    isin_upper = str(isin or "").strip().upper()
    ticker_upper = str(tk or "").strip().upper()
    cached = _get_cached_price_record(key, timeout_seconds)
    if cached is not None:
        logger.debug("Prezzo servito da cache runtime: key=%s source=%s", key, cached.get("source"))
        return {
            "price": cached.get("price"),
            "source": cached.get("source", "Cache"),
            "price_date": cached.get("price_date"),
            "recent_history": cached.get("recent_history") or {},
        }

    if ticker_upper.startswith("BTP") or isin_upper.startswith("IT"):
        btp = get_btp_price_details(isin)
        p, p_date = btp.get("price"), btp.get("price_date")
        if p:
            _set_cached_price(key, p, "Borsa Italiana", p_date)
            logger.info("Prezzo trovato da Borsa Italiana: key=%s datetime=%s", key, p_date)
            return {"price": p, "source": "Borsa Italiana", "price_date": p_date, "recent_history": {}}
        logger.warning("Prezzo BTP non trovato su Borsa Italiana: key=%s", key)
        return {"price": None, "source": "Borsa Italiana non disponibile", "price_date": p_date, "recent_history": {}}

    persisted_tk = _cache_get(_ISIN_YAHOO_TICKER_CACHE, isin)
    if persisted_tk and persisted_tk.upper() != ticker_upper:
        p, p_date, rec_hist = get_yahoo_price_details(persisted_tk)
        if p:
            _set_cached_price(key, p, f"Yahoo [{persisted_tk}]", p_date, rec_hist)
            logger.info("Prezzo da ticker persistente: key=%s ticker=%s date=%s", key, persisted_tk, p_date)
            return {"price": p, "source": f"Yahoo [{persisted_tk}]", "price_date": p_date, "recent_history": rec_hist}

    if "." in tk and not ticker_upper.startswith("0P"):
        p, p_date, rec_hist = get_yahoo_price_details(tk)
        if p:
            _set_cached_price(key, p, f"Yahoo [{tk}]", p_date, rec_hist)
            logger.info("Prezzo trovato da Yahoo ticker diretto: key=%s ticker=%s date=%s", key, tk, p_date)
            return {"price": p, "source": f"Yahoo [{tk}]", "price_date": p_date, "recent_history": rec_hist}

    auto = get_yahoo_ticker(isin)
    if auto and auto.upper() != ticker_upper:
        p, p_date, rec_hist = get_yahoo_price_details(auto)
        if p:
            _set_cached_price(key, p, f"Yahoo [{auto}]", p_date, rec_hist)
            logger.info("Prezzo trovato da Yahoo ticker auto-detect: key=%s ticker=%s date=%s", key, auto, p_date)
            return {"price": p, "source": f"Yahoo [{auto}]", "price_date": p_date, "recent_history": rec_hist}

    p, p_date, rec_hist = get_yahoo_price_details(tk)
    if p:
        _set_cached_price(key, p, f"Yahoo [{tk}]", p_date, rec_hist)
        logger.info("Prezzo trovato da Yahoo fallback finale: key=%s ticker=%s date=%s", key, tk, p_date)
        return {"price": p, "source": f"Yahoo [{tk}]", "price_date": p_date, "recent_history": rec_hist}

    logger.warning("Prezzo non trovato: key=%s", key)
    return {"price": None, "source": "Non trovato", "price_date": None, "recent_history": {}}


def get_price(isin: str, tk: str, timeout_seconds: int = 300) -> tuple[float | None, str]:
    """Compatibilità: restituisce solo prezzo e fonte."""
    info = get_price_details(isin, tk, timeout_seconds=timeout_seconds)
    return info.get("price"), info.get("source", "Non trovato")
