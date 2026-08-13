"""
Sestante — Dashboard Professionale v4.5
Entry point: Clean orchestrator (~200 lines)
- Load data from storage
- Call services to pre-compute all page data
- Populate PageContext with results
- Call pure render functions for selected page
"""
import hashlib
import json
import logging
import os
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Any

import streamlit as st
import pandas as pd
from types import SimpleNamespace
from datetime import date

_APP_RUN_STARTED_AT = time.perf_counter()

# === RESET CACHE STREAMLIT (solo se richiesto) ===
# Non svuotare cache a ogni rerun: Streamlit rilancia app.py a ogni interazione.
# Per forzare un reset manuale usare st.session_state["_clear_streamlit_cache"] = True
# oppure avviare con PORTFOLIO_CLEAR_CACHE_ON_START=1.
if st.session_state.pop("_clear_streamlit_cache", False) or os.getenv("PORTFOLIO_CLEAR_CACHE_ON_START") == "1":
    st.cache_resource.clear()
    st.cache_data.clear()

# === INIT SESSION STATE ===
if 'active_tab' not in st.session_state:
    st.session_state.active_tab = 0


def _begin_sestante_session_run() -> int:
    """Registra un solo progressivo per script run, prima del render delle tab."""
    try:
        if not st.session_state.get("_sestante_session_token"):
            st.session_state["_sestante_session_token"] = uuid.uuid4().hex[:10]
        run_ordinal = int(st.session_state.get("_sestante_session_run_ordinal", 0) or 0) + 1
        st.session_state["_sestante_session_run_ordinal"] = run_ordinal
        return run_ordinal
    except Exception:
        return 0


_CURRENT_SESSION_RUN_ORDINAL = _begin_sestante_session_run()

# === IMPORTS ===
from persistence.storage import (
    APP_VERSION, SCHEMA_VERSION, load_quotes_log, _data_mtime, load_settings,
    apply_privacy_filter,
)
from core.asset_categories import get_selected_category_codes
from core.cache_signatures import build_portfolio_data_signature, build_portfolio_signature_components, theme_signature
from core.state import StateManager
from core.cache import get_portfolio_cache_bust, consume_next_render_scope
from core.cache_policy import build_cache_artifact_signature
from core.cache_orchestrator import get_or_build_registered_artifact
from core.settings_profiles import (
    get_calculations_settings,
    get_pre_render_settings,
    get_runtime_ui_settings,
    get_ui_preferences,
    resolve_figure_cache_strategy,
)
from core.portfolio_metrics import (
    calcola_flussi_capitale,
    calcola_kpi_principali,
    calcola_total_return,
)
from core.logging_utils import configure_logging, get_log_file_path, resolve_log_level
from core.quotes_runtime import build_quotes_refresh_df
from core.services import get_quotazioni_stats
from ui.theme import get_theme_context, init_plotly_template, inject_theme_styles
from ui.styles import inject_app_styles, inject_layout_js
from ui.runtime_context import build_runtime_context_data
from ui.context_refresh import refresh_volatile_ctx_fields
from ui.formatting import fmtd, fmtds, fmt_dt_it
from ui.runtime_pages import PageDef, render_dashboard_tabs, trigger_tab_navigation
from ui.sidebar import render_sidebar
from ui.i18n import t
from ui.pages.overview import render_overview
from ui.pages.home import render_home
from ui.pages.quotazioni import render_quotazioni
from ui.pages.cruscotti import render_cruscotti
from ui.pages.mercati import render_mercati
from ui.pages.operazioni import render_operazioni
from ui.pages.summary import render_summary
from ui.pages.confronto import render_confronto
from ui.pages.pianificazione import render_pianificazione
from ui.pages.ai_page import render_ai_page
from ui.pages.impostazioni import render_impostazioni
from ui.pages.gestione_dati import render_gestione_dati
from ui.charts.settings import get_chart_setting
from ui.charts.streamlit_runtime import bind_safe_plotly_chart, reset_plotly_auto_key_counter
from ui.notifications import flush_toasts




def _shutdown_streamlit_server(delay_seconds: float = 1.25) -> None:
    """Arresta realmente il processo Streamlit locale dopo un breve ritardo.

    Streamlit non espone una API pubblica e stabile per chiudere il server dal front-end.
    Per una dashboard locale, la soluzione più affidabile è terminare il processo Python
    dopo avere renderizzato una schermata di conferma. Il ritardo lascia al browser il tempo
    di ricevere l'ultimo frame della pagina.
    """
    if os.getenv("PORTFOLIO_TESTING") == "1":
        return

    def _exit_process() -> None:
        os._exit(0)

    timer = threading.Timer(delay_seconds, _exit_process)
    timer.daemon = True
    timer.start()


def _render_shutdown_dashboard_screen() -> None:
    """Schermata finale prima dell'arresto reale del server Streamlit."""
    if not st.session_state.get("_portfolio_shutdown_timer_started", False):
        st.session_state["_portfolio_shutdown_timer_started"] = True
        _shutdown_streamlit_server()

    st.markdown("""
    <div class="shutdown-shell">
        <div class="shutdown-panel">
            <div class="shutdown-mark">S</div>
            <div class="shutdown-content">
                <div class="shutdown-kicker">SESTANTE</div>
                <div class="shutdown-title">Dashboard in chiusura</div>
                <div class="shutdown-sub">
                    Il server Streamlit locale verrà arrestato tra pochi istanti.
                    Dopo la chiusura puoi chiudere questa scheda del browser.
                </div>
                <div class="shutdown-footer">
                    <span class="shutdown-pill">Server in arresto</span>
                    <span class="shutdown-command">Per riaprire: streamlit run app.py</span>
                </div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    st.stop()


# === TYPOGRAPHY INJECTION ===
def _inject_typography_css(settings: dict) -> None:
    """Inject dynamic CSS for font sizes based on settings."""
    typo = settings.get("appearance", {}).get("typography", {})
    titles_size = typo.get("titles", "1.4rem")
    subtitles_size = typo.get("subtitles", "1.1rem")
    body_size = typo.get("body", "0.95rem")
    caption_size = typo.get("caption", "0.85rem")

    css = f"""
    <style>
    h1, h2 {{ font-size: {titles_size} !important; }}
    h3 {{ font-size: {subtitles_size} !important; }}
    [data-testid="stAppViewContainer"] p,
    [data-testid="stAppViewContainer"] li,
    [data-testid="stAppViewContainer"] label,
    [data-testid="stAppViewContainer"] input,
    [data-testid="stAppViewContainer"] textarea,
    [data-testid="stAppViewContainer"] .stMarkdown,
    [data-testid="stAppViewContainer"] .stRadio,
    [data-testid="stAppViewContainer"] .stCheckbox,
    [data-testid="stAppViewContainer"] .stSelectbox,
    [data-testid="stAppViewContainer"] .stMultiSelect {{
        font-size: {body_size} !important;
    }}
    .caption, small, .text-caption, [data-testid="caption"], [data-testid="stCaptionContainer"] {{
        font-size: {caption_size} !important;
    }}
    </style>
    """
    st.markdown(css, unsafe_allow_html=True)


# === SETUP ===
st.set_page_config(page_title="Sestante", page_icon="📊", layout="wide")

# Load settings and inject typography CSS
settings = load_settings()
_inject_typography_css(settings)

_initial_log_level = resolve_log_level(
    ((settings.get("ui_preferences", {}) or {}).get("log_level", "INFO")),
)
app_logger = configure_logging(level=_initial_log_level)
init_plotly_template()
inject_theme_styles()
theme = get_theme_context()
inject_app_styles()
inject_layout_js()
flush_toasts()
if not hasattr(st, "_portfolio_orig_plotly_chart"):
    st._portfolio_orig_plotly_chart = st.plotly_chart
st._portfolio_safe_plotly_chart = bind_safe_plotly_chart(
    get_chart_setting=get_chart_setting,
    orig_plotly_chart=st._portfolio_orig_plotly_chart,
    fallback_plotly_chart=st._portfolio_orig_plotly_chart,
)
if st.plotly_chart is not st._portfolio_safe_plotly_chart:
    st.plotly_chart = st._portfolio_safe_plotly_chart
reset_plotly_auto_key_counter()
app_logger.info("Applicazione avviata")
app_logger.info("File di log attivo: %s", get_log_file_path(app_logger))
app_logger.info("Working directory Streamlit: %s", os.getcwd())


@contextmanager
def _logged_app_phase(name: str, **details: Any):
    """Logga le macro-fasi del rerun senza alterare il comportamento Streamlit."""
    detail_text = " ".join(f"{key}={value}" for key, value in details.items() if value not in (None, ""))
    suffix = f" {detail_text}" if detail_text else ""
    t0 = time.perf_counter()
    app_logger.info("[APP_PHASE] start %s%s", name, suffix)
    try:
        yield
    except Exception:
        app_logger.exception("[APP_PHASE] error %s elapsed=%.3fs%s", name, time.perf_counter() - t0, suffix)
        raise
    else:
        app_logger.info("[APP_PHASE] end %s elapsed=%.3fs%s", name, time.perf_counter() - t0, suffix)


# === FORM SERVER (operazioni senza rerun) ===
@st.cache_resource
def _start_form_server():
    from ui.form_server import start_form_server
    start_form_server()
    return True
with _logged_app_phase("form_server_start"):
    _start_form_server()


# === INITIALIZE STATE ===
# Bump obbligatorio ad ogni cambio di schema/logica nella pipeline
# derived-runtime (core/state.py, core/finance.py e chiamanti a valle):
# questa stringa e' sia la chiave di @st.cache_resource su get_state_manager
# (forza una nuova istanza StateManager, azzerando la sua cache interna in
# memoria) sia un componente di _portfolio_semantic_signature (forza il
# rebuild completo di runtime.orchestration_payload, il livello di cache
# piu' esterno che avvolge l'intero ctx). Bump del 2026-08-09: aggiunta
# colonna "ValoreAperto" a build_portfolio_history_df - senza bump qui,
# ne' il bump del cache_sig interno alla funzione ne' quello del token
# StateManager (history_df_v4 -> v5) bastavano, perche' questo livello
# esterno non richiamava neppure get_history_df_for su un hit. Bump del
# 2026-08-13: fix sulle date weekend infiltrate nell'indice date dello
# storico portafoglio (_filter_weekend_dates in core/finance.py) - stesso
# sintomo, stesso motivo del bump precedente.
_STATE_MANAGER_SCHEMA = "2026-08-13-derived-runtime-cache-v3"


@st.cache_resource
def get_state_manager(schema_version: str = _STATE_MANAGER_SCHEMA) -> StateManager:
    _ = schema_version
    return StateManager()


with _logged_app_phase("state_load"):
    state_manager = get_state_manager()
    if st.session_state.pop("_force_reload", 0):
        state_manager.force_reload()
    else:
        state_manager.reload_if_changed()
    data = state_manager.get_data()
    settings = state_manager.get_settings()
    st.session_state["_settings_runtime"] = settings
    runtime_ui_settings = get_runtime_ui_settings(settings)
    snapshots_state = state_manager.get_snapshots()
    meta_state = state_manager.get_meta()
st.session_state["_plotly_profile_enabled"] = bool(
    runtime_ui_settings.get("debug_render_monitor", False)
    or runtime_ui_settings.get("debug_render_progress", False)
    or runtime_ui_settings.get("debug_render_log", False)
    or settings.get("ui_profile_plotly_render", False)
)
if os.getenv("PORTFOLIO_PROFILE_PLOTLY_ON_START") == "1":
    st.session_state["_plotly_profile_enabled"] = True
try:
    app_logger.info(
        "Theme runtime: font=%s headingFont=%s baseFontSize=%s baseFontWeight=%s",
        st.get_option("theme.font"),
        st.get_option("theme.headingFont"),
        st.get_option("theme.baseFontSize"),
        st.get_option("theme.baseFontWeight"),
    )
except Exception:
    pass

with _logged_app_phase("sidebar_render"):
    render_sidebar(data)


data = apply_privacy_filter(data, settings)

# Il log quotazioni è un metadato volatile della UI, non parte della
# firma finanziaria cacheata. Va letto dopo la sidebar perché il pulsante
# “Aggiorna Quotazioni” può salvarlo durante questo stesso script run.
_quotes_log_override = st.session_state.pop("_portfolio_quotes_log_override", None)
quotes_log = _quotes_log_override if isinstance(_quotes_log_override, dict) else load_quotes_log()

if bool(st.session_state.get("portfolio_dashboard_shutdown_requested", False)):
    _render_shutdown_dashboard_screen()


if not data.get("strumenti"):
    app_logger.info("Nessuno strumento presente: arresto iniziale della UI")
    st.info("👋 " + t(settings, "app.no_instruments", "Aggiungi il primo strumento dalla sidebar oppure importa i dati."))
    st.stop()


# === ORCHESTRATION: Pre-compute all page data via services ===
def _runtime_settings_signature() -> str:
    """Firma delle impostazioni che influenzano davvero il bootstrap runtime."""
    settings_payload = {
        "selected_categories": list(get_selected_category_codes(settings)),
        "calculations": get_calculations_settings(settings),
        "pre_render": get_pre_render_settings(settings),
        "runtime_ui": get_runtime_ui_settings(settings),
        "ui_preferences": get_ui_preferences(settings),
        "portfolio_benchmark": settings.get("portfolio_benchmark", {}),
        "portfolio_identity": settings.get("portfolio_identity", {}),
        "portfolio_objective": settings.get("portfolio_objective", {}),
        "sator_settings": settings.get("sator", {}),
        "include_proventi_in_total_return": settings.get("include_proventi_in_total_return"),
    }
    return hashlib.md5(json.dumps(settings_payload, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _portfolio_semantic_signature(*, include_cache_bust: bool) -> str:
    """Firma semantica del runtime portfolio.

    I dati benchmark/mercati hanno una loro cache dedicata e possono cambiare
    anche quando il portafoglio e' invariato. Includerli qui produce falsi
    `signature_changed` al primo avvio e rende poco leggibile la diagnostica
    performance. La loro variazione resta comunque visibile nel diff profiling.
    """
    selected_categories_sig = ",".join(get_selected_category_codes(settings))
    portfolio_data_sig = build_portfolio_data_signature(
        data,
        app_version=str(APP_VERSION),
        schema_version=str(SCHEMA_VERSION),
        include_benchmark_data=False,
    )
    settings_sig = _runtime_settings_signature()
    theme_sig = theme_signature(theme)
    signature = (
        f"v{APP_VERSION}|schema{SCHEMA_VERSION}|state:{_STATE_MANAGER_SCHEMA}"
        f"|data:{portfolio_data_sig}|settings:{settings_sig}"
        f"|cats:{selected_categories_sig}|theme:{theme_sig}"
    )
    if include_cache_bust:
        signature += f"|bust:{get_portfolio_cache_bust()}"
    return signature


def _portfolio_cache_signature() -> str:
    """Firma usata per invalidare la cache runtime dell'orchestrazione."""
    return _portfolio_semantic_signature(include_cache_bust=True)


def _profiling_persistence_enabled() -> bool:
    """Evita che AppTest/pytest contaminino la diagnostica reale in `.data`."""

    return os.getenv("PORTFOLIO_TESTING") != "1"


def _profiling_signature_diff_lines() -> list[str]:
    """
    Diagnostica leggibile delle componenti che cambiano nella firma portfolio.
    """
    parts_file = os.path.join(os.path.dirname(__file__), ".data", ".profiling_signature_parts.json")
    current_parts = build_portfolio_signature_components(data, include_benchmark_data=True)
    previous_parts: dict[str, Any] = {}
    persist_enabled = _profiling_persistence_enabled()
    if persist_enabled and os.path.exists(parts_file):
        try:
            with open(parts_file, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                previous_parts = loaded
        except Exception:
            previous_parts = {}

    changed_keys = [
        key for key, value in current_parts.items()
        if previous_parts.get(key) != value
    ]
    lines = ["signature_diff: none"]
    if not previous_parts:
        lines = ["signature_diff: first_run"]
    elif changed_keys:
        lines = [f"signature_diff: {', '.join(changed_keys)}"]
        for key in changed_keys:
            lines.append(f"  - {key}: {previous_parts.get(key)!r} -> {current_parts.get(key)!r}")

    try:
        if not persist_enabled:
            return lines
        os.makedirs(os.path.dirname(parts_file), exist_ok=True)
        with open(parts_file, "w", encoding="utf-8") as f:
            json.dump(current_parts, f, ensure_ascii=True, indent=2)
    except Exception:
        pass
    return lines


def _profiling_scenario(*, override_scenario: str | None = None, session_run_ordinal: int | None = None) -> str:
    """Classifica il run senza confondere stato cache e tipo di avvio."""
    # Track file per persistenza tra sessioni
    tracking_file = os.path.join(os.path.dirname(__file__), ".data", ".profiling_state")
    persist_enabled = _profiling_persistence_enabled()

    current_signature = _portfolio_semantic_signature(include_cache_bust=False)
    previous_signature_file = None
    if persist_enabled and os.path.exists(tracking_file):
        try:
            with open(tracking_file, "r", encoding="utf-8") as f:
                candidate = f.readline().strip()
            if candidate:
                previous_signature_file = candidate
        except Exception:
            previous_signature_file = None

    force_data_change = bool(st.session_state.pop("_profiling_force_data_change", False))
    seen_before = bool(previous_signature_file)
    signature_changed = bool(previous_signature_file and previous_signature_file != current_signature)
    override = str(override_scenario or "").strip()

    if not seen_before:
        cache_condition = "no_previous_signature"
    elif signature_changed:
        cache_condition = "signature_changed"
    else:
        cache_condition = "signature_unchanged"

    if override:
        scenario = override
    elif not seen_before:
        scenario = "cold_start"
    elif int(session_run_ordinal or 0) <= 1:
        scenario = "first_session_run"
    elif force_data_change or signature_changed:
        scenario = "post_data_change"
    else:
        scenario = "warm_rerun"

    if persist_enabled:
        os.makedirs(os.path.dirname(tracking_file), exist_ok=True)
        with open(tracking_file, "w", encoding="utf-8") as f:
            f.write(f"{current_signature}\n")

    st.session_state["_profiling_previous_signature"] = current_signature
    st.session_state["_profiling_scenario_current"] = scenario
    st.session_state["_profiling_cache_condition_current"] = cache_condition
    return scenario


def _profiling_cache_condition() -> str:
    return str(st.session_state.get("_profiling_cache_condition_current") or "n/d")


def _profiling_cohort_signature(scenario: str | None = None) -> str:
    """Firma stabile per confrontare run comparabili senza spezzare lo storico a ogni mtime."""
    scenario = str(scenario or _profiling_scenario(session_run_ordinal=_CURRENT_SESSION_RUN_ORDINAL))
    ui_mode = str(runtime_ui_settings.get("page_mode", "per_pagina"))
    quote_mode = "Completa"
    cache_strategy = resolve_figure_cache_strategy(settings, st.session_state)
    strumenti_count = len(data.get("strumenti", [])) if isinstance(data, dict) else 0
    storico_dates = len((data.get("storico_prezzi", {}) or {})) if isinstance(data, dict) else 0
    snapshots_count = len(snapshots_state or [])
    return (
        f"v{APP_VERSION}|schema{SCHEMA_VERSION}|bust:{get_portfolio_cache_bust()}"
        f"|ui:{ui_mode}|quotes:{quote_mode}|cache:{cache_strategy}"
        f"|strumenti:{strumenti_count}|storico:{storico_dates}|snapshots:{snapshots_count}"
        f"|scenario:{scenario}"
    )


_CURRENT_RERUN_CONTEXT = consume_next_render_scope(default="full_tabs")
_CURRENT_PROFILING_SCENARIO = _profiling_scenario(
    override_scenario=str(_CURRENT_RERUN_CONTEXT.get("scenario") or ""),
    session_run_ordinal=_CURRENT_SESSION_RUN_ORDINAL,
)
_CURRENT_PROFILING_CACHE_CONDITION = _profiling_cache_condition()
_CURRENT_PROFILING_COHORT = _profiling_cohort_signature(_CURRENT_PROFILING_SCENARIO)


def _build_orchestration_payload() -> dict[str, Any]:
    """Pre-compute portfolio data using pure services."""
    calculations_settings = get_calculations_settings(settings)
    return build_runtime_context_data(
        data=data,
        settings=settings,
        state_manager=state_manager,
        theme=theme,
        quotes_log=quotes_log,
        snapshots_state=snapshots_state,
        meta_state=meta_state,
        calculations_settings=calculations_settings,
        app_version=APP_VERSION,
        schema_version=SCHEMA_VERSION,
        logger=app_logger,
    )


def get_or_build_orchestration_payload(data_signature: str) -> dict[str, Any]:
    """Carica o costruisce il payload runtime tramite la cache unica registrata."""
    artifact_sig = build_cache_artifact_signature(
        "runtime.orchestration_payload",
        inputs={"portfolio_cache_sig": str(data_signature or "")},
    )
    app_logger.debug("Inizio orchestrazione dati: signature=%s artifact=%s", data_signature, artifact_sig)
    artifact = get_or_build_registered_artifact(
        artifact_id="runtime.orchestration_payload",
        signature=artifact_sig,
        builder=_build_orchestration_payload,
        clone_on_read=True,
        disk_codec="pickle",
    )
    value = artifact.value
    return value if isinstance(value, dict) else _build_orchestration_payload()


_portfolio_cache_sig = _portfolio_cache_signature()
with _logged_app_phase("orchestration", signature=_portfolio_cache_sig):
    ctx = SimpleNamespace(**get_or_build_orchestration_payload(_portfolio_cache_sig))
with _logged_app_phase("volatile_context_refresh"):
    refresh_volatile_ctx_fields(ctx, fmtd=fmtd, fmtds=fmtds, fmt_dt_it=fmt_dt_it)


def _refresh_volatile_quotes_runtime(ctx_obj: SimpleNamespace) -> None:
    """Aggiorna nel context solo i metadati leggeri della pagina Quotazioni.

    L'orchestrazione finanziaria può rimanere cacheata anche quando cambia
    soltanto il log dell'ultimo refresh. Se non aggiorniamo questi campi dopo
    la cache, la UI può mostrare orario/semaforo vecchi pur avendo salvato
    correttamente portafoglio_quotes_log.json.
    """
    try:
        _chiusi = getattr(ctx_obj, "chiusi_tickers", None) or frozenset()
        active_tickers = [
            str(item.get("ticker") or "")
            for item in (getattr(ctx_obj, "data", {}) or {}).get("strumenti", [])
            if str(item.get("ticker") or "") and str(item.get("ticker") or "") not in _chiusi
        ]
    except Exception:
        active_tickers = []
    quotes_refresh_df = build_quotes_refresh_df(quotes_log, active_tickers)
    ctx_obj.quotes_log = quotes_log
    ctx_obj.quotes_refresh_df = quotes_refresh_df
    ctx_obj.quotazioni_stats = get_quotazioni_stats(quotes_refresh_df)


_refresh_volatile_quotes_runtime(ctx)
_CURRENT_PRE_RENDER_SIGNATURE = None


# === FIGURE CACHE PRE-WARMING (background, non-blocking) ===
if os.getenv("PORTFOLIO_TESTING") == "1":
    app_logger.info("Pre-warming disabilitato in modalita test.")
else:
    try:
        from core.cache_prewarmer import should_prewarm, trigger_background_prewarm, compute_prewarm_signature, run_initial_prewarm, mark_prewarm_deferred
        from ui.prewarm_bundle import run_prewarm_bundle
        from core.render_profiler import persist_pre_render_event
        with _logged_app_phase("pre_render"):
            _cfg_strategy = resolve_figure_cache_strategy(settings, st.session_state)
            _pre_render_settings = get_pre_render_settings(settings)
            _prewarm_theme = get_theme_context()
            _prewarm_signature = compute_prewarm_signature(ctx, _prewarm_theme, settings)
            _CURRENT_PRE_RENDER_SIGNATURE = _prewarm_signature
            _pre_render_enabled = bool(_pre_render_settings.get("enabled", True))
            _pre_render_cooldown_seconds = int(_pre_render_settings.get("cooldown_seconds", 1800))
            _operational_scope = str(_CURRENT_RERUN_CONTEXT.get("render_scope") or "full_tabs")
            _operational_reason = str(_CURRENT_RERUN_CONTEXT.get("reason") or "")
            _operational_scenario = str(_CURRENT_RERUN_CONTEXT.get("scenario") or "")
            _is_operational_light_rerun = _operational_scope == "current_page_only" or bool(_operational_reason)
            if _is_operational_light_rerun:
                # Nei rerun operativi non ricostruiamo i grafici core in pre-render.
                # Marcando la firma come differita evitiamo che il run immediatamente
                # successivo rilanci un pre-render sincrono pesante.
                mark_prewarm_deferred(_prewarm_signature)
                persist_pre_render_event(
                    _prewarm_signature,
                    "PreRender",
                    "skip_operational_rerun",
                    0.0,
                    status="SKIP",
                    detail=(
                        f"mode=operational_rerun | render_scope={_operational_scope}"
                        f" | scenario={_operational_scenario or 'n/d'}"
                    ),
                    reset_cycle=True,
                )
            elif _cfg_strategy == "disabled":
                persist_pre_render_event(
                    _prewarm_signature,
                    "PreRender",
                    "disabled",
                    0.0,
                    status="SKIP",
                    detail="figure_cache_strategy=disabled",
                    reset_cycle=True,
                )
            elif not _pre_render_enabled:
                persist_pre_render_event(
                    _prewarm_signature,
                    "PreRender",
                    "disabled",
                    0.0,
                    status="SKIP",
                    detail="ui_pre_render.enabled=false",
                    reset_cycle=True,
                )
            else:
                _should_prewarm = should_prewarm(
                    signature=_prewarm_signature,
                    cooldown_seconds=_pre_render_cooldown_seconds,
                )
                _sync_prewarm_allowed = (
                    bool(_pre_render_settings.get("initial_complete", False))
                    and str(_CURRENT_PROFILING_SCENARIO or "") == "cold_start"
                )
                _background_prewarm_allowed = (
                    bool(_pre_render_settings.get("background_enabled", True))
                    and str(_CURRENT_PROFILING_SCENARIO or "") == "cold_start"
                )
                if _should_prewarm and _sync_prewarm_allowed:
                    persist_pre_render_event(
                        _prewarm_signature,
                        "PreRender",
                        "decision",
                        0.0,
                        detail="mode=initial_complete | scenario=cold_start",
                        reset_cycle=True,
                    )
                    run_initial_prewarm(ctx, _prewarm_theme, settings, prewarm_fn=run_prewarm_bundle)
                elif _should_prewarm and _background_prewarm_allowed:
                    _started = trigger_background_prewarm(ctx, _prewarm_theme, settings, prewarm_fn=run_prewarm_bundle)
                    persist_pre_render_event(
                        _prewarm_signature,
                        "PreRender",
                        "background_started" if _started else "background_busy",
                        0.0,
                        status="OK" if _started else "SKIP",
                        detail=(
                            f"mode=background | scenario={_CURRENT_PROFILING_SCENARIO}"
                            f" | initial_complete={bool(_pre_render_settings.get('initial_complete', False))}"
                        ),
                        reset_cycle=True,
                    )
                elif _should_prewarm and bool(_pre_render_settings.get("background_enabled", True)):
                    mark_prewarm_deferred(_prewarm_signature)
                    persist_pre_render_event(
                        _prewarm_signature,
                        "PreRender",
                        "deferred_warm_rerun",
                        0.0,
                        status="SKIP",
                        detail=(
                            f"mode=background_deferred | scenario={_CURRENT_PROFILING_SCENARIO}"
                            " | reason=no_background_work_during_warm_rerun"
                        ),
                        reset_cycle=True,
                    )
                elif _should_prewarm:
                    persist_pre_render_event(
                        _prewarm_signature,
                        "PreRender",
                        "deferred",
                        0.0,
                        status="SKIP",
                        detail=(
                            f"initial_complete={bool(_pre_render_settings.get('initial_complete', False))}"
                            f" | background_enabled=false | scenario={_CURRENT_PROFILING_SCENARIO}"
                        ),
                        reset_cycle=True,
                    )
                else:
                    persist_pre_render_event(
                        _prewarm_signature,
                        "PreRender",
                        "not_needed",
                        0.0,
                        status="SKIP",
                        detail=f"cooldown_seconds={_pre_render_cooldown_seconds}",
                        reset_cycle=True,
                    )
    except Exception as exc:
        app_logger.warning("Pre-warming non eseguito: %s", exc)

# === BENCHMARK SCHEDULER (background, 18:00 italiane) ===
if os.getenv("PORTFOLIO_TESTING") == "1":
    app_logger.info("Benchmark scheduler disabilitato in modalita test.")
else:
    try:
        from core.infrastructure.schedule import start_benchmark_scheduler
        with _logged_app_phase("benchmark_scheduler_start"):
            start_benchmark_scheduler(data)
    except Exception as exc:
        app_logger.warning("Benchmark scheduler non avviato: %s", exc)


# === MERCATI AUTO-REFRESH SCHEDULER (background, cache only) ===
if os.getenv("PORTFOLIO_TESTING") == "1":
    app_logger.info("Auto-refresh Mercati disabilitato in modalita test.")
else:
    try:
        from core.infrastructure.market_auto_refresh import start_market_auto_refresh_scheduler
        with _logged_app_phase("market_auto_refresh_scheduler_start"):
            start_market_auto_refresh_scheduler(settings)
    except Exception as exc:
        app_logger.warning("Auto-refresh Mercati non avviato: %s", exc)


# === DEBUG / PERFORMANCE UI FLAGS ===
_ui_preferences = get_ui_preferences(settings)
_RENDER_DEBUG_PROGRESS_ENABLED = bool(
    runtime_ui_settings.get("debug_render_progress", runtime_ui_settings.get("debug_render_monitor", False))
)
_RENDER_DEBUG_LOG_ENABLED = bool(
    runtime_ui_settings.get("debug_render_log", runtime_ui_settings.get("debug_render_monitor", False))
)
_RENDER_DEBUG_ENABLED = bool(_RENDER_DEBUG_PROGRESS_ENABLED or _RENDER_DEBUG_LOG_ENABLED)
_RENDER_ALWAYS_PROGRESS_ENABLED = True


# === SCENARIO CACHE BADGE ===
def _scenario_cache_badge_display(scenario: str) -> str:
    """Mappa lo scenario di cache a una label compatta per il banner."""
    badge_map = {
        "cold_start": ("Cold start", "#0EA5E9"),
        "first_session_run": ("Primo run", "#6366F1"),
        "post_data_change": ("Dati aggiornati", "#F97316"),
        "warm_rerun": ("Cache calda", "#10B981"),
        "quote_refresh": ("Quote refresh", "#F97316"),
        "quote_refresh_noop": ("Quote invariate", "#64748B"),
        "settings_update": ("Setup aggiornato", "#F97316"),
    }
    label, color = badge_map.get(scenario, (str(scenario or "run"), "#6B7280"))
    return (
        f'<span class="header-status-dot" style="--status-color:{color};"></span>'
        f"<span>{label}</span>"
    )


# === PAGE HEADER ===
st.markdown('<div id="page-top"></div>', unsafe_allow_html=True)
_debug_badge = " • DEBUG" if _RENDER_DEBUG_ENABLED else ""
_scenario_badge = _scenario_cache_badge_display(_CURRENT_PROFILING_SCENARIO)
_cache_strategy_label = str(resolve_figure_cache_strategy(settings, st.session_state) or "auto").replace("_", " ")
_header_logo_url = f"app/static/sestante_logo_header_final.png?v={APP_VERSION}-final-logo"
_header_date_text = str(getattr(ctx, "header_date", "") or "")
_header_update_marker = "(ultimo aggiornamento quotazioni:"
if _header_update_marker in _header_date_text:
    _header_today_text, _header_update_text = _header_date_text.split(_header_update_marker, 1)
    _header_today_text = _header_today_text.strip()
    _header_update_text = _header_update_text.rstrip(") ").strip()
else:
    _header_today_text = _header_date_text.strip() or fmtd(date.today())
    _header_update_text = fmt_dt_it(getattr(ctx, "last_quotes_update", None))
st.markdown(f"""<div class="header-panel header-executive">
    <div class="header-brand header-brand-logo-wrap">
        <img class="header-brand-logo" src="{_header_logo_url}" alt="Sestante - Gestione Portafoglio Finanziario">
    </div>
    <div class="header-right">
        <div class="header-meta">
            <div class="header-chip">
                <span class="header-chip-label">Versione</span>
                <span class="header-chip-value accent">v{APP_VERSION}{_debug_badge}</span>
            </div>
            <div class="header-chip">
                <span class="header-chip-label">Run</span>
                <span class="header-chip-value">{_scenario_badge}</span>
            </div>
            <div class="header-chip">
                <span class="header-chip-label">Cache</span>
                <span class="header-chip-value">{_cache_strategy_label}</span>
            </div>
        </div>
        <div class="header-timeline">
            <span><strong>Data</strong> {_header_today_text}</span>
            <span><strong>Aggiornamento</strong> {_header_update_text}</span>
        </div>
    </div>
</div>""", unsafe_allow_html=True)
_header_progress_host = st.empty()


# Nota tecnica:
# - Il pre-render grafici e' asincrono nei rerun caldi: la navigazione deve
#   restare fluida anche quando cache o firma dati richiedono aggiornamento.

_PAGE_DEFS = [
    PageDef("quotazioni",     f"📈 {t(settings, 'tab.quotes', 'Quotazioni')}",          render_quotazioni),
    PageDef("portafoglio",    f"📋 {t(settings, 'tab.portfolio', 'Portafoglio')}",      render_home),
    PageDef("operazioni",     f"📒 {t(settings, 'tab.operations', 'Operazioni')}",      render_operazioni),
    PageDef("cruscotti",      f"🧭 {t(settings, 'tab.dashboards', 'Cruscotti')}",       render_cruscotti),
    PageDef("mercati",        f"🌐 {t(settings, 'tab.markets', 'Mercati')}",            render_mercati),
    PageDef("summary",        f"📄 {t(settings, 'tab.summary', 'Summary')}",            render_summary),
    PageDef("confronto",      f"🆚 {t(settings, 'tab.comparison', 'Confronto')}",       render_confronto),
    PageDef("pianificazione", f"🎯 {t(settings, 'tab.planning', 'Pianificazione')}",    render_pianificazione),
    PageDef("ai",             f"🤖 {t(settings, 'tab.ai', 'AI')}",                      render_ai_page),
    PageDef("gestione_dati",  f"🗄️ {t(settings, 'tab.data_management', 'Dati')}",      render_gestione_dati),
    PageDef("impostazioni",   f"⚙️ {t(settings, 'tab.settings', 'Setup')}",            render_impostazioni),
]
_PAGE_COUNT = len(_PAGE_DEFS)
st.session_state["total_pages"] = _PAGE_COUNT

# Handle navigation to Quotazioni requested from sidebar/actions.
if st.session_state.pop("goto_tab_quotazioni", False):
    st.session_state.active_tab = 0
    trigger_tab_navigation()

if st.session_state.pop("goto_tab_operazioni", False):
    st.session_state.active_tab = 2
    trigger_tab_navigation()

app_logger.info(
    "[RUN_CONTEXT] scenario=%s cache_condition=%s cohort=%s debug_progress=%s debug_log=%s debug_scope=%s render_scope=%s reason=%s",
    _CURRENT_PROFILING_SCENARIO,
    _CURRENT_PROFILING_CACHE_CONDITION,
    _CURRENT_PROFILING_COHORT,
    _RENDER_DEBUG_PROGRESS_ENABLED,
    _RENDER_DEBUG_LOG_ENABLED,
    str(runtime_ui_settings.get("debug_render_scope", "current_page")),
    str(_CURRENT_RERUN_CONTEXT.get("render_scope") or "full_tabs"),
    str(_CURRENT_RERUN_CONTEXT.get("reason") or ""),
)
with _logged_app_phase("dashboard_render", scenario=_CURRENT_PROFILING_SCENARIO):
    render_dashboard_tabs(
        page_defs=_PAGE_DEFS,
        ctx=ctx,
        debug_enabled=_RENDER_DEBUG_ENABLED,
        debug_progress_enabled=_RENDER_ALWAYS_PROGRESS_ENABLED,
        debug_log_enabled=_RENDER_DEBUG_LOG_ENABLED,
        debug_render_scope=str(runtime_ui_settings.get("debug_render_scope", "current_page")),
        render_overview=render_overview,
        app_logger=app_logger,
        app_version=APP_VERSION,
        schema_version=SCHEMA_VERSION,
        data_mtime=_data_mtime(),
        cache_bust=get_portfolio_cache_bust(),
        portfolio_signature=_portfolio_cache_sig,
        pre_render_signature=_CURRENT_PRE_RENDER_SIGNATURE,
        profiling_cohort=_CURRENT_PROFILING_COHORT,
        profiling_scenario=_CURRENT_PROFILING_SCENARIO,
        profiling_cache_condition=_CURRENT_PROFILING_CACHE_CONDITION,
        profiling_signature_diff_lines=_profiling_signature_diff_lines(),
        operational_render_scope=str(_CURRENT_RERUN_CONTEXT.get("render_scope") or "full_tabs"),
        operational_reason=str(_CURRENT_RERUN_CONTEXT.get("reason") or ""),
        operational_origin_page_id=str(_CURRENT_RERUN_CONTEXT.get("origin_page_id") or ""),
        operational_origin_page_index=int(_CURRENT_RERUN_CONTEXT.get("origin_page_index") or 0),
        dirty_flags=dict(_CURRENT_RERUN_CONTEXT.get("dirty_flags") or {}),
        progress_host=_header_progress_host,
        run_started_at=_APP_RUN_STARTED_AT,
    )

try:
    from core.figure_cache import flush_figure_cache_manifest
    with _logged_app_phase("figure_cache_manifest_flush"):
        flush_figure_cache_manifest()
except Exception:
    app_logger.exception("Errore durante il flush del manifest figure cache")
