from __future__ import annotations

import logging
import time
from collections import OrderedDict
from dataclasses import dataclass
from threading import RLock
from typing import Any

from core.cache_policy import get_cache_artifact_spec, iter_cache_artifact_specs

logger = logging.getLogger("portafoglio.core.runtime_cache")


@dataclass(frozen=True)
class RuntimeCacheStats:
    """Stato sintetico di una cache runtime registrata."""

    artifact_id: str
    namespace: str
    clear_group: str
    size: int
    max_entries: int
    hits: int
    misses: int
    sets: int


class RegisteredRuntimeCache:
    """Adapter unico per piccole cache runtime in memoria.

    Serve a evitare dizionari privati non censiti: ogni istanza deve puntare a
    un artifact del registry centrale, cosi' diagnostica e pulizia parlano la
    stessa lingua del resto della cache 5.0.
    """

    def __init__(self, artifact_id: str, *, namespace: str = "default", max_entries: int = 0):
        spec = get_cache_artifact_spec(artifact_id)
        self.artifact_id = spec.artifact_id
        self.namespace = str(namespace or "default")
        self.clear_group = spec.clear_group
        self.max_entries = max(0, int(max_entries or 0))
        self._items: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._lock = RLock()
        self._hits = 0
        self._misses = 0
        self._sets = 0

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    def __contains__(self, key: object) -> bool:
        with self._lock:
            return str(key) in self._items

    def get(self, key: str, default: Any = None, *, max_age_seconds: int | float | None = None) -> Any:
        cache_key = str(key)
        with self._lock:
            item = self._items.get(cache_key)
            if item is None:
                self._misses += 1
                return default
            ts, value = item
            if max_age_seconds is not None and (time.time() - ts) > float(max_age_seconds):
                self._items.pop(cache_key, None)
                self._misses += 1
                return default
            self._items.move_to_end(cache_key)
            self._hits += 1
            return value

    def set(self, key: str, value: Any) -> None:
        cache_key = str(key)
        with self._lock:
            self._items[cache_key] = (time.time(), value)
            self._items.move_to_end(cache_key)
            self._sets += 1
            self._evict_if_needed()

    def update(self, values: dict[str, Any]) -> None:
        for key, value in (values or {}).items():
            self.set(str(key), value)

    def as_dict(self) -> dict[str, Any]:
        with self._lock:
            return {key: value for key, (_ts, value) in self._items.items()}

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def stats(self) -> RuntimeCacheStats:
        with self._lock:
            return RuntimeCacheStats(
                artifact_id=self.artifact_id,
                namespace=self.namespace,
                clear_group=self.clear_group,
                size=len(self._items),
                max_entries=self.max_entries,
                hits=self._hits,
                misses=self._misses,
                sets=self._sets,
            )

    def _evict_if_needed(self) -> None:
        if self.max_entries <= 0:
            return
        while len(self._items) > self.max_entries:
            self._items.popitem(last=False)


_RUNTIME_CACHES: dict[tuple[str, str], RegisteredRuntimeCache] = {}
_REGISTRY_LOCK = RLock()


def get_runtime_cache(
    artifact_id: str,
    *,
    namespace: str = "default",
    max_entries: int = 0,
) -> RegisteredRuntimeCache:
    """Restituisce una cache runtime registrata e condivisa nel processo."""

    key = (str(artifact_id or "").strip(), str(namespace or "default"))
    with _REGISTRY_LOCK:
        existing = _RUNTIME_CACHES.get(key)
        if existing is not None:
            return existing
        cache = RegisteredRuntimeCache(key[0], namespace=key[1], max_entries=max_entries)
        _RUNTIME_CACHES[key] = cache
        logger.debug("Runtime cache registrata: artifact=%s namespace=%s", key[0], key[1])
        return cache


def iter_runtime_cache_stats() -> tuple[RuntimeCacheStats, ...]:
    """Statistiche delle cache runtime attive nel processo."""

    with _REGISTRY_LOCK:
        return tuple(cache.stats() for cache in _RUNTIME_CACHES.values())


def clear_runtime_caches(*, clear_group: str | None = None) -> int:
    """Pulisce le cache runtime, opzionalmente per gruppo registry."""

    wanted_group = str(clear_group or "").strip()
    cleared = 0
    with _REGISTRY_LOCK:
        for cache in _RUNTIME_CACHES.values():
            if wanted_group and cache.clear_group != wanted_group:
                continue
            cache.clear()
            cleared += 1
    return cleared


def registered_runtime_provider_ids() -> tuple[str, ...]:
    """Artifact registry che possono ospitare adapter runtime ufficiali."""

    return tuple(
        spec.artifact_id
        for spec in iter_cache_artifact_specs()
        if spec.storage in {"process_memory_lru", "runtime_memory_plus_cache_file"}
        or spec.status == "registered_provider"
    )
