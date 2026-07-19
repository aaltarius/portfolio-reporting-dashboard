"""
core/infrastructure/schedule.py — Scheduler per benchmark refresh automatico alle 18:00 italiane.
Thread daemon con retry exponential, idempotente, persistente.
"""
import json
import logging
import threading
import time
from datetime import datetime, time as time_type
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("portafoglio.core.infrastructure.schedule")

_benchmark_scheduler_thread: Optional[threading.Thread] = None
_scheduler_lock = threading.Lock()
_BENCHMARK_REFRESH_TIME = time_type(18, 0)  # 18:00 italiane
_BENCHMARK_REFRESH_STATE_FILE = Path(__file__).parent.parent.parent / "data" / "config" / "benchmark_last_refresh.json"


def _read_benchmark_refresh_state() -> dict[str, Any]:
    """Legge timestamp ultimo refresh per ticker."""
    try:
        if _BENCHMARK_REFRESH_STATE_FILE.exists():
            raw = _BENCHMARK_REFRESH_STATE_FILE.read_text()
            if raw.strip():
                return json.loads(raw)
    except Exception:
        pass
    return {}


def _write_benchmark_refresh_state(state: dict[str, Any]) -> None:
    """Salva timestamp ultimo refresh."""
    try:
        _BENCHMARK_REFRESH_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _BENCHMARK_REFRESH_STATE_FILE.write_text(json.dumps(state, indent=2))
    except Exception as exc:
        logger.warning("Errore durante salvataggio benchmark refresh state: %s", exc)


def set_benchmark_last_refresh(ticker: str, ts: Optional[float] = None) -> None:
    """Setta timestamp ultimo refresh per ticker (None = adesso)."""
    state = _read_benchmark_refresh_state()
    state[ticker] = ts if ts is not None else time.time()
    _write_benchmark_refresh_state(state)


def _seconds_until_next_refresh() -> int:
    """Ritorna secondi fino alle prossime 18:00 italiane."""
    now = datetime.now()
    target = datetime.combine(now.date(), _BENCHMARK_REFRESH_TIME)
    if now >= target:
        target = datetime.combine(now.date(), _BENCHMARK_REFRESH_TIME) + __import__("datetime").timedelta(days=1)
    return int((target - now).total_seconds())


def _do_benchmark_refresh(data: dict[str, Any]) -> None:
    """Esegue refresh benchmark con retry exponential."""
    from core.finance import refresh_benchmark_cache

    retry_count = 0
    max_retries = 3
    base_delay = 5

    while retry_count < max_retries:
        try:
            count = refresh_benchmark_cache(data, force=False)
            logger.info("Benchmark refresh completato: %d ticker aggiornati", count)

            # Salva timestamp per ogni ticker
            for ticker in data.get("benchmark_data", {}).keys():
                set_benchmark_last_refresh(ticker, time.time())

            return
        except Exception as exc:
            retry_count += 1
            if retry_count < max_retries:
                delay = base_delay * (2 ** (retry_count - 1))
                logger.warning("Errore benchmark refresh (retry %d/%d dopo %.0fs): %s", retry_count, max_retries, delay, exc)
                time.sleep(delay)
            else:
                logger.error("Benchmark refresh fallito dopo %d tentativi: %s", max_retries, exc)


def _scheduler_loop(data: dict[str, Any]) -> None:
    """Loop dello scheduler: si sveglia ogni giorno a 18:00 e fa refresh benchmark."""
    logger.info("Benchmark scheduler avviato, prossimo refresh a 18:00 italiane")

    while True:
        try:
            sleep_seconds = _seconds_until_next_refresh()
            logger.debug("Scheduler in sleep per %.0f secondi fino prossimo refresh", sleep_seconds)
            time.sleep(sleep_seconds)

            logger.info("Esecuzione refresh benchmark scheduler @ 18:00")
            _do_benchmark_refresh(data)
        except Exception as exc:
            logger.error("Errore nello scheduler loop: %s", exc)
            time.sleep(60)  # Retry dopo 1 minuto se errore


def start_benchmark_scheduler(data: dict[str, Any]) -> bool:
    """
    Avvia lo scheduler benchmark in background se non già in esecuzione.
    Ritorna True se il thread è stato avviato, False se già attivo.
    Usa il nome del thread come guard process-wide: funziona anche dopo
    hot-reload di Streamlit (reimport azzera la variabile globale ma i
    thread preesistenti restano vivi con lo stesso nome).
    """
    global _benchmark_scheduler_thread
    with _scheduler_lock:
        # Cerca tra tutti i thread vivi, non solo nella variabile locale al modulo
        for t in threading.enumerate():
            if t.name == "BenchmarkScheduler" and t.is_alive():
                _benchmark_scheduler_thread = t  # re-aggancia il riferimento
                return False

        _benchmark_scheduler_thread = threading.Thread(
            target=_scheduler_loop,
            args=(data,),
            daemon=True,
            name="BenchmarkScheduler",
        )
        _benchmark_scheduler_thread.start()
        logger.info("Benchmark scheduler thread avviato")
    return True
