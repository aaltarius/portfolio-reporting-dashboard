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

from typing import Any

import pandas as pd

from core.cache_orchestrator import get_or_build_registered_artifact
from core.cache_policy import build_cache_artifact_signature
from core.services.rebalancing import build_rebalancing_plan
from core.services.sator import run_sator_analysis


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
) -> dict[str, Any]:
    """Wrapper cacheato di `run_sator_analysis`."""

    signature = build_cache_artifact_signature(
        "sator.ranking_cache",
        inputs={
            "data_sig": str(data_sig or ""),
            "sator_settings": _sator_settings_slice(settings),
            "budget": float(budget),
            "selected_categories": tuple(selected_categories or ()),
            "include_fee_instruments": bool(include_fee_instruments),
        },
    )
    artifact = get_or_build_registered_artifact(
        artifact_id="sator.ranking_cache",
        signature=signature,
        builder=lambda: run_sator_analysis(
            data,
            settings,
            budget=budget,
            selected_categories=selected_categories,
            include_fee_instruments=include_fee_instruments,
        ),
    )
    return artifact.value


def get_cached_rebalancing_plan(
    data: dict[str, Any],
    settings: dict[str, Any],
    state_df: pd.DataFrame,
    current_mix: dict[str, float],
    portfolio_value: float,
    *,
    exclude_tickers: frozenset[str] = frozenset(),
    data_sig: str = "",
) -> dict[str, dict[str, Any]]:
    """Wrapper cacheato di `build_rebalancing_plan`."""

    signature = build_cache_artifact_signature(
        "sator.rebalancing_plan_cache",
        inputs={
            "data_sig": str(data_sig or ""),
            "sator_settings": _sator_settings_slice(settings),
            "portfolio_objective": _portfolio_objective_slice(settings),
            "exclude_tickers": tuple(sorted(str(t) for t in (exclude_tickers or ()))),
        },
    )
    artifact = get_or_build_registered_artifact(
        artifact_id="sator.rebalancing_plan_cache",
        signature=signature,
        builder=lambda: build_rebalancing_plan(
            data,
            settings,
            state_df,
            current_mix,
            portfolio_value,
            exclude_tickers=exclude_tickers,
        ),
    )
    return artifact.value
