"""Aggiornamento silenzioso della cache Mercati.

Il servizio non usa API Streamlit: aggiorna i file cache in background e lascia
alla UI il normale ciclo di rerun per rileggere i dati aggiornati.
"""
from __future__ import annotations

import json
import logging
import math
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from core.services.market_universe_refresh import (
    DEFAULT_MARKET_REFRESH_PERIOD,
    refresh_market_universe_benchmark_data,
    refresh_market_universe_live_data,
)
from persistence.storage import (
    BENCHMARK_CACHE_FILE,
    default_benchmark_cache,
    load_settings,
    save_benchmark_data,
    _read_json_file,
)
from ui.market_universe import MARKET_UNIVERSE_ITEMS


logger = logging.getLogger("portafoglio.core.infrastructure.market_auto_refresh")

_THREAD_NAME = "MarketAutoRefreshScheduler"
_scheduler_lock = threading.Lock()
_market_auto_refresh_thread: threading.Thread | None = None
_STATE_FILE = Path(BENCHMARK_CACHE_FILE).parent / "market_auto_refresh_state.json"


def _coerce_int(value: Any, *, default: int, min_value: int, max_value: int) -> int:
    try:
        parsed = int(float(value))
    except (TypeError, ValueError, OverflowError):
        parsed = default
    return max(min_value, min(max_value, parsed))


def normalize_market_auto_refresh_settings(settings: dict[str, Any] | None) -> dict[str, Any]:
    raw_settings = settings if isinstance(settings, dict) else {}
    raw = raw_settings.get("market_auto_refresh", {})
    cfg = raw if isinstance(raw, dict) else {}
    return {
        "enabled": bool(cfg.get("enabled", False)),
        "live_interval_minutes": _coerce_int(
            cfg.get("live_interval_minutes", 30),
            default=30,
            min_value=5,
            max_value=240,
        ),
        "history_enabled": bool(cfg.get("history_enabled", True)),
        "history_interval_minutes": _coerce_int(
            cfg.get("history_interval_minutes", 240),
            default=240,
            min_value=60,
            max_value=1440,
        ),
        "only_when_markets_open": bool(cfg.get("only_when_markets_open", True)),
    }


def should_refresh_market_auto(last_ts: float | int | None, now_ts: float, interval_minutes: int) -> bool:
    if last_ts is None:
        return True
    try:
        previous = float(last_ts)
    except (TypeError, ValueError, OverflowError):
        return True
    if not math.isfinite(previous) or previous <= 0:
        return True
    return (float(now_ts) - previous) >= max(1, int(interval_minutes)) * 60


def _read_state() -> dict[str, Any]:
    try:
        if _STATE_FILE.exists():
            raw = _STATE_FILE.read_text(encoding="utf-8")
            if raw.strip():
                payload = json.loads(raw)
                if isinstance(payload, dict):
                    return payload
    except Exception:
        logger.warning("Lettura stato auto-refresh Mercati fallita", exc_info=True)
    return {}


def _write_state(state: dict[str, Any]) -> None:
    try:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        logger.warning("Scrittura stato auto-refresh Mercati fallita", exc_info=True)


def _market_is_open(item: dict[str, Any], now_utc: datetime | None = None) -> bool:
    try:
        tz = ZoneInfo(str(item.get("tz") or "UTC"))
        now = (now_utc or datetime.now(ZoneInfo("UTC"))).astimezone(tz)
        if now.weekday() >= 5:
            return False
        open_time = item.get("open")
        close_time = item.get("close")
        if open_time is None or close_time is None:
            return True
        return bool(open_time <= now.time() <= close_time)
    except Exception:
        return True


def any_market_open(items: list[dict[str, Any]] | None = None, now_utc: datetime | None = None) -> bool:
    source = items if items is not None else MARKET_UNIVERSE_ITEMS
    return any(_market_is_open(dict(item), now_utc=now_utc) for item in source if isinstance(item, dict))


def _refresh_once(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = normalize_market_auto_refresh_settings(settings or load_settings())
    state = _read_state()
    now_ts = time.time()
    now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if not cfg["enabled"]:
        state.update({"enabled": False, "last_check_at": now_text, "last_status": "disabled"})
        _write_state(state)
        return state

    if cfg["only_when_markets_open"] and not any_market_open():
        state.update({
            "enabled": True,
            "last_check_at": now_text,
            "last_status": "skipped",
            "last_message": "Nessun mercato dell'universo risulta aperto.",
        })
        _write_state(state)
        return state

    due_live = should_refresh_market_auto(
        state.get("last_live_ts"),
        now_ts,
        int(cfg["live_interval_minutes"]),
    )
    due_history = bool(cfg["history_enabled"]) and should_refresh_market_auto(
        state.get("last_history_ts"),
        now_ts,
        int(cfg["history_interval_minutes"]),
    )
    if not due_live and not due_history:
        state.update({"enabled": True, "last_check_at": now_text, "last_status": "fresh"})
        _write_state(state)
        return state

    payload = _read_json_file(BENCHMARK_CACHE_FILE, default_benchmark_cache())
    reports: dict[str, Any] = {}
    if due_live:
        reports["live"] = refresh_market_universe_live_data(payload, MARKET_UNIVERSE_ITEMS)
        state["last_live_ts"] = now_ts
        state["last_live_at"] = now_text
    if due_history:
        reports["history"] = refresh_market_universe_benchmark_data(
            payload,
            MARKET_UNIVERSE_ITEMS,
            period=DEFAULT_MARKET_REFRESH_PERIOD,
        )
        state["last_history_ts"] = now_ts
        state["last_history_at"] = now_text

    save_benchmark_data(payload)
    state.update({
        "enabled": True,
        "last_check_at": now_text,
        "last_status": "updated",
        "last_report": reports,
    })
    _write_state(state)
    return state


def _scheduler_loop() -> None:
    logger.info("Auto-refresh Mercati avviato")
    while True:
        sleep_seconds = 60
        try:
            settings = load_settings()
            cfg = normalize_market_auto_refresh_settings(settings)
            if cfg["enabled"]:
                _refresh_once(settings)
                sleep_seconds = max(30, min(120, int(cfg["live_interval_minutes"]) * 60))
            else:
                sleep_seconds = 120
        except Exception as exc:
            logger.warning("Auto-refresh Mercati non completato: %s", exc, exc_info=True)
            sleep_seconds = 60
        time.sleep(sleep_seconds)


def start_market_auto_refresh_scheduler(settings: dict[str, Any] | None = None) -> bool:
    """Avvia il worker se abilitato e non gia' vivo nel processo Streamlit."""
    global _market_auto_refresh_thread
    cfg = normalize_market_auto_refresh_settings(settings or load_settings())
    if not cfg["enabled"]:
        return False
    with _scheduler_lock:
        for thread in threading.enumerate():
            if thread.name == _THREAD_NAME and thread.is_alive():
                _market_auto_refresh_thread = thread
                return False
        _market_auto_refresh_thread = threading.Thread(
            target=_scheduler_loop,
            daemon=True,
            name=_THREAD_NAME,
        )
        _market_auto_refresh_thread.start()
        logger.info("Thread auto-refresh Mercati avviato")
        return True


__all__ = [
    "any_market_open",
    "normalize_market_auto_refresh_settings",
    "should_refresh_market_auto",
    "start_market_auto_refresh_scheduler",
]
