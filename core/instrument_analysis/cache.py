"""Cache persistente su disco per il motore InstrumentAnalysis.

Due cache separate (spec sezione 9): risoluzione (identity/profilo/C-D-S/
benchmark, TTL lungo) e storici/curve operative (TTL giornaliero, gestita
altrove — vedi series.py). Questo modulo copre solo la cache di
risoluzione. Stesso pattern di scrittura atomica di persistence/storage.py.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from core.config import DATA_DIR

ALGORITHM_VERSION = "1.0.0"

_CACHE_SUBDIR = "instrument_analysis"


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
    return _read_json(resolution_cache_path())


def save_resolution_cache(cache: dict[str, Any]) -> None:
    _write_json_atomic(resolution_cache_path(), cache)


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
