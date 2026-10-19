"""Cache persistente su disco per il motore InstrumentAnalysis.

Due cache separate (spec sezione 9): risoluzione (identity/profilo/C-D-S/
benchmark, TTL lungo) e storici/curve operative (TTL giornaliero, gestita
altrove — vedi series.py). Questo modulo copre solo la cache di
risoluzione. Stesso pattern di scrittura atomica di persistence/storage.py.
"""
from __future__ import annotations

import json
import os
import random
import threading
import time
import zlib
from pathlib import Path
from typing import Any

from core.config import DATA_DIR

ALGORITHM_VERSION = "1.1.0"  # Task V (2026-09-05): _hierarchical_role_prior
# rivisto (factor/size tilt equity spostati a Satellite, P3) - invalida la
# cache disco cosi' ogni strumento gia' analizzato viene ricalcolato con le
# nuove percentuali C/D/S invece di continuare a servire quelle vecchie fino
# alla scadenza naturale del TTL (14 giorni).

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


#: Le entry non scadono tutte a 14 giorni esatti: ognuna riceve un TTL tra il
#: 70% e il 100% del default, cosi' le scadenze si distribuiscono su ~4 giorni
#: invece di cadere insieme (log reale 2026-10-19: 29 entry create nello
#: stesso ciclo, scadute insieme, 213s di render bloccato a rifarle).
_TTL_JITTER_MIN_FRACTION = 0.7


def _jitter_fraction_for_key(key: str) -> float:
    """Frazione deterministica in [MIN, 1.0] derivata dalla chiave: serve alle
    entry legacy senza `ttl_days`, che altrimenti scadrebbero tutte insieme."""
    frac = (zlib.crc32(key.encode("utf-8")) & 0xFFFFFFFF) / 0xFFFFFFFF
    return _TTL_JITTER_MIN_FRACTION + (1.0 - _TTL_JITTER_MIN_FRACTION) * frac


def entry_ttl_days(entry: dict[str, Any], key: str, default_ttl_days: float) -> float:
    """TTL effettivo = TTL del chiamante x fattore di sfalsamento dell'entry
    (salvato alla scrittura, o derivato dalla chiave per le entry legacy)."""
    factor = entry.get("ttl_factor")
    if not (isinstance(factor, (int, float)) and _TTL_JITTER_MIN_FRACTION <= factor <= 1.0):
        factor = _jitter_fraction_for_key(key)
    return default_ttl_days * float(factor)


def put_cached_resolution(cache: dict[str, Any], key: str, payload: dict[str, Any]) -> None:
    entry = dict(payload)
    entry["cached_at"] = time.time()
    entry["algorithm_version"] = ALGORITHM_VERSION
    entry["ttl_factor"] = random.uniform(_TTL_JITTER_MIN_FRACTION, 1.0)
    cache[key] = entry


def resolution_remaining_days(cache: dict[str, Any], key: str, ttl_days: float) -> float | None:
    """Giorni residui di validita' (negativi se scaduta). None se l'entry non
    esiste o ha una versione d'algoritmo diversa (va ricalcolata, non servita)."""
    entry = cache.get(key)
    if not isinstance(entry, dict) or entry.get("algorithm_version") != ALGORITHM_VERSION:
        return None
    cached_at = entry.get("cached_at")
    if not isinstance(cached_at, (int, float)):
        return None
    return entry_ttl_days(entry, key, ttl_days) - (time.time() - cached_at) / 86400.0


def get_cached_resolution(cache: dict[str, Any], key: str, ttl_days: float) -> dict[str, Any] | None:
    remaining = resolution_remaining_days(cache, key, ttl_days)
    if remaining is None or remaining < 0:
        return None
    return cache[key]


def get_stale_resolution(
    cache: dict[str, Any], key: str, ttl_days: float, max_stale_days: float,
) -> dict[str, Any] | None:
    """Entry scaduta ma ancora entro `max_stale_days` dalla creazione: meglio
    un dato vecchio subito che rete bloccante nel render (regola non
    negoziabile 1). Il rinnovo lo fa il worker in background."""
    remaining = resolution_remaining_days(cache, key, ttl_days)
    if remaining is None:
        return None
    age_days = (time.time() - float(cache[key]["cached_at"])) / 86400.0
    return cache[key] if age_days <= max_stale_days else None


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
