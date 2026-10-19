"""Aggiornamento silenzioso della cache InstrumentAnalysis.

Rinnovo ANTICIPATO e a piccoli passi (2026-10-19, dopo un render da 213s per
29 entry scadute insieme): acceso di default, rinnova le entry a cui restano
meno di `renew_ahead_days` giorni (le piu' urgenti prima), poche per ciclo,
con una pausa tra una richiesta e l'altra, e si ferma al primo errore invece
di insistere sulla rete. Insieme alle scadenze sfalsate e alle entry "stale"
servite dal render (vedi core/instrument_analysis/cache.py) l'utente non
dovrebbe piu' aspettare la rete durante il disegno delle pagine.

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
from core.domain.instrument_status import active_fetch_tickers
from core.infrastructure.market_auto_refresh import should_refresh_market_auto
from core.instrument_analysis import cache as ia_cache
from core.instrument_analysis.service import _RESOLUTION_TTL_DAYS
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


def _coerce_float(value: Any, *, default: float, min_value: float, max_value: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        parsed = default
    return max(min_value, min(max_value, parsed))


def normalize_instrument_analysis_auto_refresh_settings(settings: dict[str, Any] | None) -> dict[str, Any]:
    raw_settings = settings if isinstance(settings, dict) else {}
    raw = raw_settings.get("instrument_analysis_auto_refresh", {})
    cfg = raw if isinstance(raw, dict) else {}
    return {
        "enabled": bool(cfg.get("enabled", True)),
        "interval_minutes": _coerce_int(
            cfg.get("interval_minutes", 15), default=15, min_value=5, max_value=1440,
        ),
        # Poche per ciclo: analyze() puo' costare fino a ~10s per strumento;
        # il resto lo prende il ciclo successivo, nessuna raffica di rete.
        "max_instruments_per_cycle": _coerce_int(
            cfg.get("max_instruments_per_cycle", 3), default=3, min_value=1, max_value=100,
        ),
        # Pausa tra una risoluzione e la successiva dentro lo stesso ciclo.
        "pause_seconds": _coerce_int(
            cfg.get("pause_seconds", 45), default=45, min_value=0, max_value=600,
        ),
        # Quanto prima della scadenza si rinnova: la entry viene sostituita
        # prima che il render la trovi scaduta.
        "renew_ahead_days": _coerce_float(
            cfg.get("renew_ahead_days", 3.0), default=3.0, min_value=0.0, max_value=14.0,
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
    cache = ia_cache.load_resolution_cache()
    active = active_fetch_tickers(data)
    ahead = float(cfg["renew_ahead_days"])

    report: dict[str, Any] = {"checked": 0, "refreshed": 0, "failed": [], "skipped_cap": 0}
    due: list[tuple[float, dict[str, Any], str]] = []
    for item in data.get("strumenti", []) or []:
        ticker = str(item.get("ticker") or "").strip().upper()
        # Chiusi/terminali esclusi (classe di bug ricorrente, vedi CLAUDE.md).
        if not ticker or ticker not in active:
            continue
        isin = str(item.get("isin") or "").strip().upper()
        report["checked"] += 1
        remaining = ia_cache.resolution_remaining_days(
            cache, ia_cache.resolution_cache_key(ticker, isin), _RESOLUTION_TTL_DAYS,
        )
        # Mancante (None) = piu' urgente di tutto; poi le piu' scadute/vicine.
        if remaining is None:
            due.append((float("-inf"), item, ticker))
        elif remaining < ahead:
            due.append((remaining, item, ticker))
    due.sort(key=lambda row: row[0])

    batch = due[: int(cfg["max_instruments_per_cycle"])]
    report["skipped_cap"] = len(due) - len(batch)
    pause = int(cfg["pause_seconds"])
    for index, (_remaining, item, ticker) in enumerate(batch):
        if index > 0 and pause > 0:
            time.sleep(pause)
        try:
            resolve_instrument_benchmark(item, master_entry=master.get(ticker), force_refresh=True)
            report["refreshed"] += 1
        except Exception as exc:
            # Rete probabilmente giu': ci si ferma, il ciclo dopo riprova.
            logger.warning("Refresh InstrumentAnalysis fallito per %s: %s", ticker, exc, exc_info=True)
            report["failed"].append(ticker)
            report["skipped_cap"] += len(batch) - index - 1
            break

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
