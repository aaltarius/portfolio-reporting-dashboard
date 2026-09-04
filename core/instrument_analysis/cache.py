"""Cache persistente su disco per il motore InstrumentAnalysis.

Due cache separate (spec sezione 9): risoluzione (identity/profilo/C-D-S/
benchmark, TTL lungo) e storici/curve operative (TTL giornaliero, gestita
altrove — vedi series.py). Questo modulo copre solo la cache di
risoluzione. Stesso pattern di scrittura atomica di persistence/storage.py.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from core.config import DATA_DIR

ALGORITHM_VERSION = "1.0.0"

_CACHE_SUBDIR = "instrument_analysis"

_resolution_cache_lock = threading.Lock()
_resolution_cache_state: dict[str, Any] = {"path": None, "mtime": None, "data": None}


def _cache_dir() -> Path:
    return Path(DATA_DIR) / "cache" / _CACHE_SUBDIR


def resolution_cache_path() -> Path:
    return _cache_dir() / "resolution.json"


def series_cache_path() -> Path:
    return _cache_dir() / "series.json"


def resolution_cache_key(ticker: str, isin: str) -> str:
    tk = str(ticker or "").strip().upper()
    isincode = str(isin or "").strip().upper()
    return f"{tk}|{isincode}"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, default=str)
    os.replace(tmp, str(path))


def load_resolution_cache() -> dict[str, Any]:
    """Legge la cache di risoluzione, memoizzata in-process per mtime del
    file. `peek_cached()` la richiama per OGNI strumento in cicli stretti
    (SATOR, Fase C) - senza questa memoizzazione ogni chiamata rilegge e
    riparsa da zero l'intero file JSON, anche >150 volte per un singolo
    render pagina (bug reale trovato 2026-09-05: la pagina "Quote &
    impostazioni" del form-server impiegava 3-4s solo per questo, oltre il
    timeout di probe della sidebar - i bottoni sidebar non aprivano piu' la
    scheda). Il path e' incluso nel confronto (non solo l'mtime) per
    restare corretta quando i test isolano `DATA_DIR` con monkeypatch."""
    path = resolution_cache_path()
    try:
        mtime = os.path.getmtime(path) if path.exists() else None
    except OSError:
        mtime = None
    with _resolution_cache_lock:
        if (
            _resolution_cache_state["data"] is not None
            and _resolution_cache_state["path"] == path
            and _resolution_cache_state["mtime"] == mtime
        ):
            return _resolution_cache_state["data"]
        data = _read_json(path)
        _resolution_cache_state["path"] = path
        _resolution_cache_state["mtime"] = mtime
        _resolution_cache_state["data"] = data
        return data


def save_resolution_cache(cache: dict[str, Any]) -> None:
    path = resolution_cache_path()
    _write_json_atomic(path, cache)
    try:
        mtime = os.path.getmtime(path) if path.exists() else None
    except OSError:
        mtime = None
    with _resolution_cache_lock:
        _resolution_cache_state["path"] = path
        _resolution_cache_state["mtime"] = mtime
        _resolution_cache_state["data"] = cache


def put_cached_resolution(cache: dict[str, Any], key: str, payload: dict[str, Any]) -> None:
    entry = dict(payload)
    entry["cached_at"] = time.time()
    entry["algorithm_version"] = ALGORITHM_VERSION
    cache[key] = entry


def get_cached_resolution(cache: dict[str, Any], key: str, ttl_days: float) -> dict[str, Any] | None:
    entry = cache.get(key)
    if not isinstance(entry, dict):
        return None
    if entry.get("algorithm_version") != ALGORITHM_VERSION:
        return None
    cached_at = entry.get("cached_at")
    if not isinstance(cached_at, (int, float)):
        return None
    if (time.time() - cached_at) > (ttl_days * 86400):
        return None
    return entry


def load_series_cache() -> dict[str, Any]:
    return _read_json(series_cache_path())


def save_series_cache(cache: dict[str, Any]) -> None:
    _write_json_atomic(series_cache_path(), cache)


def put_cached_series(cache: dict[str, Any], ticker: str, history: dict[str, float]) -> None:
    cache[str(ticker or "").strip().upper()] = {"history": history, "cached_at": time.time()}


def get_cached_series(cache: dict[str, Any], ticker: str, ttl_days: float) -> dict[str, float] | None:
    entry = cache.get(str(ticker or "").strip().upper())
    if not isinstance(entry, dict):
        return None
    cached_at = entry.get("cached_at")
    if not isinstance(cached_at, (int, float)):
        return None
    if (time.time() - cached_at) > (ttl_days * 86400):
        return None
    history = entry.get("history")
    return history if isinstance(history, dict) else None
