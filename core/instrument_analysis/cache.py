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

ALGORITHM_VERSION = "1.1.0"  # invariata: il cambio di motore del benchmark non tocca profilo e ruoli C/D/S che SATOR legge dalla cache; le voci si rinnovano alla scadenza
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
    """Cache di analisi (comprende risoluzione benchmark) SOLO SQLite."""
    from core.verified_benchmarks import IndexStore
    return IndexStore().preference('analysis_resolution_cache',{}) or {}


# Snapshot di sola lettura della cache di risoluzione, per percorso dell'archivio.
_SNAPSHOT_MEMO: dict[str, tuple[tuple, dict[str, Any]]] = {}


def load_resolution_cache_snapshot() -> dict[str, Any]:
    """Cache di risoluzione condivisa e SOLA LETTURA, riletta solo se il database cambia.

    `peek_cached` la chiede per ogni strumento e per ogni chiamante di SATOR
    (centinaia di volte per run): prima ogni chiamata apriva una connessione
    SQLite e rifaceva il parse di ~200 KB di JSON. L'oggetto restituito e'
    condiviso: chi deve modificarlo usa `load_resolution_cache()`, che
    restituisce una copia indipendente.
    """
    from core.verified_benchmarks import IndexStore
    store=IndexStore()
    key=str(store.path)
    stat=store.stat_key()
    memo=_SNAPSHOT_MEMO.get(key)
    if memo is not None and memo[0]==stat:
        return memo[1]
    payload=store.preference('analysis_resolution_cache',{}) or {}
    _SNAPSHOT_MEMO[key]=(store.stat_key(),payload)
    return payload


def save_resolution_cache(cache:dict[str,Any])->None:
    from core.verified_benchmarks import IndexStore
    IndexStore().save_preference('analysis_resolution_cache',cache)


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


def load_series_cache() -> dict[str,Any]:
    from core.verified_benchmarks import IndexStore
    return IndexStore().preference('analysis_series_cache',{}) or {}


def save_series_cache(cache:dict[str,Any])->None:
    from core.verified_benchmarks import IndexStore
    IndexStore().save_preference('analysis_series_cache',cache)


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
