"""
ui/pages/impostazioni.py — Tab Impostazioni: configurazione strutturale.
Pure rendering - le operazioni amministrative vivono in Gestione Dati.
"""
import logging
import json
import os
import shutil
from datetime import date, datetime
from types import SimpleNamespace

import pandas as pd
import streamlit as st

from core.cache import invalidate_portfolio_cache, record_cache_decision
from core.ai_analysis import (
    GEMINI_MODELS,
    load_ai_config,
    save_ai_config,
    test_gemini_connection,
)
from streamlit.delta_generator import DeltaGenerator

from core.asset_categories import (
    ASSET_CATEGORY_REGISTRY,
    MAX_VISIBLE_CATEGORY_CODES,
    get_selected_category_codes,
    normalize_category_selection,
)
from persistence.storage import (
    BASE_DIR, DATA_FILE, SETTINGS_FILE, QUOTES_LOG_FILE,
    SNAPSHOTS_FILE, BENCHMARK_CACHE_FILE, META_FILE,
    BENCH, APP_VERSION, SCHEMA_VERSION,
    TIPI_EVENTO_PORTAFOGLIO, EVENTI_CON_STRUMENTO, EVENTI_CON_QUANTITA,
    EVENTI_CON_PREZZO, EVENTI_CON_IMPORTO,
    macro_cat, _normalize_macro_label,
    _safe_float, _safe_date_str,
    default_settings, default_data_v33,
    get_registro_eventi, get_proventi_normalizzati,
    _event_sort_key, _new_event_id,
    _normalize_event_record, _rebuild_cash_ledger_from_events,
    _build_instrument_master,
    save_data, save_settings, save_quotes_log, save_snapshots,
    load_settings, load_quotes_log, load_snapshots, load_meta,
append_audit_event, describe_audit_event,
)
from core.finance import (
    CUSTOM_BENCHMARK_COMPONENT_OPTIONS,
    PORTFOLIO_BENCH_OPTIONS, _build_snapshot_from_data,
)
from core.services.benchmark import resolve_effective_benchmark_components
from core.settings_profiles import (
    get_alerts_settings,
    get_benchmarking_settings,
    get_calculations_settings,
    get_category_view_settings,
    get_i18n_settings,
    get_pre_render_settings,
    get_portfolio_profile,
    get_runtime_ui_settings,
    get_ui_preferences,
)
from core.validators import (
    validate_alert_thresholds,
    validate_date,
    validate_number_input,
    validate_quote_import,
    validate_selection,
)
from ui.formatting import (
    fmt_dt_it, fmt_num_it, fmt_eur_it, fmt_pct_it, fmt_qty_it,
)
from ui.theme import get_theme_context
from ui.notifications import queue_info, queue_success
from ui.i18n import t
from ui.page_chrome import render_page_intro as render_page_intro_shared, render_section_line as render_section_line_shared
from ui.components import (
    legend_block, back_to_top,
    render_styled_table,
    vertical_gap,
    render_section_title,
)

logger = logging.getLogger("portafoglio.ui.impostazioni")


def _page_icon_svg(kind: str = "default") -> str:
    icons = {
        "summary": """
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <defs><linearGradient id="g-summary" x1="3" y1="3" x2="21" y2="21"><stop stop-color="var(--page-accent)"/><stop offset="1" stop-color="var(--page-accent-2)"/></linearGradient></defs>
          <rect x="3.5" y="3" width="17" height="18" rx="4" fill="url(#g-summary)" opacity=".16"/>
          <path d="M8 8.2h8M8 12h8M8 15.8h5" fill="none" stroke="url(#g-summary)" stroke-width="1.9" stroke-linecap="round"/>
          <circle cx="17" cy="16" r="2.2" fill="url(#g-summary)"/>
        </svg>
        """,
        "confronto": """
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <defs><linearGradient id="g-confronto" x1="4" y1="20" x2="20" y2="4"><stop stop-color="var(--page-accent)"/><stop offset="1" stop-color="var(--page-accent-2)"/></linearGradient></defs>
          <rect x="3" y="4" width="18" height="16" rx="4" fill="url(#g-confronto)" opacity=".14"/>
          <path d="M7 16.5V11M12 16.5V7.5M17 16.5v-4" fill="none" stroke="url(#g-confronto)" stroke-width="2.1" stroke-linecap="round"/>
          <path d="M6.5 17.5h11" stroke="url(#g-confronto)" stroke-width="1.8" stroke-linecap="round"/>
        </svg>
        """,
        "pianificazione": """
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <defs><linearGradient id="g-plan" x1="4" y1="4" x2="20" y2="20"><stop stop-color="var(--page-accent)"/><stop offset="1" stop-color="var(--page-accent-2)"/></linearGradient></defs>
          <rect x="3.5" y="5" width="17" height="15.5" rx="4" fill="url(#g-plan)" opacity=".15"/>
          <path d="M8 3.5v3M16 3.5v3M6.5 9h11" stroke="url(#g-plan)" stroke-width="1.8" stroke-linecap="round"/>
          <path d="M8 13h3l1.5 2.2L16.5 11" fill="none" stroke="url(#g-plan)" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
        """,
        "gestione": """
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <defs><linearGradient id="g-data" x1="4" y1="4" x2="20" y2="20"><stop stop-color="var(--page-accent)"/><stop offset="1" stop-color="var(--page-accent-2)"/></linearGradient></defs>
          <rect x="4" y="3.5" width="16" height="17" rx="4" fill="url(#g-data)" opacity=".15"/>
          <path d="M8 8h8M8 12h8M8 16h5" stroke="url(#g-data)" stroke-width="1.8" stroke-linecap="round"/>
          <circle cx="17" cy="16" r="2.2" fill="url(#g-data)"/>
        </svg>
        """,
        "impostazioni": """
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <defs><linearGradient id="g-settings" x1="4" y1="4" x2="20" y2="20"><stop stop-color="var(--page-accent)"/><stop offset="1" stop-color="var(--page-accent-2)"/></linearGradient></defs>
          <circle cx="12" cy="12" r="8.5" fill="url(#g-settings)" opacity=".15"/>
          <path d="M12 8.1v-2M12 18v-2M8.1 12h-2M18 12h-2M9.25 9.25 7.8 7.8M16.2 16.2l-1.45-1.45M14.75 9.25 16.2 7.8M7.8 16.2l1.45-1.45" stroke="url(#g-settings)" stroke-width="1.7" stroke-linecap="round"/>
          <circle cx="12" cy="12" r="3.1" fill="none" stroke="url(#g-settings)" stroke-width="2"/>
        </svg>
        """,
        "default": """
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <defs><linearGradient id="g-default" x1="4" y1="4" x2="20" y2="20"><stop stop-color="var(--page-accent)"/><stop offset="1" stop-color="var(--page-accent-2)"/></linearGradient></defs>
          <rect x="4" y="4" width="16" height="16" rx="4" fill="url(#g-default)" opacity=".15"/>
          <path d="M8 9h8M8 13h8M8 17h5" stroke="url(#g-default)" stroke-width="1.8" stroke-linecap="round"/>
        </svg>
        """,
    }
    return icons.get(kind, icons["default"])


def _render_page_intro(title: str, comment: str, icon: str = "default", theme=None) -> None:
    return render_page_intro_shared(title, comment, icon, theme)


def _section_line() -> None:
    return render_section_line_shared()


def render_impostazioni(tab: DeltaGenerator, ctx: SimpleNamespace) -> None:
    """Pure rendering for impostazioni page."""
    # Get theme at function entry
    theme = get_theme_context()

    # Extract needed data from context
    data = ctx.data
    fmtd = ctx.fmtd
    settings = dict(getattr(ctx, "settings", {}) or {})

    st.markdown(
        f"""<style>
        .settings-inline-panel {{
          background:{theme.colors.get('bg_surface_alt', theme.bg_surface)};
          border:1px solid {theme.border_color};
          border-radius:16px;
          padding:12px 14px;
          color:{theme.font_color};
          box-shadow:{theme.shadow_color};
          line-height:1.55;
        }}
        .settings-domain-title {{
          font-size:1.02rem;
          font-weight:800;
          color:{theme.font_color};
          margin:0 0 6px 0;
        }}
        .settings-domain-note {{
          color:{theme.muted_color};
          line-height:1.58;
          margin:0 0 14px 0;
        }}
        div[data-testid="stForm"] {{
          border:none !important;
          background:transparent !important;
          box-shadow:none !important;
          padding:0 !important;
        }}
        .settings-subsection-title {{
          font-size:0.94rem;
          font-weight:750;
          color:{theme.font_color};
          margin:18px 0 8px 0;
        }}
        .settings-subsection-note {{
          color:{theme.muted_color};
          line-height:1.55;
          margin:0 0 12px 0;
        }}
        .settings-ops-guide {{
          display:flex;
          flex-direction:column;
          gap:8px;
          margin:2px 0 16px 0;
        }}
        .settings-ops-guide__row {{
          display:grid;
          grid-template-columns:minmax(138px, 0.28fr) 1fr;
          gap:12px;
          align-items:center;
          padding:11px 13px;
          border:1px solid color-mix(in srgb, var(--guide-color) 34%, {theme.border_color});
          border-left:4px solid var(--guide-color);
          border-radius:8px;
          background:color-mix(in srgb, var(--guide-color) 8%, var(--ptf-surface, #ffffff));
        }}
        .settings-ops-guide__tag {{
          display:inline-flex;
          align-items:center;
          width:max-content;
          max-width:100%;
          padding:4px 8px;
          border-radius:999px;
          background:color-mix(in srgb, var(--guide-color) 16%, transparent);
          color:var(--guide-color);
          font-weight:800;
          font-size:.78rem;
          line-height:1.15;
          white-space:nowrap;
        }}
        .settings-ops-guide__text {{
          color:{theme.font_color};
          font-size:.9rem;
          line-height:1.42;
          margin:0;
        }}
        .settings-ops-guide__text strong {{
          color:{theme.font_color};
          font-weight:800;
        }}
        @media (max-width: 720px) {{
          .settings-ops-guide__row {{
            grid-template-columns:1fr;
            gap:7px;
          }}
        }}
        </style>""",
        unsafe_allow_html=True,
    )
    with tab:

        _render_page_intro(t(settings, "tab.settings", "Impostazioni"), t(settings, "page_intro.impostazioni.comment", "Profilo, visualizzazione, calcoli, benchmark, lingua e formato dati."), "impostazioni", theme)
        settings = load_settings()
        calculations_settings = get_calculations_settings(settings)
        alerts_settings = get_alerts_settings(settings)
        benchmarking_settings = get_benchmarking_settings(settings)
        category_view_settings = get_category_view_settings(settings)
        ui_preferences = get_ui_preferences(settings)
        runtime_ui_settings = get_runtime_ui_settings(settings)
        pre_render_settings = get_pre_render_settings(settings)
        i18n_settings = get_i18n_settings(settings)
        try:
            _settings_form = st.form("settings_form", clear_on_submit=False, border=False)
        except TypeError:
            _settings_form = st.form("settings_form", clear_on_submit=False)
        with _settings_form:
            portfolio_profile = get_portfolio_profile(settings)
            with st.container():
                render_section_title(
                    t(settings, 'settings.subsection.identity', 'Anagrafica portafoglio'),
                    comment="Definisci l'identita' del portafoglio: nome, descrizione e valute di riferimento. Questi dati vengono riusati nei report e nella Portfolio Summary.",
                    icon="portfolio",
                )
                pf1, pf2 = st.columns(2)
                portfolio_name = pf1.text_input("Nome portafoglio", value=str(portfolio_profile.get("portfolio_name", "Portafoglio Principale")))
                portfolio_code = pf2.text_input("Codice portafoglio", value=str(portfolio_profile.get("portfolio_id", "main")))
                pf3, pf4 = st.columns(2)
                st.caption("🔒 Funzionalità futura: la conversione multi-valuta non è ancora supportata — ogni importo nell'app resta espresso in EUR indipendentemente da questa scelta.")
                base_currency = pf3.selectbox("Valuta base", ["EUR", "USD", "GBP", "CHF"], index=["EUR", "USD", "GBP", "CHF"].index(str(portfolio_profile.get("base_currency", "EUR"))) if str(portfolio_profile.get("base_currency", "EUR")) in ["EUR", "USD", "GBP", "CHF"] else 0, disabled=True)
                reporting_currency = pf4.selectbox("Valuta reporting", ["EUR", "USD", "GBP", "CHF"], index=["EUR", "USD", "GBP", "CHF"].index(str(portfolio_profile.get("reporting_currency", "EUR"))) if str(portfolio_profile.get("reporting_currency", "EUR")) in ["EUR", "USD", "GBP", "CHF"] else 0, disabled=True)
                portfolio_description = st.text_area("Descrizione portafoglio", value=str(portfolio_profile.get("description", "")), height=80)
                bench_default = st.selectbox("Benchmark di portafoglio", PORTFOLIO_BENCH_OPTIONS, index=max(PORTFOLIO_BENCH_OPTIONS.index(benchmarking_settings.get("default_portfolio_benchmark", "Blend automatico")) if benchmarking_settings.get("default_portfolio_benchmark", "Blend automatico") in PORTFOLIO_BENCH_OPTIONS else 0, 0))
                st.caption("Agisce sui confronti del portafoglio nel tempo, sulla Portfolio Summary e sui report esportati: è il riferimento usato per calcolare il confronto relativo del portafoglio.")
                st.caption("L'obiettivo di portafoglio (Core/Difensivo/Satellite) e i radar della scheda Portafoglio si impostano ora in Pianificazione.")
                custom_benchmark_enabled = st.checkbox("Usa benchmark personalizzato", value=bool(benchmarking_settings.get("custom_enabled", False)))
                custom_benchmark_name = st.text_input("Nome benchmark personalizzato", value=str(benchmarking_settings.get("custom_name", "")), disabled=not custom_benchmark_enabled)
                custom_component_choices = list(CUSTOM_BENCHMARK_COMPONENT_OPTIONS.keys())
                current_components = benchmarking_settings.get("custom_components", []) if isinstance(benchmarking_settings.get("custom_components", []), list) else []
                component_rows = []
                legend_block("Puoi definire un benchmark composito scegliendo fino a tre componenti e il loro peso relativo. I pesi vengono normalizzati automaticamente.")
                for idx in range(3):
                    existing = current_components[idx] if idx < len(current_components) and isinstance(current_components[idx], dict) else {}
                    existing_ticker = str(existing.get("ticker", ""))
                    reverse_label = next((label for label, ticker in CUSTOM_BENCHMARK_COMPONENT_OPTIONS.items() if ticker == existing_ticker), custom_component_choices[0])
                    cbench1, cbench2 = st.columns([3, 1])
                    selected_label = cbench1.selectbox(
                        f"Componente {idx + 1}",
                        custom_component_choices,
                        index=custom_component_choices.index(reverse_label) if reverse_label in custom_component_choices else 0,
                        key=f"custom_bench_component_{idx}",
                        disabled=not custom_benchmark_enabled,
                    )
                    component_weight = cbench2.number_input(
                        f"Peso {idx + 1} %",
                        min_value=0.0,
                        max_value=100.0,
                        value=float(existing.get("weight", 0.0) or 0.0),
                        step=5.0,
                        format="%.1f",
                        key=f"custom_bench_weight_{idx}",
                        disabled=not custom_benchmark_enabled,
                    )
                    if custom_benchmark_enabled and float(component_weight) > 0:
                        component_rows.append({
                            "ticker": CUSTOM_BENCHMARK_COMPONENT_OPTIONS[selected_label],
                            "weight": float(component_weight) / 100.0,
                        })
                # Anteprima dichiarativa del benchmark effettivo: rende visibile
                # cosa verra' usato nei confronti Cruscotti/Summary/Report dopo il salvataggio.
                preview_settings = {
                    **settings,
                    "benchmarking": {
                        **settings.get("benchmarking", {}),
                        "default_portfolio_benchmark": bench_default,
                        "custom_enabled": bool(custom_benchmark_enabled),
                        "custom_name": str(custom_benchmark_name or "").strip(),
                        "custom_components": component_rows,
                    },
                }
                preview_cfg = resolve_effective_benchmark_components(preview_settings, None)
                preview_components = pd.DataFrame(preview_cfg.get("components", []))
                st.markdown("<div class='settings-subsection-title'>Anteprima benchmark effettivo</div>", unsafe_allow_html=True)
                legend_block(str(preview_cfg.get("method_note") or "Il benchmark scelto sara' usato per Summary, Cruscotti, Confronto, Report, extra-rendimento, tracking error e information ratio."))
                if not preview_components.empty:
                    preview_display = pd.DataFrame({
                        "Componente": preview_components.get("label", pd.Series(dtype=str)).astype(str),
                        "Ticker": preview_components.get("ticker", pd.Series(dtype=str)).astype(str),
                        "Peso": pd.to_numeric(preview_components.get("weight"), errors="coerce"),
                    })
                    preview_styled = (
                        preview_display.style
                        .format({"Peso": lambda v: fmt_pct_it(v, 1, signed=False)})
                        .set_properties(subset=["Peso"], **{"text-align": "right", "font-variant-numeric": "tabular-nums"})
                        .set_table_styles([
                            {"selector": "th", "props": [("font-weight", "700"), ("white-space", "nowrap")]},
                            {"selector": "td", "props": [("white-space", "nowrap")]},
                        ], overwrite=False)
                    )
                    render_styled_table(preview_styled, height=min(190, 72 + len(preview_display) * 34))

            _section_line()
            with st.container():
                render_section_title(
                    t(settings, 'settings.domain.appearance', 'Aspetto e Visualizzazione'),
                    comment=t(settings, 'settings.domain.appearance_note', 'Personalizza colori, font e visibilita delle sezioni.'),
                    icon="settings",
                )

                appearance_settings = settings.get("appearance", {})

                # Predefined font families - must be web-safe or loaded via CDN
                FONT_FAMILIES = {
                    "Sans-serif predefinito": "system-ui, -apple-system, sans-serif",
                    "Segoe UI": "'Segoe UI', Tahoma, sans-serif",
                    "Roboto": "'Roboto', 'Helvetica', sans-serif",
                    "Monospace": "'Courier New', monospace",
                    "Georgia": "'Georgia', serif",
                }

                # --- COLORS ---
                st.markdown("**Colori**")
                from core.palettes import PALETTES
                palette_options = list(PALETTES.keys())
                current_palette = str(appearance_settings.get("color_palette", "Default"))
                ui_color_palette = st.radio(
                    "Scegli palette di colori",
                    palette_options,
                    index=palette_options.index(current_palette) if current_palette in palette_options else 0,
                    horizontal=True,
                    key="appearance_color_palette",
                )

                # --- ACCENT VARIANT ---
                from ui.theme import ACCENT_VARIANTS
                accent_options = list(ACCENT_VARIANTS.keys())
                current_accent = str(ui_preferences.get("accent_variant", "Default"))
                ui_accent_variant = st.selectbox("Colore accento", accent_options,
                    index=accent_options.index(current_accent) if current_accent in accent_options else 0,
                    help="Colore usato per bottoni ed elementi in evidenza in tutta l'interfaccia.",
                    key="appearance_accent_variant",
                )

                # --- SHOW EXPLANATIONS ---
                ui_show_explanations = st.checkbox("Mostra spiegazioni nei Cruscotti e in Confronto",
                    value=bool(ui_preferences.get("show_explanations", True)),
                    help="Disattiva per nascondere i box esplicativi e i commenti introduttivi nelle pagine Cruscotti e Confronto.",
                    key="appearance_show_explanations",
                )

                ui_show_portfolio_insights = st.checkbox("Portafoglio: mostra priorita' operative",
                    value=bool(ui_preferences.get("show_portfolio_insights", True)),
                    help="Mostra sopra la tabella del Portafoglio un pannello read-only con scostamenti, concentrazione, movimento giornaliero e richiamo SATOR. Disattivalo per tornare alla vista precedente.",
                    key="appearance_show_portfolio_insights",
                )

                ui_show_market_ticker_tape = st.checkbox("Portafoglio: mostra striscia mercati",
                    value=bool(ui_preferences.get("show_market_ticker_tape", True)),
                    help="Mostra sotto il titolo della tabella una striscia informativa con mercati/proxy aperti o chiusi e ultima variazione disponibile in cache. Non scarica nuovi dati.",
                    key="appearance_show_market_ticker_tape",
                )

                # --- QUOTAZIONI FULL RESOLUTION ---
                ui_quotazioni_full_resolution = st.checkbox("Quotazioni: dettaglio giornaliero completo",
                    value=bool(ui_preferences.get("quotazioni_full_resolution", False)),
                    help="Di default i grafici storico-quotazioni mostrano un punto a settimana per i dati oltre gli ultimi 90 giorni (i valori restano esatti, solo meno punti a schermo). Attiva per vedere sempre ogni singolo giorno su tutti i grafici.",
                    key="appearance_quotazioni_full_resolution",
                )

                # Dimensioni tipografiche (titoli/sottotitoli/body/commenti) rimosse
                # dalla UI il 2026-07-16: nessuna variabile CSS le applicava da
                # nessuna parte (verificato: solo typography.family alimenta
                # --ptf-font-family in ui/theme.py, mai titles/subtitles/body/
                # caption). Restano fisse a "Standard" finche' non si costruisce
                # la propagazione CSS necessaria a ogni intestazione dell'app.
                _TYPO_STANDARD_SIZES = {"titles": "1.4rem", "subtitles": "1.1rem", "body": "0.95rem", "caption": "0.85rem"}

                # --- FONT FAMILY ---
                st.markdown("**Famiglia font**")
                font_families = list(FONT_FAMILIES.keys())
                current_font_family = str(appearance_settings.get("typography", {}).get("family", "Sans-serif predefinito"))
                ui_font_family = st.selectbox(
                    "Seleziona font",
                    font_families,
                    index=font_families.index(current_font_family) if current_font_family in font_families else 0,
                    help="La scelta si applica a tutta l'interfaccia: Streamlit, grafici, e componenti personalizzati",
                    key="appearance_font_family",
                )

                # --- VISIBILITY ---
                st.markdown("**Visibilità sezioni**")
                visibility_presets = ["Essenziale", "Standard", "Completo"]
                current_mode = str(appearance_settings.get("visibility_mode", "Standard"))
                ui_visibility_mode = st.radio(
                    "Preset visualizzazione",
                    visibility_presets,
                    index=visibility_presets.index(current_mode) if current_mode in visibility_presets else 1,
                    horizontal=True,
                    key="appearance_visibility_mode",
                )

                st.markdown("**Categorie visibili**")
                category_options = [code for code in ASSET_CATEGORY_REGISTRY.keys() if code != "ALTRO"]
                current_categories = normalize_category_selection(
                    category_view_settings.get("selected_categories"),
                    fallback=get_selected_category_codes(settings),
                )
                category_labels = {
                    code: f"{code} - {ASSET_CATEGORY_REGISTRY.get(code, {}).get('name', code)}"
                    for code in category_options
                }
                selected_category_labels = st.multiselect(
                    f"Seleziona fino a {MAX_VISIBLE_CATEGORY_CODES} categorie attive nel portafoglio",
                    options=category_options,
                    default=current_categories,
                    format_func=lambda code: category_labels.get(code, code),
                    max_selections=MAX_VISIBLE_CATEGORY_CODES,
                    key="category_view_selected_categories",
                    help="Le categorie selezionate definiscono il perimetro attivo: grafici, tabelle e calcoli usano solo queste.",
                )
                st.caption(
                    "Le categorie non selezionate restano archiviate nei dati, ma vengono escluse dal perimetro attivo di portafoglio, grafici e calcoli."
                )
            _section_line()
            with st.container():
                render_section_title(
                    t(settings, 'settings.domain.analysis', 'Analisi e Controlli'),
                    comment=t(settings, 'settings.domain.analysis_note', 'Parametri del motore analitico, rolling windows e soglie di allerta usate nelle viste di monitoraggio.'),
                    icon="analysis",
                )
                st.markdown(f"**{t(settings, 'settings.subsection.analysis', 'Analisi e soglie')}**")
                legend_block("Le opzioni proventi, rolling window e inflazione regolano i calcoli di rendimento e volatilità.")
                c77, c78, c79 = st.columns(3)
                include_proventi = c77.checkbox("Includi proventi nei ritorni", value=bool(calculations_settings.get("include_proventi_in_total_return", True)))
                rolling_window_days = c78.number_input("Rolling window (giorni)", min_value=30, max_value=365, value=int(calculations_settings.get("rolling_window_days", 90)), step=10)
                inflation_rate = c79.number_input("Inflazione annua %", min_value=0.0, max_value=50.0, value=float(calculations_settings.get("inflation_rate", 0.0)) * 100.0, step=0.25, format="%.2f")
                st.markdown(f"**{t(settings, 'settings.subsection.alerts', 'Avvisi e soglie')}**")
                legend_block("Configura gli alert automatici più immediati: concentrazione eccessiva, perdite oltre soglia e squilibri tra rischio e peso. In questo primo blocco gli avvisi vengono mostrati nella parte alta della dashboard.")
                al1, al2 = st.columns(2)
                alerts_enabled = al1.checkbox("Alert attivi", value=bool(alerts_settings.get("enabled", False)))
                alerts_risk_weight = al2.checkbox("Monitora rischio/peso", value=bool(alerts_settings.get("risk_weight_monitoring", True)))
                al4, al5 = st.columns(2)
                loss_threshold_pct = al4.number_input("Perdita soglia %", min_value=0.0, max_value=100.0, value=float(alerts_settings.get("loss_threshold_pct") or 0.0), step=1.0, format="%.1f", help="0 = disattivato")
                concentration_threshold_pct = al5.number_input("Concentrazione soglia %", min_value=0.0, max_value=100.0, value=float(alerts_settings.get("concentration_threshold_pct") or 0.0), step=1.0, format="%.1f", help="0 = disattivato")
                al7, al8 = st.columns(2)
                drawdown_threshold_pct = al7.number_input("Drawdown soglia %", min_value=0.0, max_value=100.0, value=float(alerts_settings.get("drawdown_threshold_pct") or 0.0), step=1.0, format="%.1f", help="0 = disattivato")
                volatility_threshold_pct = al8.number_input("Volatilità soglia %", min_value=0.0, max_value=100.0, value=float(alerts_settings.get("volatility_threshold_pct") or 0.0), step=1.0, format="%.1f", help="0 = disattivato")
            _section_line()
            with st.container():
                    render_section_title(
                        t(settings, 'settings.domain.data', 'Lingua e formati'),
                        comment=t(settings, 'settings.domain.data_note', 'Preferenze locali per lingua, date e numeri.'),
                        icon="data",
                    )
                    st.markdown(f"**{t(settings, 'settings.section.i18n', 'Internazionalizzazione')}**")
                    st.markdown(f"<div class='summary-help'>{t(settings, 'settings.section.i18n_note', 'Preparazione per output multilingua e formati locali: in questo blocco definisci lingua, locale e convenzioni base per date e numeri.')}</div>", unsafe_allow_html=True)
                    i18n1, i18n2 = st.columns(2)
                    language_code = i18n1.selectbox("Lingua interfaccia/report", ["it", "en"], index=0 if str(i18n_settings.get("language", "it")).lower() == "it" else 1)
                    locale_code = i18n2.selectbox("Locale", ["it-IT", "en-US"], index=0 if str(i18n_settings.get("locale", "it-IT")) == "it-IT" else 1, disabled=True)
                    st.caption("🔒 Funzionalità futura: locale, formato data e formato numerico non sono ancora applicati — l'app mostra sempre date in formato italiano (DD/MM/YYYY) e numeri con virgola decimale, indipendentemente da questi selettori.")
                    i18n3, i18n4 = st.columns(2)
                    date_format_pref = i18n3.selectbox("Formato data", ["DD/MM/YYYY", "MM/DD/YYYY"], index=0 if str(i18n_settings.get("date_format", "DD/MM/YYYY")) == "DD/MM/YYYY" else 1, disabled=True)
                    number_format_pref = i18n4.selectbox("Formato numerico", ["it-IT", "en-US"], index=0 if str(i18n_settings.get("number_format", "it-IT")) == "it-IT" else 1, disabled=True)
            _section_line()
            with st.container():
                render_section_title(
                    "Avanzate",
                    comment="Strumenti tecnici per capire lentezze e gestire la preparazione anticipata dei grafici. Per l'uso quotidiano puoi lasciare i valori consigliati.",
                    icon="settings",
                )
                st.markdown(
                    f"""
                    <div class="settings-ops-guide">
                      <div class="settings-ops-guide__row" style="--guide-color:{theme.color_green};">
                        <span class="settings-ops-guide__tag">Uso normale</span>
                        <p class="settings-ops-guide__text">Lascia spenti i report tecnici e mantieni attiva la <strong>cache anticipata dei grafici</strong>.</p>
                      </div>
                      <div class="settings-ops-guide__row" style="--guide-color:{theme.color_orange};">
                        <span class="settings-ops-guide__tag">Se sembra lento</span>
                        <p class="settings-ops-guide__text">Attiva il <strong>report tempi a fondo pagina</strong> per capire quale pagina, grafico o tabella pesa di piu'.</p>
                      </div>
                      <div class="settings-ops-guide__row" style="--guide-color:{theme.color_blue};">
                        <span class="settings-ops-guide__tag">Diagnosi tecnica</span>
                        <p class="settings-ops-guide__text">Usa la <strong>diagnosi completa</strong> solo durante una revisione: misura tutte le pagine, ma rende il rerun piu' lento.</p>
                      </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                legacy_debug = bool(runtime_ui_settings.get("debug_render_monitor", False))
                debug_render_progress = st.checkbox(
                    "Mostra avanzamento tecnico in sidebar",
                    value=bool(runtime_ui_settings.get("debug_render_progress", legacy_debug)),
                    help="Aggiunge una piccola barra di avanzamento nella sidebar mentre Streamlit costruisce le pagine. Serve solo per diagnosi; non velocizza l'app.",
                )
                debug_render_log = st.checkbox(
                    "Mostra report tempi a fondo pagina",
                    value=bool(runtime_ui_settings.get("debug_render_log", legacy_debug)),
                    help="Mostra in fondo all'app un report copiabile con i tempi di rendering: utile per capire quale pagina, grafico o tabella rallenta il caricamento.",
                )
                debug_scope_options = [
                    "Normale: misura la UI reale",
                    "Diagnosi completa: misura tutte le pagine",
                ]
                debug_render_scope = st.selectbox(
                    "Misurazione tempi di caricamento",
                    debug_scope_options,
                    index=0 if str(runtime_ui_settings.get("debug_render_scope", "current_page")) == "current_page" else 1,
                    help="'Normale' misura il comportamento reale dell'app. 'Diagnosi completa' aggiunge un controllo pagina-per-pagina, piu' dettagliato ma piu' lento.",
                )
                st.caption(
                    "La misurazione tempi non cambia i calcoli e non migliora le prestazioni: serve solo a vedere dove si consuma tempo durante un rerun."
                )
                log_level = st.selectbox(
                    "Livello log applicativo",
                    ["DEBUG", "INFO", "WARNING", "ERROR"],
                    index=["DEBUG", "INFO", "WARNING", "ERROR"].index(
                        str(runtime_ui_settings.get("log_level", "INFO")).upper()
                    ) if str(runtime_ui_settings.get("log_level", "INFO")).upper() in ["DEBUG", "INFO", "WARNING", "ERROR"] else 1,
                    help="Controlla la verbosità del log applicativo generale portafoglio.log.",
                )
                st.markdown("**Cache anticipata dei grafici**")
                st.caption(
                    "Prepara in anticipo i grafici principali dopo un cambio dati, tema o impostazioni. "
                    "Modalita' consigliata: in background, cosi' l'avvio non resta bloccato."
                )
                pr1, pr2 = st.columns(2)
                pre_render_enabled = pr1.checkbox(
                    "Prepara i grafici in anticipo",
                    value=bool(pre_render_settings.get("enabled", True)),
                    help="Consigliato: costruisce in anticipo le figure piu' costose e le salva nella cache grafici. Disattivalo solo se vuoi avvii piu' leggeri durante prove o sviluppo.",
                )
                pre_render_initial_complete = pr2.checkbox(
                    "Blocca l'avvio per preparare subito",
                    value=bool(pre_render_settings.get("initial_complete", False)),
                    disabled=not pre_render_enabled,
                    help="Modalita' tecnica: se dati, tema o impostazioni sono cambiati, prepara subito le figure prima di completare il caricamento. Piu' pronta dopo, ma l'avvio puo' rallentare.",
                )
                pr3, pr4 = st.columns(2)
                pre_render_background_enabled = pr3.checkbox(
                    "Prepara in background senza bloccare",
                    value=bool(pre_render_settings.get("background_enabled", True)),
                    disabled=not pre_render_enabled,
                    help="Scelta consigliata: prepara le figure mentre continui a usare l'app. I benefici arrivano nei rerun successivi, senza aggiungere attesa all'avvio.",
                )
                pre_render_cooldown_minutes = pr4.number_input(
                    "Attendi almeno (min) prima di rifarlo",
                    min_value=1,
                    max_value=1440,
                    value=max(1, int(pre_render_settings.get("cooldown_seconds", 1800)) // 60),
                    step=5,
                    disabled=not pre_render_enabled,
                    help="Evita di ricostruire la cache troppo spesso. Esempio: 30 minuti significa che, a parita' di dati/tema, l'app non ripete subito la preparazione anticipata.",
                )
                st.caption(
                    "In pratica: tieni attiva la cache anticipata in background. Attiva il blocco avvio solo per prove tecniche mirate."
                )
                st.markdown("**Aggiornamento Mercati**")
                market_auto_refresh_settings = settings.get("market_auto_refresh", {})
                if not isinstance(market_auto_refresh_settings, dict):
                    market_auto_refresh_settings = {}
                st.caption(
                    "Scarica in background le quotazioni della pagina Mercati e aggiorna la cache senza forzare rerun. "
                    "La pagina mostrerà i nuovi dati al prossimo cambio pagina, click o aggiornamento manuale."
                )
                mr1, mr2 = st.columns(2)
                market_auto_refresh_enabled = mr1.checkbox(
                    "Aggiorna Mercati in background",
                    value=bool(market_auto_refresh_settings.get("enabled", False)),
                    help="Avvia un thread leggero che aggiorna la cache Mercati a intervalli regolari. Non cambia automaticamente la pagina aperta.",
                )
                market_auto_refresh_open_only = mr2.checkbox(
                    "Solo quando i mercati sono aperti",
                    value=bool(market_auto_refresh_settings.get("only_when_markets_open", True)),
                    disabled=not market_auto_refresh_enabled,
                    help="Evita download nei momenti in cui nessun riferimento dell'universo Mercati risulta aperto.",
                )
                mr3, mr4 = st.columns(2)
                market_auto_refresh_live_minutes = mr3.number_input(
                    "Live ogni (min)",
                    min_value=5,
                    max_value=240,
                    value=max(5, min(240, int(market_auto_refresh_settings.get("live_interval_minutes", 30) or 30))),
                    step=5,
                    disabled=not market_auto_refresh_enabled,
                    help="Intervallo per prezzi correnti e variazioni giornaliere degli indici.",
                )
                market_auto_refresh_history_enabled = mr4.checkbox(
                    "Aggiorna anche storico 6 mesi",
                    value=bool(market_auto_refresh_settings.get("history_enabled", True)),
                    disabled=not market_auto_refresh_enabled,
                    help="Aggiorna periodicamente anche le serie usate da rendimento, mini-andamenti e mappe forza relativa.",
                )
                market_auto_refresh_history_minutes = st.number_input(
                    "Storico ogni (min)",
                    min_value=60,
                    max_value=1440,
                    value=max(60, min(1440, int(market_auto_refresh_settings.get("history_interval_minutes", 240) or 240))),
                    step=30,
                    disabled=not (market_auto_refresh_enabled and market_auto_refresh_history_enabled),
                    help="Lo storico cambia meno spesso del live: 240 minuti è un buon compromesso tra freschezza e traffico dati.",
                )

            submitted_settings = st.form_submit_button("💾 Salva impostazioni", width="stretch", type="primary")
        if submitted_settings:
            try:
                if not str(portfolio_name or "").strip():
                    raise ValueError("Il nome del portafoglio è obbligatorio.")
                if not str(portfolio_code or "").strip():
                    raise ValueError("Il codice del portafoglio è obbligatorio.")
                if custom_benchmark_enabled and not component_rows:
                    raise ValueError("Configura almeno una componente con peso positivo per il benchmark personalizzato.")
                validate_number_input(float(rolling_window_days), 30, 365)
                validate_number_input(float(inflation_rate), 0, 50)
                validate_alert_thresholds(
                    float(loss_threshold_pct),
                    float(concentration_threshold_pct),
                    float(drawdown_threshold_pct),
                    float(volatility_threshold_pct),
                )

                settings["portfolio_id"] = str(portfolio_code).strip()
                settings["portfolio_profile"] = {
                    **settings.get("portfolio_profile", {}),
                    "portfolio_id": str(portfolio_code).strip(),
                    "portfolio_name": str(portfolio_name).strip(),
                    "description": str(portfolio_description or "").strip(),
                    "base_currency": base_currency,
                    "reporting_currency": reporting_currency,
                }
                settings["benchmarking"] = {
                    **settings.get("benchmarking", {}),
                    "default_portfolio_benchmark": bench_default,
                    "custom_enabled": bool(custom_benchmark_enabled),
                    "custom_name": str(custom_benchmark_name or "").strip(),
                    "custom_components": component_rows,
                }
                settings["category_view"] = {
                    **settings.get("category_view", {}),
                    "selected_categories": normalize_category_selection(selected_category_labels),
                }
                settings["calculations_metrics"] = {
                    **settings.get("calculations_metrics", {}),
                    "include_proventi_in_total_return": bool(include_proventi),
                    "rolling_window_days": int(rolling_window_days),
                    "inflation_rate": float(inflation_rate) / 100.0,
                }
                settings["alerts"] = {
                    **settings.get("alerts", {}),
                    "enabled": bool(alerts_enabled),
                    "risk_weight_monitoring": bool(alerts_risk_weight),
                    "loss_threshold_pct": float(loss_threshold_pct) if float(loss_threshold_pct) > 0 else None,
                    "concentration_threshold_pct": float(concentration_threshold_pct) if float(concentration_threshold_pct) > 0 else None,
                    "drawdown_threshold_pct": float(drawdown_threshold_pct) if float(drawdown_threshold_pct) > 0 else None,
                    "volatility_threshold_pct": float(volatility_threshold_pct) if float(volatility_threshold_pct) > 0 else None,
                }
                settings["ui_preferences"] = {
                    **settings.get("ui_preferences", {}),
                    "show_explanations": ui_show_explanations,
                    "show_portfolio_insights": ui_show_portfolio_insights,
                    "show_market_ticker_tape": ui_show_market_ticker_tape,
                    "quotazioni_full_resolution": ui_quotazioni_full_resolution,
                    "accent_variant": ui_accent_variant,
                    "font_scale": str(runtime_ui_settings.get("font_scale", "Grande")),
                    "log_level": str(log_level).upper(),
                    "debug_render_monitor": bool(debug_render_progress or debug_render_log),
                    "debug_render_progress": bool(debug_render_progress),
                    "debug_render_log": bool(debug_render_log),
                    "debug_render_scope": "full_sweep" if str(debug_render_scope).startswith("Diagnosi completa") else "current_page",
                    "page_mode": str(runtime_ui_settings.get("page_mode", "per_pagina")),
                }
                settings["i18n"] = {
                    "language": str(language_code or "it"),
                    "locale": str(locale_code or "it-IT"),
                    "date_format": str(date_format_pref or "DD/MM/YYYY"),
                    "number_format": str(number_format_pref or locale_code or "it-IT"),
                }
                settings["ui_pre_render"] = {
                    **settings.get("ui_pre_render", {}),
                    "enabled": bool(pre_render_enabled),
                    "initial_complete": bool(pre_render_initial_complete),
                    "background_enabled": bool(pre_render_background_enabled),
                    "cooldown_seconds": int(pre_render_cooldown_minutes) * 60,
                    "scope": str(pre_render_settings.get("scope", "core_charts_v1")),
                }
                settings["market_auto_refresh"] = {
                    **settings.get("market_auto_refresh", {}),
                    "enabled": bool(market_auto_refresh_enabled),
                    "live_interval_minutes": int(market_auto_refresh_live_minutes),
                    "history_enabled": bool(market_auto_refresh_history_enabled),
                    "history_interval_minutes": int(market_auto_refresh_history_minutes),
                    "only_when_markets_open": bool(market_auto_refresh_open_only),
                }
                # Appearance
                settings["operativo_mode"] = "sidebar"
                settings["sator_mode"] = "sidebar"
                settings["export_pp_mode"] = "sidebar"
                settings["appearance"] = {
                    **settings.get("appearance", {}),
                    "color_palette": ui_color_palette,
                    "typography": {
                        **_TYPO_STANDARD_SIZES,
                        "family": ui_font_family,
                    },
                    "visibility_mode": ui_visibility_mode,
                }
                settings_changed = save_settings(settings)
                logger.info(
                    "Impostazioni salvate: benchmark=%s changed=%s",
                    bench_default,
                    settings_changed,
                )
                if settings_changed:
                    queue_success("Impostazioni salvate")
                    invalidate_portfolio_cache("impostazioni salvate")
                    st.rerun()
                else:
                    record_cache_decision(
                        "impostazioni gia' aggiornate",
                        details={"material_change": False, "changed_count": 0},
                        invalidated=False,
                        scenario="settings_noop",
                        render_scope="full_tabs",
                        dirty_flags={},
                    )
                    st.info("Impostazioni gia' aggiornate: nessuna cache invalidata.")
            except ValueError as exc:
                logger.warning("Validazione impostazioni fallita: %s", exc)
                st.error(str(exc))

        # ── Configurazione AI ─────────────────────────────────────────────────────
        vertical_gap("sm")
        render_section_title(
            "Configurazione AI",
            comment="Chiave API Gemini e modello default. La chiave è salvata in chiaro in data/config/ai_config.json.",
            icon="settings",
        )

        ai_cfg = load_ai_config()
        stored_key = ai_cfg.get("api_key", "")
        key_hint = "●●●●●●●● (chiave salvata)" if stored_key else "Nessuna chiave salvata"

        st.caption(key_hint)
        st.caption("Ottieni o gestisci la tua chiave su [Google AI Studio](https://aistudio.google.com/app/apikey).")
        new_ai_key = st.text_input(
            "Chiave API Gemini",
            value="",
            type="password",
            placeholder="AIza...",
            key="_setup_ai_key_input",
        )
        new_ai_model = st.selectbox(
            "Modello default",
            options=GEMINI_MODELS,
            index=GEMINI_MODELS.index(ai_cfg.get("default_model", GEMINI_MODELS[0]))
                  if ai_cfg.get("default_model") in GEMINI_MODELS else 0,
            key="_setup_ai_model_select",
        )

        col_save, col_test, col_remove = st.columns(3)
        with col_save:
            if st.button("Salva configurazione AI", key="_setup_ai_save_btn", width="stretch"):
                key_to_save = new_ai_key.strip() if new_ai_key.strip() else stored_key
                if not key_to_save:
                    st.warning("Inserisci una chiave API prima di salvare.")
                else:
                    try:
                        save_ai_config(key_to_save, new_ai_model)
                        st.success("Configurazione AI salvata.")
                    except Exception as exc:
                        st.error(f"Errore salvataggio: {exc}")

        with col_test:
            if st.button("Testa connessione", key="_setup_ai_test_btn", width="stretch"):
                key_to_test = new_ai_key.strip() if new_ai_key.strip() else stored_key
                if not key_to_test:
                    st.warning("Inserisci o salva prima una chiave API.")
                else:
                    try:
                        result = test_gemini_connection(key_to_test, model=new_ai_model)
                        st.success(f"Connessione OK. Risposta: {result!r}")
                    except RuntimeError as exc:
                        st.error(str(exc))

        with col_remove:
            if st.button("Rimuovi chiave", key="_setup_ai_remove_btn", width="stretch"):
                try:
                    save_ai_config("", new_ai_model)
                    st.success("Chiave rimossa.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Errore: {exc}")

        st.caption(
            "⚠️ La chiave API è salvata in chiaro in `data/config/ai_config.json`. "
            "Non condividere questo file o includerlo in repository pubblici."
        )

        back_to_top(show_prev=True, show_next=False, nav_key="impostazioni")

    st.divider()
    st.caption(f"Sestante v{APP_VERSION} — {fmtd(date.today())}")
