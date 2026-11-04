"""Adattatore Yahoo Finance per la scoperta dei candidati (CandidateSource).

Sottile e sostituibile: unisce `Search` e `Lookup(...).get_etf()` (solo ETF e
indici), scarica lo storico settimanale rettificato degli ultimi 5 anni e legge
l'ISIN. Ogni errore di rete diventa un risultato vuoto: la decisione resta
'in attesa', mai un'eccezione. Verso la rete esce solo testo descrittivo e simboli.
"""
from __future__ import annotations

import time

from .decide import ALLOWED_TYPES, Candidate


class YahooSource:
    def __init__(self, yf_module=None, pause: float = 0.4):
        if yf_module is None:
            import yfinance as yf_module  # import tardivo: nessuna rete all'importazione
        self._yf = yf_module
        self._pause = pause
        self._history_cache: dict[str, dict[str, float]] = {}
        self._isin_cache: dict[str, str] = {}
        self._name_cache: dict[str, str] = {}

    def _wait(self) -> None:
        if self._pause:
            time.sleep(self._pause)

    def search(self, text: str) -> list[Candidate]:
        found: dict[str, Candidate] = {}
        try:
            for q in self._yf.Search(text, max_results=10, news_count=0, enable_fuzzy_query=False).quotes or []:
                qt = str(q.get("quoteType") or "").upper()
                sym = str(q.get("symbol") or "").strip()
                if sym and qt in ALLOWED_TYPES and sym not in found:
                    found[sym] = Candidate(sym, str(q.get("shortname") or q.get("longname") or ""), qt)
        except Exception:
            pass
        self._wait()
        try:
            df = self._yf.Lookup(text).get_etf(count=25)
            for sym in list(getattr(df, "index", [])):
                sym = str(sym).strip()
                if sym and sym not in found:
                    found[sym] = Candidate(sym, str(df.loc[sym, "shortName"]), "ETF")
        except Exception:
            pass
        self._wait()
        return list(found.values())

    def history(self, symbol: str) -> dict[str, float]:
        if symbol in self._history_cache:
            return self._history_cache[symbol]
        out = self._fetch_history(symbol)
        if not out:  # risposta vuota: spesso e' un limite di richieste, si riprova una volta
            if self._pause:
                time.sleep(1.5)
            out = self._fetch_history(symbol)
        self._history_cache[symbol] = out
        self._wait()
        return out

    def _fetch_history(self, symbol: str) -> dict[str, float]:
        out: dict[str, float] = {}
        try:
            df = self._yf.Ticker(symbol).history(period="5y", interval="1wk", auto_adjust=True)
            for ts, val in df["Close"].dropna().items():
                out[ts.strftime("%Y-%m-%d")] = float(val)
        except Exception:
            out = {}
        return out

    def isin(self, symbol: str) -> str:
        if symbol in self._isin_cache:
            return self._isin_cache[symbol]
        try:
            val = str(self._yf.Ticker(symbol).isin or "").strip()
        except Exception:
            val = ""
        val = "" if val in ("-", "None") else val
        self._isin_cache[symbol] = val
        self._wait()
        return val

    def long_name(self, symbol: str) -> str:
        """Nome completo del prodotto (i nomi brevi dei fornitori tagliano copertura, classe e tipo)."""
        if symbol in self._name_cache:
            return self._name_cache[symbol]
        name = ""
        try:
            for q in self._yf.Search(symbol, max_results=5, news_count=0, enable_fuzzy_query=False).quotes or []:
                if str(q.get("symbol") or "") == symbol:
                    name = str(q.get("longname") or q.get("shortname") or "")
                    break
        except Exception:
            name = ""
        self._name_cache[symbol] = name
        self._wait()
        return name
