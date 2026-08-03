"""core/frozen_analysis_cache.py — Cache condivisa per analisi "congelate"
(Benchmark, Accumuli).

Le due sezioni Cruscotti/Benchmark e Cruscotti/Accumuli condividono lo
stesso pattern: un'analisi pesante viene calcolata solo su richiesta
esplicita dell'utente e "congelata" (sessione + disco) finché non viene
rigenerata a mano; le figure derivate da quell'analisi vengono a loro
volta cacheate in sessione con una piccola LRU. Questo modulo estrae
quella infrastruttura comune — le pagine chiamanti restano responsabili
solo dei testi/etichette e degli allowlist di firma specifici di
ciascuna analisi (vedi ui/pages/cruscotti_benchmark.py e
ui/pages/cruscotti_accumuli.py).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

import pandas as pd
import streamlit as st

from core.cache_orchestrator import (
    get_registered_figure_cache,
    load_registered_analytics_entry,
    store_registered_analytics_entry,
)
from core.figure_cache import CachingStrategy
from core.render_profiler import profile_step


def prune_cache_items(items: dict[str, Any], max_items: int) -> None:
    """Mantiene contenuta una cache di sessione a dimensione fissa (elimina le voci più vecchie per ordine di inserimento)."""
    if len(items) <= max_items:
        return
    for old_key in list(items.keys())[: max(0, len(items) - max_items)]:
        items.pop(old_key, None)


def cached_render_value(
    cache_state_key: str,
    key: str,
    builder: Callable[[], Any],
    *,
    page_label: str,
    label: str,
    max_items: int,
    count: int | None = None,
) -> Any:
    """Cache di sessione per valori (tipicamente figure Plotly) già costruiti da un'analisi congelata."""
    cache = st.session_state.setdefault(cache_state_key, {})
    if not isinstance(cache, dict):
        cache = {}
        st.session_state[cache_state_key] = cache
    if key in cache:
        with profile_step(page_label, f"cache hit figura {label}", count=count):
            return cache[key]
    with profile_step(page_label, f"build figura {label}", count=count):
        value = builder()
    cache[key] = value
    prune_cache_items(cache, max_items)
    return value


def cached_render_figure(
    *,
    chart_id: str,
    data_sig: str,
    theme_sig: str,
    charts_settings_sig: str,
    builder: Callable[[], Any],
    page_label: str,
    label: str,
    count: int | None = None,
    extra_params: dict[str, Any] | None = None,
    strategy: str = CachingStrategy.HYBRID,
) -> Any:
    """Cache persistente per figure derivate da analisi congelate.

    Le analisi Benchmark/Accumuli restano congelate e rigenerabili solo da
    pulsante; le figure derivate, pero', devono seguire la FigureCache comune
    invece di una cache solo di sessione, altrimenti dopo reload/process reset
    vengono ricostruite pur avendo lo stesso payload.
    """

    def _profiled_builder() -> Any:
        with profile_step(page_label, f"build figura {label}", count=count):
            return builder()

    params = dict(extra_params or {})
    params.setdefault("scope", label)
    return get_registered_figure_cache().get_or_build(
        chart_id=chart_id,
        data_sig=str(data_sig or "no-data-sig"),
        theme_sig=str(theme_sig or "no-theme-sig"),
        charts_settings_sig=str(charts_settings_sig or "no-chart-settings-sig"),
        builder=_profiled_builder,
        page_mode="FrozenAnalysis",
        extra_params=params,
        strategy=strategy,
    )


def small_signature_part(value: Any, dict_keys: frozenset[str]) -> Any:
    """Riduce oggetti voluminosi a una firma leggera e serializzabile.

    dict_keys: per i dict, solo queste chiavi vengono incluse nella firma
    — allowlist specifica di ciascuna analisi (diversa fra Benchmark e
    Accumuli, non unificare le due allowlist: rappresentano campi
    logicamente diversi)."""
    if isinstance(value, pd.DataFrame):
        if value.empty:
            return {"rows": 0, "cols": list(value.columns)}
        return {
            "rows": int(len(value)),
            "cols": list(value.columns),
            "first_index": str(value.index[0]),
            "last_index": str(value.index[-1]),
        }
    if isinstance(value, dict):
        return {str(k): small_signature_part(v, dict_keys) for k, v in value.items() if k in dict_keys}
    if isinstance(value, (list, tuple)):
        if not value:
            return {"len": 0}
        return {"len": len(value), "first": str(value[0])[:80], "last": str(value[-1])[:80]}
    return value


def get_frozen_analysis_cache(cache_state_key: str, payload_type: str, signature: str) -> tuple[dict[str, Any] | None, bool]:
    """Restituisce (entry, stale) per un'analisi congelata, prima sessione poi disco."""
    cache = st.session_state.setdefault(cache_state_key, {"items": {}, "latest_key": ""})
    if not isinstance(cache, dict):
        cache = {"items": {}, "latest_key": ""}
        st.session_state[cache_state_key] = cache
    items = cache.setdefault("items", {})
    if not isinstance(items, dict):
        items = {}
        cache["items"] = items
    if signature in items and isinstance(items[signature], dict):
        items[signature].setdefault("cache_source", "session")
        return items[signature], False

    disk_entry, disk_stale, disk_source = load_registered_analytics_entry(
        payload_type=payload_type,
        signature=signature,
    )
    if isinstance(disk_entry, dict):
        disk_signature = str(disk_entry.get("signature") or signature)
        disk_entry.setdefault("cache_source", disk_source)
        items[disk_signature] = disk_entry
        cache["latest_key"] = disk_signature
        return disk_entry, disk_stale

    latest_key = str(cache.get("latest_key") or "")
    latest = items.get(latest_key)
    if isinstance(latest, dict):
        latest.setdefault("cache_source", "session_latest")
        return latest, True
    return None, False


def store_frozen_analysis_cache(
    cache_state_key: str,
    payload_type: str,
    signature: str,
    value: Any,
    *,
    max_session_items: int = 4,
    max_disk_entries: int = 6,
) -> dict[str, Any]:
    """Salva un'analisi congelata in sessione + disco sotto il campo "payload"."""
    cache = st.session_state.setdefault(cache_state_key, {"items": {}, "latest_key": ""})
    items = cache.setdefault("items", {})
    entry = {
        "signature": signature,
        "created_at": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "payload": value,
        "cache_source": "session+disk",
    }
    items[signature] = entry
    cache["latest_key"] = signature
    store_registered_analytics_entry(
        payload_type=payload_type,
        signature=signature,
        entry=entry,
        max_entries=max_disk_entries,
    )
    if len(items) > max_session_items:
        for old_key in list(items.keys())[:-max_session_items]:
            items.pop(old_key, None)
    return entry
