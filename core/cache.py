"""
core/cache.py — invalidazione controllata cache Streamlit/pipeline portfolio.

Obiettivo: evitare st.cache_data.clear() globale nelle pagine operative.
Le modifiche ai dati aggiornano una firma in session_state; app.py la include
nella signature dell'orchestrazione cacheata, rigenerando solo il payload portfolio.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any

import streamlit as st

logger = logging.getLogger("portafoglio.core.cache")

_CACHE_DECISION_KEY = "_portfolio_last_cache_decision"
_CACHE_MUTATION_DETAILS_KEY = "_portfolio_last_mutation_details"


def _safe_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, set):
        return sorted(value)
    return [value]


def _active_dirty_names(dirty: dict[str, Any]) -> list[str]:
    if not isinstance(dirty, dict):
        return []
    return sorted(str(k) for k, v in dirty.items() if bool(v))


def _get_last_mutation_details() -> dict[str, Any]:
    try:
        details = st.session_state.get(_CACHE_MUTATION_DETAILS_KEY, {})
        return details if isinstance(details, dict) else {}
    except Exception:
        return {}


def set_last_mutation_details(details: dict[str, Any] | None) -> None:
    """Memorizza dettagli diagnostici dell'ultima mutazione prima dell'invalidazione.

    Non cambia cache o dati: serve solo al render log per spiegare perche' una
    cache e' stata invalidata e quali oggetti erano realmente coinvolti.
    """
    try:
        st.session_state[_CACHE_MUTATION_DETAILS_KEY] = dict(details or {})
    except Exception:
        return


def _dependency_matrix_for_dirty(dirty: dict[str, Any]) -> list[dict[str, Any]]:
    dirty = dirty if isinstance(dirty, dict) else {}
    rows = [
        ("quotes_bundle", ["quotes", "prices"], "Pagina Quotazioni, tabelle diagnostiche e grafici strumenti"),
        ("portfolio_runtime", ["portfolio", "prices"], "Valutazioni, P/L, allocazione e ultima giornata"),
        ("cruscotti_category_dashboard", ["cruscotti", "prices"], "Dashboard categorie, temporali, drawdown e tabelle P/L horizon"),
        ("cruscotti_analitica", ["cruscotti", "reports", "prices"], "Figure analitiche avanzate e dataset sintetico"),
        ("cruscotti_benchmark", ["benchmark_portfolio", "benchmark_matrix", "prices"], "Confronto portfolio/benchmark e matrice compatibilita'"),
        ("cruscotti_accumuli", ["accumuli", "prices"], "Analisi PAC/accumuli e grafici dettaglio"),
        ("summary_reports", ["reports", "portfolio", "prices"], "Summary payload e report"),
        ("data_management", ["data_management"], "Gestione dati, backup, import e diagnostica archivio"),
        ("settings_runtime", ["settings"], "Tema, preferenze UI e configurazioni"),
    ]
    plan_rows: list[dict[str, Any]] = []
    for name, triggers, desc in rows:
        hits = [flag for flag in triggers if bool(dirty.get(flag))]
        plan_rows.append({
            "cache": name,
            "invalidate": bool(hits),
            "trigger_flags": hits,
            "description": desc,
        })
    return plan_rows


def _build_invalidation_decision(
    *,
    reason: str,
    token: int,
    force_reload: bool,
    scenario: str,
    render_scope: str,
    dirty: dict[str, Any],
    invalidated: bool,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    details = dict(details or _get_last_mutation_details() or {})
    dirty = dirty if isinstance(dirty, dict) else {}
    changed_tickers = _safe_list(details.get("changed_tickers"))
    changed_categories = _safe_list(details.get("changed_categories"))
    changed_count = int(details.get("changed_count", len(changed_tickers)) or 0)
    current_scope = str(render_scope or "")
    scope_warning = ""
    if current_scope == "current_page_only":
        scope_warning = (
            "render_scope=current_page_only rilevato: con st.tabs passive puo' essere incoerente. "
            "Le nuove invalidazioni usano full_tabs e granularita' sui dirty flags."
        )
    active_dirty = _active_dirty_names(dirty)
    decision = {
        "version": "invalidation-plan-v1",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "reason": str(reason or ""),
        "invalidated": bool(invalidated),
        "token": int(token or 0),
        "force_reload": bool(force_reload),
        "scenario": str(scenario or ""),
        "render_scope_requested": current_scope,
        "render_scope_warning": scope_warning,
        "dirty_flags": dict(dirty),
        "dirty_active": active_dirty,
        "mutation_details": details,
        "changed_tickers": changed_tickers,
        "changed_categories": changed_categories,
        "changed_count": changed_count,
        "dependency_plan": _dependency_matrix_for_dirty(dirty),
        "figure_session_clear": False,
        "notes": [],
    }
    if invalidated and changed_count and len(active_dirty) >= 6:
        decision["notes"].append(
            "Invalidazione ampia: una variazione puntuale sta attivando molti dirty_flags; "
            "valutare granularita' per categoria/strumento."
        )
    if invalidated and bool(dirty.get("accumuli")) and changed_categories and not any(str(c).upper() in {"FND", "ETF"} for c in changed_categories):
        decision["notes"].append(
            "Accumuli invalidati anche se le categorie cambiate non sembrano PAC/FND/ETF: verificare dipendenza reale."
        )
    if invalidated and bool(dirty.get("benchmark_matrix")) and not bool(details.get("benchmarks_refreshed")):
        decision["notes"].append(
            "benchmark_matrix invalidata senza refresh benchmark dichiarato: verificare se serve davvero."
        )
    if not invalidated:
        decision["notes"].append("Nessuna invalidazione dati richiesta: dovrebbe aggiornarsi solo la UI/log diagnostico.")
    return decision


def record_cache_decision(
    reason: str,
    *,
    details: dict[str, Any] | None = None,
    invalidated: bool = False,
    token: int = 0,
    force_reload: bool = False,
    scenario: str = "",
    render_scope: str = "",
    dirty_flags: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Registra una decisione cache diagnostica, anche quando non si invalida nulla."""
    decision = _build_invalidation_decision(
        reason=reason,
        token=token,
        force_reload=force_reload,
        scenario=scenario,
        render_scope=render_scope,
        dirty=dirty_flags or {},
        invalidated=invalidated,
        details=details,
    )
    try:
        st.session_state[_CACHE_DECISION_KEY] = decision
    except Exception:
        pass
    try:
        logger.info(
            "Cache decision: reason=%s invalidated=%s scenario=%s render_scope=%s dirty=%s changed=%s categories=%s notes=%s",
            decision.get("reason"),
            decision.get("invalidated"),
            decision.get("scenario"),
            decision.get("render_scope_requested"),
            ",".join(decision.get("dirty_active") or []) or "none",
            ",".join(str(x) for x in (decision.get("changed_tickers") or [])) or "none",
            ",".join(str(x) for x in (decision.get("changed_categories") or [])) or "none",
            " | ".join(decision.get("notes") or []) or "n/d",
        )
    except Exception:
        pass
    return decision


def _infer_dirty_for_quote_refresh(details: dict[str, Any]) -> dict[str, bool]:
    """Dirty flags granulari per refresh quotazioni.

    Il refresh prezzi cambia lo stato di mercato, non necessariamente ogni
    sotto-sistema. Questa funzione usa i dettagli reali della mutazione per
    evitare invalidazioni puramente difensive (es. benchmark_matrix quando i
    benchmark non sono stati aggiornati).
    """
    changed_tickers = _safe_list(details.get("changed_tickers"))
    changed_categories = {str(c or "").upper() for c in _safe_list(details.get("changed_categories")) if str(c or "").strip()}
    benchmarks_refreshed = bool(details.get("benchmarks_refreshed"))
    has_price_change = bool(changed_tickers) or bool(details.get("material_change"))

    dirty = {
        "portfolio": has_price_change,
        "prices": has_price_change,
        "quotes": True,  # il quotes_log/UI quotazioni si aggiorna comunque nel flusso di refresh
        "cruscotti": has_price_change,
        "benchmark_portfolio": has_price_change,
        # La matrice assegnazioni benchmark dipende da registry/componenti, non dal solo prezzo.
        "benchmark_matrix": benchmarks_refreshed,
        # Accumuli/PAC dipendono dai prezzi solo se le categorie cambiate possono comparire nei flussi di acquisto.
        # In assenza di categorie diagnostiche affidabili, resta prudenziale su price_change.
        "accumuli": has_price_change and (not changed_categories or bool(changed_categories.intersection({"FND", "ETF", "ETC", "ALTRO"}))),
        "reports": has_price_change,
        "sator": False,
        "settings": False,
        "data_management": False,
    }
    return dirty


def _classify_invalidation_reason(reason: str, details: dict[str, Any] | None = None) -> tuple[str, str, dict[str, bool]]:
    """Classifica il tipo di mutazione e i dirty flags reali.

    Nota: la navigazione principale usa st.tabs passive, quindi il render effettivo
    del run corrente e' full_tabs. Non richiediamo piu' current_page_only: era una
    fonte di diagnostica fuorviante e di potenziali tab vuote.
    """
    r = str(reason or "").lower()
    details = dict(details or {})

    dirty = {
        "portfolio": False,
        "prices": False,
        "quotes": False,
        "cruscotti": False,
        "benchmark_portfolio": False,
        "benchmark_matrix": False,
        "accumuli": False,
        "reports": False,
        "sator": False,
        "settings": False,
        "data_management": False,
    }

    if any(k in r for k in ("operazione", "operazioni", "carrello", "movimento", "evento", "cedola", "dividendo")):
        dirty.update({
            "portfolio": True,
            "cruscotti": True,
            "benchmark_portfolio": True,
            "accumuli": True,
            "reports": True,
        })
        return "post_operation_save", "full_tabs", dirty

    if any(k in r for k in ("quotaz", "prezz", "price", "import quot", "storico")):
        return "quote_refresh", "full_tabs", _infer_dirty_for_quote_refresh(details)

    if "sator" in r or "pianificazione" in r or "scenario" in r:
        dirty.update({"sator": True, "reports": True})
        return "sator_workflow", "full_tabs", dirty

    if "snapshot" in r or "confronto" in r:
        dirty.update({"reports": True})
        return "comparison_update", "full_tabs", dirty

    if "impostaz" in r or "settings" in r:
        dirty.update({"settings": True, "cruscotti": True, "reports": True})
        return "settings_update", "full_tabs", dirty

    if any(k in r for k in ("backup", "ripristino", "bonifica", "strumento", "sidebar", "dati")):
        dirty.update({
            "portfolio": True,
            "quotes": True,
            "cruscotti": True,
            "benchmark_portfolio": True,
            "benchmark_matrix": True,
            "accumuli": True,
            "reports": True,
            "data_management": True,
        })
        return "post_data_change", "full_tabs", dirty

    dirty.update({"portfolio": True, "cruscotti": True, "reports": True})
    return "post_data_change", "full_tabs", dirty

def _set_next_rerun_context(reason: str, token: int) -> None:
    details = _get_last_mutation_details()
    scenario, render_scope, dirty = _classify_invalidation_reason(reason, details)

    # Pagina sorgente della mutazione.
    #
    # In modalita full-tabs Streamlit esegue tutti i tab; durante il rendering
    # di una pagina runtime_pages aggiorna current_page_id/current_page_index.
    # Se l'azione salva dati e chiama st.rerun(), al run successivo non possiamo
    # affidarci ad active_tab, che spesso torna alla pagina predefinita.
    # Memorizziamo quindi esplicitamente la pagina che ha generato la mutazione,
    # così il rerun operativo leggero resta sulla pagina corretta.
    origin_page_id = str(st.session_state.get("current_page_id") or "").strip()
    try:
        origin_page_index = int(st.session_state.get("current_page_index", 0) or 0)
    except Exception:
        origin_page_index = 0

    st.session_state["_portfolio_rerun_reason"] = str(reason or "invalidazione dati")
    st.session_state["_portfolio_rerun_scenario"] = scenario
    st.session_state["_portfolio_next_render_scope"] = render_scope
    st.session_state["_portfolio_dirty_flags"] = dirty
    st.session_state["_portfolio_mutation_token"] = token
    st.session_state["_portfolio_rerun_origin_page_id"] = origin_page_id
    st.session_state["_portfolio_rerun_origin_page_index"] = origin_page_index


def consume_next_render_scope(default: str = "full_tabs") -> dict[str, Any]:
    """Consuma il contesto one-shot del prossimo rerun.

    App.py lo usa dopo azioni operative: il primo rerun successivo viene reso
    leggero; il run seguente torna alla modalita normale.
    """
    # Tutto il contesto operativo è one-shot. In precedenza veniva consumato solo
    # `_portfolio_next_render_scope`, mentre reason/scenario/dirty restavano in
    # session_state: al rerun successivo poteva comparire la combinazione incoerente
    # `operational_reason` presente ma `render_scope=full_tabs`, che forza il render
    # completo dopo una mutazione. Consumiamo quindi l'intero pacchetto insieme.
    raw_scope = st.session_state.pop("_portfolio_next_render_scope", None)
    reason = str(st.session_state.pop("_portfolio_rerun_reason", "") or "")
    scenario = str(st.session_state.pop("_portfolio_rerun_scenario", "") or "")
    dirty = st.session_state.pop("_portfolio_dirty_flags", {})
    if not isinstance(dirty, dict):
        dirty = {}
    if raw_scope is None and reason:
        # Guardia per stati lasciati da versioni precedenti: se c'è un motivo
        # operativo, non può mai partire un full-tabs automatico.
        scope = "current_page_only"
    else:
        scope = str(raw_scope or default or "full_tabs")
    origin_page_id = str(st.session_state.pop("_portfolio_rerun_origin_page_id", "") or "").strip()
    try:
        origin_page_index = int(st.session_state.pop("_portfolio_rerun_origin_page_index", 0) or 0)
    except Exception:
        origin_page_index = 0
    return {
        "render_scope": scope,
        "reason": reason,
        "scenario": scenario,
        "dirty_flags": dict(dirty),
        "origin_page_id": origin_page_id,
        "origin_page_index": origin_page_index,
    }


def invalidate_portfolio_cache(reason: str = "", *, force_reload: bool = True) -> int:
    """
    Invalida in modo mirato la pipeline dati del portafoglio.

    Non svuota tutta la cache Streamlit. Aggiorna invece un token stabile in
    session_state che app.py usa nella signature dell'orchestrazione cacheata.
    Con force_reload=True chiede anche allo StateManager di ricaricare i JSON
    al rerun successivo, utile dopo save_data/save_settings/save_snapshots.
    """
    token = time.time_ns()
    st.session_state["_portfolio_cache_bust"] = token
    st.session_state["_portfolio_cache_reason"] = str(reason or "invalidazione dati")
    st.session_state["_profiling_force_data_change"] = True
    st.session_state.pop("_profiling_scenario_current", None)
    _set_next_rerun_context(str(reason or "invalidazione dati"), token)
    if force_reload:
        st.session_state["_force_reload"] = st.session_state.get("_force_reload", 0) + 1

    decision = record_cache_decision(
        str(reason or "invalidazione dati"),
        details=_get_last_mutation_details(),
        invalidated=True,
        token=token,
        force_reload=force_reload,
        scenario=str(st.session_state.get("_portfolio_rerun_scenario") or ""),
        render_scope=str(st.session_state.get("_portfolio_next_render_scope") or ""),
        dirty_flags=st.session_state.get("_portfolio_dirty_flags") or {},
    )

    # Non svuotiamo piu' globalmente la cache figure di sessione.
    # Le figure obsolete non vengono riusate perche' la loro firma contiene data_sig/theme/settings;
    # cancellarle tutte trasformava ogni piccolo refresh quote in un cache_miss globale.
    logger.debug("Figure session cache preservata: invalidazione affidata alle firme dei singoli grafici")

    logger.info(
        "Invalidazione portfolio cache: reason=%s token=%s force_reload=%s scenario=%s render_scope=%s origin_page=%s dirty=%s changed=%s",
        reason,
        token,
        force_reload,
        st.session_state.get("_portfolio_rerun_scenario"),
        st.session_state.get("_portfolio_next_render_scope"),
        st.session_state.get("_portfolio_rerun_origin_page_id"),
        ",".join(decision.get("dirty_active") or []) or "none",
        ",".join(str(x) for x in (decision.get("changed_tickers") or [])) or "none",
    )
    return token


def get_portfolio_cache_bust() -> int:
    """Restituisce il token di invalidazione corrente per la firma cache."""
    try:
        return int(st.session_state.get("_portfolio_cache_bust", 0) or 0)
    except Exception:
        return 0
