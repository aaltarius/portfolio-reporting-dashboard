"""Aggiornamento silenzioso della cache InstrumentAnalysis.

Stesso pattern di core/infrastructure/market_auto_refresh.py: aggiorna la
cache su disco in background (thread daemon separato), lasciando alla UI
il normale ciclo di rerun per rileggerla — mai una chiamata di rete dal
render di una pagina (regola non negoziabile 1). Disattivato di default
(Fase D, Task D1, deciso con l'utente 2026-09-04): l'utente lo accende da
Impostazioni.

Riusa `core.benchmark_registry.resolve_instrument_benchmark` invece di
chiamare `InstrumentAnalysisService.analyze()` direttamente: quella
funzione gia' applica l'override manuale e calcola `duration_years` per i
BTP, e come side-effect popola l'INTERA cache di risoluzione (profilo +
CDS + benchmark insieme, vedi `_analysis_to_cache_payload` in
`core/instrument_analysis/service.py`) — non serve duplicare quella
logica qui.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from core.benchmark_registry import resolve_instrument_benchmark
from core.infrastructure.market_auto_refresh import should_refresh_market_auto
from core.instrument_analysis.service import InstrumentAnalysisService
from persistence.storage import BENCHMARK_CACHE_FILE, load_data, load_settings

logger = logging.getLogger("portafoglio.core.infrastructure.instrument_analysis_auto_refresh")

_THREAD_NAME = "InstrumentAnalysisAutoRefreshScheduler"
_scheduler_lock = threading.Lock()
_instrument_analysis_auto_refresh_thread: threading.Thread | None = None
_STATE_FILE = Path(BENCHMARK_CACHE_FILE).parent / "instrument_analysis_auto_refresh_state.json"


def _coerce_int(value: Any, *, default: int, min_value: int, max_value: int) -> int:
    try:
        parsed = int(float(value))
    except (TypeError, ValueError, OverflowError):
        parsed = default
    return max(min_value, min(max_value, parsed))


def normalize_instrument_analysis_auto_refresh_settings(settings: dict[str, Any] | None) -> dict[str, Any]:
    raw_settings = settings if isinstance(settings, dict) else {}
    raw = raw_settings.get("instrument_analysis_auto_refresh", {})
    cfg = raw if isinstance(raw, dict) else {}
    return {
        "enabled": bool(cfg.get("enabled", False)),
        # Piu' lento del Mercati (30 min di default): qui non serve un dato
        # "vivo", solo colmare la cache nel tempo.
        "interval_minutes": _coerce_int(
            cfg.get("interval_minutes", 60), default=60, min_value=15, max_value=1440,
        ),
        # Cap di sicurezza per ciclo: analyze() puo' costare fino a 8s per
        # strumento (regola non negoziabile 0), un universo grande non deve
        # bloccare un singolo ciclo per minuti - il resto lo prende il
        # ciclo successivo.
        "max_instruments_per_cycle": _coerce_int(
            cfg.get("max_instruments_per_cycle", 20), default=20, min_value=1, max_value=100,
        ),
    }


def _read_state() -> dict[str, Any]:
    try:
        if _STATE_FILE.exists():
            raw = _STATE_FILE.read_text(encoding="utf-8")
            if raw.strip():
                payload = json.loads(raw)
                if isinstance(payload, dict):
                    return payload
    except Exception:
        logger.warning("Lettura stato auto-refresh InstrumentAnalysis fallita", exc_info=True)
    return {}


def _write_state(state: dict[str, Any]) -> None:
    try:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        logger.warning("Scrittura stato auto-refresh InstrumentAnalysis fallita", exc_info=True)


def _refresh_once(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = normalize_instrument_analysis_auto_refresh_settings(settings or load_settings())
    state = _read_state()
    now_ts = time.time()
    now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if not cfg["enabled"]:
        state.update({"enabled": False, "last_check_at": now_text, "last_status": "disabled"})
        _write_state(state)
        return state

    # Stesso controllo di "e' scaduto l'intervallo" gia' usato dal
    # refresh Mercati: logica generica su timestamp, non specifica di
    # dominio, non vale la pena duplicarla per un solo altro chiamante.
    due = should_refresh_market_auto(state.get("last_run_ts"), now_ts, int(cfg["interval_minutes"]))
    if not due:
        state.update({"enabled": True, "last_check_at": now_text, "last_status": "fresh"})
        _write_state(state)
        return state

    data = load_data()
    master = data.get("instrument_master", {}) if isinstance(data.get("instrument_master", {}), dict) else {}
    service = InstrumentAnalysisService()

    report: dict[str, Any] = {"checked": 0, "refreshed": 0, "failed": [], "skipped_cap": 0}
    cap = int(cfg["max_instruments_per_cycle"])
    for item in data.get("strumenti", []) or []:
        ticker = str(item.get("ticker") or "").strip().upper()
        if not ticker:
            continue
        isin = str(item.get("isin") or "").strip().upper()
        report["checked"] += 1
        if service.peek_cached(ticker=ticker, isin=isin) is not None:
            continue
        if report["refreshed"] >= cap:
            report["skipped_cap"] += 1
            continue
        try:
            resolve_instrument_benchmark(item, master_entry=master.get(ticker))
            report["refreshed"] += 1
        except Exception as exc:
            logger.warning("Refresh InstrumentAnalysis fallito per %s: %s", ticker, exc, exc_info=True)
            report["failed"].append(ticker)

    state.update({
        "enabled": True,
        "last_check_at": now_text,
        "last_run_ts": now_ts,
        "last_run_at": now_text,
        "last_status": "updated",
        "last_report": report,
    })
    _write_state(state)
    return state


def _scheduler_loop() -> None:
    logger.info("Auto-refresh InstrumentAnalysis avviato")
    while True:
        sleep_seconds = 60
        try:
            settings = load_settings()
            cfg = normalize_instrument_analysis_auto_refresh_settings(settings)
            if cfg["enabled"]:
                _refresh_once(settings)
                sleep_seconds = max(60, min(300, int(cfg["interval_minutes"]) * 60))
            else:
                sleep_seconds = 120
        except Exception as exc:
            logger.warning("Auto-refresh InstrumentAnalysis non completato: %s", exc, exc_info=True)
            sleep_seconds = 60
        time.sleep(sleep_seconds)


def start_instrument_analysis_auto_refresh_scheduler(settings: dict[str, Any] | None = None) -> bool:
    """Avvia il worker se abilitato e non gia' vivo nel processo Streamlit."""
    global _instrument_analysis_auto_refresh_thread
    cfg = normalize_instrument_analysis_auto_refresh_settings(settings or load_settings())
    if not cfg["enabled"]:
        return False
    with _scheduler_lock:
        for thread in threading.enumerate():
            if thread.name == _THREAD_NAME and thread.is_alive():
                _instrument_analysis_auto_refresh_thread = thread
                return False
        _instrument_analysis_auto_refresh_thread = threading.Thread(
            target=_scheduler_loop,
            daemon=True,
            name=_THREAD_NAME,
        )
        _instrument_analysis_auto_refresh_thread.start()
        logger.info("Thread auto-refresh InstrumentAnalysis avviato")
        return True


__all__ = [
    "normalize_instrument_analysis_auto_refresh_settings",
    "start_instrument_analysis_auto_refresh_scheduler",
]
