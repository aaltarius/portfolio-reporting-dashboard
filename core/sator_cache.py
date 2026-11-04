"""core/sator_cache.py — cache L3 condivisa per il motore SATOR.

`run_sator_analysis` (core/services/sator.py) e `build_rebalancing_plan`
(core/services/rebalancing.py, che internamente richiama
`run_sator_analysis` due volte) non avevano nessuna cache: venivano
ricalcolati da zero ad ogni rerun di Pianificazione (ui/pages/pianificazione.py)
e ad ogni apertura della pagina SATOR standalone (ui/form_server/sator.py),
anche quando nulla di rilevante per SATOR era cambiato (es. un salvataggio
di impostazioni non-SATOR). Root cause diagnosticata confrontando
core/cache_policy.py (nessuna voce per SATOR/Pianificazione) con
tools/cache_surface_audit.py.

Questo modulo resta fuori da core/services/: compone cache + calcolo, non
definisce formule finanziarie (mai una seconda definizione della stessa
metrica — le formule restano tutte in core/services/sator.py e
core/services/rebalancing.py, qui solo richiamate tramite builder).

La firma cache usa solo il sotto-insieme di `settings` che il motore usa
davvero (`settings["sator"]`, `settings["portfolio_objective"]`), mai
l'intero dict: un cambio di impostazioni estraneo a SATOR non deve
invalidare questa cache.
"""
from __future__ import annotations

import copy
import json
import logging
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

import pandas as pd

from core.cache_orchestrator import get_or_build_registered_artifact
from core.cache_policy import build_cache_artifact_signature
from core.services.rebalancing import build_rebalancing_plan
from core.services.sator import run_sator_analysis
from core.services.sator_frontier import build_sator_frontier


logger = logging.getLogger("portafoglio.sator_cache")


# --- Ricalcolo differito (ADR-0023) -------------------------------------------
# Con `allow_stale=True`, quando la firma cambia e in questo processo esiste gia'
# un risultato precedente per gli stessi parametri, lo si restituisce subito e il
# ricalcolo parte in un thread (una volta per firma). Al ricalcolo finito il
# risultato viene registrato in cache dal thread principale alla chiamata
# successiva. Il thread non tocca mai `st.session_state` ne' la cache pagine.

@dataclass(frozen=True)
class SatorStaleInfo:
    """Stato «dati precedenti» dell'ultima chiamata con ricalcolo differito."""

    computed_at: datetime
    recompute_running: bool


class _CacheMiss(Exception):
    pass


_LOCK = threading.RLock()
_LAST_GOOD: dict[str, tuple[Any, datetime]] = {}
_READY: dict[str, tuple[Any, datetime]] = {}
_THREADS: dict[str, threading.Thread] = {}
_FAILED: set[str] = set()
_STALE: SatorStaleInfo | None = None


def get_stale_info() -> SatorStaleInfo | None:
    """Ultimo stato «dati precedenti» registrato da una chiamata differita."""
    return _STALE


def reset_stale_info() -> None:
    global _STALE
    _STALE = None


def _reset_deferred_state() -> None:
    global _STALE
    with _LOCK:
        _LAST_GOOD.clear()
        _READY.clear()
        _THREADS.clear()
        _FAILED.clear()
        _STALE = None


def _join_background_threads(timeout: float = 10.0) -> None:
    with _LOCK:
        threads = list(_THREADS.values())
    for thread in threads:
        thread.join(timeout)


def _raise_miss() -> Any:
    raise _CacheMiss()


def _peek_artifact(artifact_id: str, signature: str) -> Any:
    """Valore gia' in cache per questa firma, oppure None (non costruisce nulla)."""
    try:
        return get_or_build_registered_artifact(artifact_id=artifact_id, signature=signature, builder=_raise_miss).value
    except _CacheMiss:
        return None


def _record_good(discriminator: str, value: Any, *, at: datetime | None = None) -> None:
    with _LOCK:
        previous = _LAST_GOOD.get(discriminator)
        if at is None and previous is not None and previous[0] is value:
            return
        _LAST_GOOD[discriminator] = (value, at or datetime.now())


def _start_background(signature: str, build_isolated: Callable[[], Any]) -> None:
    with _LOCK:
        thread = _THREADS.get(signature)
        if thread is not None and thread.is_alive():
            return

        def worker() -> None:
            try:
                value = build_isolated()
            except Exception:
                logger.warning("Ricalcolo SATOR differito non riuscito (firma %s)", signature, exc_info=True)
                with _LOCK:
                    _FAILED.add(signature)
                return
            with _LOCK:
                _READY[signature] = (value, datetime.now())

        thread = threading.Thread(target=worker, name=f"SatorDeferred-{signature[:8]}", daemon=True)
        _THREADS[signature] = thread
        thread.start()


def _deferred(
    artifact_id: str,
    signature: str,
    discriminator: str,
    build: Callable[[], Any],
    build_isolated: Callable[[], Any],
    allow_stale: bool,
) -> Any:
    global _STALE

    def synchronous() -> Any:
        value = get_or_build_registered_artifact(artifact_id=artifact_id, signature=signature, builder=build).value
        _record_good(discriminator, value)
        return value

    if not allow_stale:
        return synchronous()
    hit = _peek_artifact(artifact_id, signature)
    if hit is not None:
        _record_good(discriminator, hit)
        return hit
    with _LOCK:
        ready = _READY.pop(signature, None)
        failed = signature in _FAILED
        last = _LAST_GOOD.get(discriminator)
    if ready is not None:
        value, computed_at = ready
        get_or_build_registered_artifact(artifact_id=artifact_id, signature=signature, builder=lambda: value)
        _record_good(discriminator, value, at=computed_at)
        return value
    if last is None or failed:
        return synchronous()
    _start_background(signature, build_isolated)
    _STALE = SatorStaleInfo(computed_at=last[1], recompute_running=True)
    return last[0]


def _discriminator(artifact_id: str, inputs: dict[str, Any]) -> str:
    """Parametri della richiesta SENZA la firma dati: identifica «la stessa domanda»."""
    stable = {k: v for k, v in inputs.items() if k != "data_sig"}
    return f"{artifact_id}|{json.dumps(stable, sort_keys=True, default=str)}"


def _sator_settings_slice(settings: dict[str, Any] | None) -> dict[str, Any]:
    return dict((settings or {}).get("sator", {}) or {}) if isinstance(settings, dict) else {}


def _portfolio_objective_slice(settings: dict[str, Any] | None) -> dict[str, Any]:
    return dict((settings or {}).get("portfolio_objective", {}) or {}) if isinstance(settings, dict) else {}


def get_cached_sator_analysis(
    data: dict[str, Any],
    settings: dict[str, Any],
    *,
    budget: float,
    selected_categories: list[str] | None = None,
    include_fee_instruments: bool = True,
    data_sig: str = "",
    allow_stale: bool = False,
) -> dict[str, Any]:
    """Wrapper cacheato di `run_sator_analysis`.

    Con `allow_stale=True` vale il ricalcolo differito (vedi `_deferred`).
    """

    inputs = {
        "data_sig": str(data_sig or ""),
        "sator_settings": _sator_settings_slice(settings),
        "budget": float(budget),
        "selected_categories": tuple(selected_categories or ()),
        "include_fee_instruments": bool(include_fee_instruments),
    }
    signature = build_cache_artifact_signature("sator.ranking_cache", inputs=inputs)

    def run(d, s):
        return run_sator_analysis(
            d,
            s,
            budget=budget,
            selected_categories=selected_categories,
            include_fee_instruments=include_fee_instruments,
        )

    return _deferred(
        "sator.ranking_cache",
        signature,
        _discriminator("sator.ranking_cache", inputs),
        lambda: run(data, settings),
        lambda: run(copy.deepcopy(data), copy.deepcopy(settings)),
        allow_stale,
    )


def get_cached_rebalancing_plan(
    data: dict[str, Any],
    settings: dict[str, Any],
    state_df: pd.DataFrame,
    current_mix: dict[str, float],
    portfolio_value: float,
    *,
    exclude_tickers: frozenset[str] = frozenset(),
    data_sig: str = "",
    allow_stale: bool = False,
) -> dict[str, dict[str, Any]]:
    """Wrapper cacheato di `build_rebalancing_plan` (ricalcolo differito con `allow_stale`)."""

    inputs = {
        "data_sig": str(data_sig or ""),
        "sator_settings": _sator_settings_slice(settings),
        "portfolio_objective": _portfolio_objective_slice(settings),
        "exclude_tickers": tuple(sorted(str(t) for t in (exclude_tickers or ()))),
    }
    signature = build_cache_artifact_signature("sator.rebalancing_plan_cache", inputs=inputs)

    def run(d, s, df, mix):
        return build_rebalancing_plan(d, s, df, mix, portfolio_value, exclude_tickers=exclude_tickers)

    return _deferred(
        "sator.rebalancing_plan_cache",
        signature,
        _discriminator("sator.rebalancing_plan_cache", inputs),
        lambda: run(data, settings, state_df, current_mix),
        lambda: run(copy.deepcopy(data), copy.deepcopy(settings), state_df.copy(), dict(current_mix)),
        allow_stale,
    )


def get_cached_sator_frontier(
    data: dict[str, Any],
    settings: dict[str, Any],
    *,
    precomputed_result: dict[str, Any],
    lookback_months: int,
    manual_slider_pct: float,
    exclude_tickers: frozenset[str] = frozenset(),
    data_sig: str = "",
    allow_stale: bool = False,
) -> Any:
    """Wrapper cacheato di `build_sator_frontier`. `precomputed_result` non
    entra nella firma: deriva da `data_sig` + `settings["sator"]` (stessa
    firma di `get_cached_sator_analysis` col budget di default)."""

    inputs = {
        "data_sig": str(data_sig or ""),
        "sator_settings": _sator_settings_slice(settings),
        "lookback_months": int(lookback_months),
        "manual_slider_pct": round(float(manual_slider_pct), 4),
        "exclude_tickers": tuple(sorted(str(t) for t in (exclude_tickers or ()))),
    }
    signature = build_cache_artifact_signature("sator.frontier_cache", inputs=inputs)

    def run(d, s, pre):
        return build_sator_frontier(
            d,
            s,
            precomputed_result=pre,
            lookback_months=lookback_months,
            manual_slider_pct=manual_slider_pct,
            exclude_tickers=exclude_tickers,
        )

    return _deferred(
        "sator.frontier_cache",
        signature,
        _discriminator("sator.frontier_cache", inputs),
        lambda: run(data, settings, precomputed_result),
        lambda: run(copy.deepcopy(data), copy.deepcopy(settings), copy.deepcopy(precomputed_result)),
        allow_stale,
    )
