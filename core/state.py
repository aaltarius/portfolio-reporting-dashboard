"""
core/state.py — State Manager con cache granulare.
Gestisce dati portfolio in memoria con invalidazione intelligente.
"""
import logging
import os
import threading
import time
from typing import Any
import pandas as pd
from persistence.storage import (
    DATA_DIR,
    _portfolio_state_signature,
    load_data, load_settings, load_quotes_log, load_snapshots, load_meta,
    save_data, _data_mtime, _new_event_id
)
from core.finance import (
    compute_portfolio_state, build_portfolio_history_df, build_hist_df,
    append_evento_portafoglio
)
from core.market_data import get_price, prime_isin_ticker_cache
from core.price_frames import build_expanded_price_frame
from core.cache_signatures import history_span_by_ticker

logger = logging.getLogger("portafoglio.core.state")
_DERIVED_CACHE_DIR = os.path.join(DATA_DIR, "cache", "derived_runtime")


class StateManager:
    """
    Gestisce dati portfolio in memoria con cache granulare.
    Invalida solo ciò che è necessario quando i dati cambiano.
    """

    def __init__(self):
        """Inizializza state manager e carica dati."""
        # Dati primari
        self._data = None
        self._settings = None
        self._quotes_log = None
        self._snapshots_state = None
        self._meta_state = None

        # Cache computed (invalidabili)
        self._cache = {
            "portfolio_state": None,
            "finance_results": None,
            "history_df": None,
            "hist_df": None,
            "analytics": None,
            "expanded_price_frame": None,
            "ultimi_eventi": None,
            "market_prices": None,
        }

        # Cache per strumento (ticker -> dati di posizione e eventi)
        self._instrument_cache = {}

        # Traccia mtime per invalidazione automatica
        self._mtime_tracker = {}
        self._portfolio_state_cache_token = None
        self._history_cache_token = None
        self._hist_df_cache_token = None
        self._expanded_price_frame_cache_token = None

        # Carica dati iniziali
        self._load_all()
        self._mtime_tracker["data"] = _data_mtime()
        os.makedirs(_DERIVED_CACHE_DIR, exist_ok=True)

        # Pre-warming sincrono (timeout 2 secondi)
        self._warm_essential_figures()

    def _load_all(self) -> None:
        """Carica tutti i dati da disco."""
        self._data = load_data()
        prime_isin_ticker_cache(self._data.get("cache_lookup_strumenti", {}))
        self._settings = load_settings()
        self._quotes_log = load_quotes_log()
        self._snapshots_state = load_snapshots()
        self._meta_state = load_meta()

        # Invalida tutta la cache
        self._cache = {key: None for key in self._cache}
        self._instrument_cache = {}
        self._portfolio_state_cache_token = None
        self._history_cache_token = None
        self._hist_df_cache_token = None
        self._expanded_price_frame_cache_token = None
        logger.info(
            "StateManager load completo: strumenti=%s snapshots=%s",
            len(self._data.get("strumenti", [])) if isinstance(self._data, dict) else 0,
            len(self._snapshots_state.get("snapshots", [])) if isinstance(self._snapshots_state, dict) else 0,
        )

    def _warm_essential_figures(self, timeout_seconds: float = 2.0) -> None:
        """Pre-warming sincrono dei dati essenziali (history_df, portfolio_state) con timeout.

        Idempotente: skip se già in cache. Se supera timeout, log warning ma continua.
        """
        start_time = time.time()

        def _warm():
            try:
                if self._cache["portfolio_state"] is None:
                    self._cache["portfolio_state"] = compute_portfolio_state(self._data)
                    self._cache["finance_results"] = self._cache["portfolio_state"]
                    elapsed = time.time() - start_time
                    logger.debug("Pre-warm portfolio_state completato in %.3f secondi", elapsed)

                if self._cache["history_df"] is None:
                    self._cache["history_df"] = build_portfolio_history_df(self._data)
                    elapsed = time.time() - start_time
                    logger.debug("Pre-warm history_df completato in %.3f secondi", elapsed)
            except Exception as exc:
                logger.warning("Errore durante pre-warming: %s", exc)

        thread = threading.Thread(target=_warm, daemon=False)
        thread.start()
        thread.join(timeout=timeout_seconds)

        elapsed = time.time() - start_time
        if thread.is_alive():
            logger.warning("Pre-warming superato timeout (%.1fs > %.1fs): continuando ugualmente", elapsed, timeout_seconds)
        else:
            logger.info("Pre-warming completato in %.3f secondi", elapsed)

    @staticmethod
    def _history_span_token(storico: dict[str, Any], strumenti: list[Any]) -> tuple:
        """
        Parte di token che cattura il perimetro storico per-ticker.

        len(storico)/latest_history_date da soli non rilevano un backfill che
        riempie date piu' vecchie GIA' presenti come chiave (es. altri strumenti
        hanno gia' un prezzo su quel giorno): la chiave non e' nuova, quindi quei
        due numeri restano identici anche se un ticker ha ora piu' storico. Vedi
        core.cache_signatures.history_span_by_ticker per lo stesso fix lato
        firme dei grafici.
        """
        tickers = sorted({
            str(s.get("ticker", "")).strip()
            for s in strumenti
            if isinstance(s, dict) and str(s.get("ticker", "")).strip()
        })
        span = history_span_by_ticker(storico, tickers)
        return tuple(sorted((tk, v["n_dates"], v["earliest"]) for tk, v in span.items()))

    def _derived_data_token(self, data: dict[str, Any]) -> tuple:
        payload = data if isinstance(data, dict) else {}
        storico = payload.get("storico_prezzi", {}) if isinstance(payload.get("storico_prezzi", {}), dict) else {}
        strumenti = payload.get("strumenti", []) if isinstance(payload.get("strumenti", []), list) else []
        operazioni = payload.get("operazioni", []) if isinstance(payload.get("operazioni", []), list) else []
        latest_history_date = max(storico.keys()) if storico else ""
        last_quotes_update = str(payload.get("last_quotes_update") or "")
        state_sig = _portfolio_state_signature(payload, include_closed=True)
        return (
            state_sig,
            last_quotes_update,
            len(storico),
            latest_history_date,
            len(strumenti),
            len(operazioni),
            self._history_span_token(storico, strumenti),
        )

    def _derived_cache_path(self, cache_name: str) -> str:
        return os.path.join(_DERIVED_CACHE_DIR, f"{cache_name}.pkl")

    def _load_persisted_derived(self, cache_name: str, token: tuple[Any, ...]) -> Any | None:
        path = self._derived_cache_path(cache_name)
        if not os.path.exists(path):
            return None
        try:
            payload = pd.read_pickle(path)
        except Exception as exc:
            logger.warning("Cache derivata corrotta (%s): %s", cache_name, exc)
            return None
        if not isinstance(payload, dict) or payload.get("token") != token:
            return None
        logger.debug("Cache derivata persistita hit: %s", cache_name)
        return payload.get("value")

    def _save_persisted_derived(self, cache_name: str, token: tuple[Any, ...], value: Any) -> None:
        path = self._derived_cache_path(cache_name)
        tmp_path = f"{path}.tmp"
        try:
            pd.to_pickle({"token": token, "value": value}, tmp_path)
            os.replace(tmp_path, path)
        except Exception as exc:
            logger.warning("Salvataggio cache derivata fallito (%s): %s", cache_name, exc)
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass

    def _build_hist_df_token_for(self, data: dict[str, Any]) -> tuple:
        """Token per hist_df che esclude operazioni: stabile durante insert operazione."""
        payload = data if isinstance(data, dict) else {}
        storico = payload.get("storico_prezzi", {})
        if not isinstance(storico, dict):
            storico = {}
        strumenti = payload.get("strumenti", [])
        if not isinstance(strumenti, list):
            strumenti = []
        last_quotes_update = str(payload.get("last_quotes_update") or "")
        latest_history_date = max(storico.keys()) if storico else ""
        return (
            "hist_df_v3",
            last_quotes_update,
            len(storico),
            latest_history_date,
            len(strumenti),
            self._history_span_token(storico, strumenti),
        )

    def invalidate(self, keys: list[str]) -> None:
        """
        Invalida solo cache specifiche.

        Args:
            keys: Lista di cache keys da invalidare
                  (es. ["portfolio_state", "analytics"])
        """
        for key in keys:
            if key in self._cache:
                self._cache[key] = None
                if key == "portfolio_state":
                    self._portfolio_state_cache_token = None
                elif key == "history_df":
                    self._history_cache_token = None
                elif key == "hist_df":
                    self._hist_df_cache_token = None
                elif key == "expanded_price_frame":
                    self._expanded_price_frame_cache_token = None
        if keys:
            logger.debug("Cache invalidata: %s", ",".join(keys))

    def get_data(self) -> dict[str, Any]:
        """Ritorna dati primari (strumenti, eventi, etc)."""
        return self._data

    def get_settings(self) -> dict[str, Any]:
        """Ritorna impostazioni."""
        return self._settings

    def get_snapshots(self) -> dict[str, Any]:
        """Ritorna snapshots."""
        return self._snapshots_state

    def get_meta(self) -> dict[str, Any]:
        """Ritorna metadati."""
        return self._meta_state

    def get_portfolio_state(self) -> dict[str, Any]:
        """
        Ritorna stato portafoglio (posizioni, P&L).
        Usa cache se disponibile.
        """
        return self.get_portfolio_state_for(self._data)

    def get_portfolio_state_for(self, data: dict[str, Any]) -> dict[str, Any]:
        """Ritorna stato portafoglio per uno specifico payload filtrato/cacheato."""
        token = ("portfolio_state_v2",) + self._derived_data_token(data)
        if self._cache["portfolio_state"] is None or self._portfolio_state_cache_token != token:
            cached = self._load_persisted_derived("portfolio_state_v2", token)
            if cached is not None:
                self._cache["portfolio_state"] = cached
            else:
                logger.debug("Cache miss portfolio_state")
                self._cache["portfolio_state"] = compute_portfolio_state(data)
                self._save_persisted_derived("portfolio_state_v2", token, self._cache["portfolio_state"])
            self._portfolio_state_cache_token = token
            self._cache["finance_results"] = self._cache["portfolio_state"]
        return self._cache["portfolio_state"]

    def get_history_df_for(self, data: dict[str, Any]) -> pd.DataFrame:
        """Ritorna serie storica per payload filtrato usando cache persistita."""
        token = ("history_df_v4",) + self._derived_data_token(data)
        if self._cache["history_df"] is None or self._history_cache_token != token:
            cached = self._load_persisted_derived("history_df_v4", token)
            if cached is not None:
                self._cache["history_df"] = cached
            else:
                logger.debug("Cache miss history_df")
                self._cache["history_df"] = build_portfolio_history_df(data)
                self._save_persisted_derived("history_df_v4", token, self._cache["history_df"])
            self._history_cache_token = token
        return self._cache["history_df"]

    def get_hist_df_for(self, data: dict[str, Any]) -> pd.DataFrame:
        """Ritorna storico prezzi per payload filtrato usando cache persistita."""
        token = self._build_hist_df_token_for(data)
        if self._cache["hist_df"] is None or self._hist_df_cache_token != token:
            cached = self._load_persisted_derived("hist_df_v3", token)
            if cached is not None:
                self._cache["hist_df"] = cached
            else:
                logger.debug("Cache miss hist_df")
                self._cache["hist_df"] = build_hist_df(data)
                self._save_persisted_derived("hist_df_v3", token, self._cache["hist_df"])
            self._hist_df_cache_token = token
        return self._cache["hist_df"]

    def get_expanded_price_frame_for(self, data: dict[str, Any]) -> pd.DataFrame:
        """Ritorna frame prezzi espanso per payload filtrato usando cache persistita."""
        if self._cache["expanded_price_frame"] is None:
            token = ("expanded_price_frame_v2",) + self._derived_data_token(data)
            self._expanded_price_frame_cache_token = token
            cached = self._load_persisted_derived("expanded_price_frame_v2", token)
            if cached is not None:
                self._cache["expanded_price_frame"] = cached
            else:
                logger.debug("Cache miss expanded_price_frame")
                self._cache["expanded_price_frame"] = build_expanded_price_frame(data, dh_hist=self.get_hist_df_for(data))
                self._save_persisted_derived("expanded_price_frame_v2", token, self._cache["expanded_price_frame"])
        elif self._expanded_price_frame_cache_token != (("expanded_price_frame_v2",) + self._derived_data_token(data)):
            token = ("expanded_price_frame_v2",) + self._derived_data_token(data)
            cached = self._load_persisted_derived("expanded_price_frame_v2", token)
            if cached is not None:
                self._cache["expanded_price_frame"] = cached
            else:
                logger.debug("Cache miss expanded_price_frame")
                self._cache["expanded_price_frame"] = build_expanded_price_frame(data, dh_hist=self.get_hist_df_for(data))
                self._save_persisted_derived("expanded_price_frame_v2", token, self._cache["expanded_price_frame"])
            self._expanded_price_frame_cache_token = token
        return self._cache["expanded_price_frame"]

    def reload_if_changed(self) -> bool:
        """
        Controlla se file dati è cambiato.
        Se sì, ricarica e invalida cache.
        Ritorna: True se reload avvenuto, False altrimenti.
        """
        current_mtime = _data_mtime()
        if current_mtime != self._mtime_tracker.get("data"):
            self._load_all()
            self._mtime_tracker["data"] = current_mtime
            logger.info("Reload automatico eseguito per cambio mtime dati")
            return True
        return False

    def force_reload(self) -> None:
        """Ricarica lo stato da disco e invalida tutte le cache derivate."""
        self._load_all()
        self._mtime_tracker["data"] = _data_mtime()
        logger.info("Reload forzato eseguito")

    def get_instrument_events(self, ticker: str) -> list[dict[str, Any]]:
        """
        Ritorna eventi per strumento (filtrati dal registro).
        Cache a livello di strumento.
        """
        cache_key = f"events_{ticker}"
        if cache_key not in self._instrument_cache:
            from persistence.storage import get_registro_eventi
            registro = get_registro_eventi(self._data)
            strumento_events = [e for e in registro if e.get("ticker") == ticker]
            self._instrument_cache[cache_key] = strumento_events
        return self._instrument_cache[cache_key]
