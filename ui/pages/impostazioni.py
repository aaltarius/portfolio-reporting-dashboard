"""
ui/pages/impostazioni.py — Tab Impostazioni: configurazione strutturale.
Pure rendering - le operazioni amministrative vivono in Gestione Dati.
"""
import copy
import logging
from datetime import date
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
from persistence.storage import APP_VERSION, load_settings, save_settings
from core.finance import PORTFOLIO_BENCH_OPTIONS
from core.services.benchmark import resolve_effective_benchmark_components
from core.settings_profiles import (
    settings_change_is_diagnostic_only,
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
from core.validators import validate_alert_thresholds, validate_number_input
from ui.formatting import fmt_pct_it
from ui.theme import get_theme_context
from ui.notifications import queue_success
from ui.i18n import t
from ui.page_chrome import render_page_intro as render_page_intro_shared, render_section_line as render_section_line_shared
from core.section_visibility import PAGE_SECTIONS, build_custom_visibility, is_section_visible
from ui.components import (
    legend_block, back_to_top, kpi_card,
    render_styled_table,
    vertical_gap,
    render_section_title,
)

logger = logging.getLogger("portafoglio.ui.impostazioni")


def _render_page_intro(title: str, comment: str, icon: str = "default", theme=None) -> None:
    return render_page_intro_shared(title, comment, icon, theme)


def _section_line() -> None:
    return render_section_line_shared()


def _render_settings_overview(settings, benchmarking_settings, category_view_settings, theme) -> None:
    """Sintesi in sola lettura di come l'app è configurata adesso (valori salvati)."""
    market = settings.get("market_auto_refresh", {}) if isinstance(settings.get("market_auto_refresh"), dict) else {}
    profiles = settings.get("instrument_analysis_auto_refresh", {}) if isinstance(settings.get("instrument_analysis_auto_refresh"), dict) else {}
    network_on = [
        label for label, on in (
            ("benchmark 18:00", bool(benchmarking_settings.get("scheduler_enabled", False))),
            ("Mercati", bool(market.get("enabled", False))),
            ("profili strumenti", bool(profiles.get("enabled", False))),
        ) if on
    ]
    bench_name = (
        str(benchmarking_settings.get("custom_name") or "Personalizzato")
        if benchmarking_settings.get("custom_enabled")
        else str(benchmarking_settings.get("default_portfolio_benchmark", "Blend automatico"))
    )
    cols = st.columns(4, gap="small")
    with cols[0]:
        kpi_card("Benchmark di portafoglio", bench_name, "personalizzato" if benchmarking_settings.get("custom_enabled") else "scelto in elenco", accent=theme.color_blue)
    with cols[1]:
        kpi_card("Uso della rete", "Solo su comando" if not network_on else f"{len(network_on)} automatic{'o' if len(network_on) == 1 else 'i'}", ", ".join(network_on) if network_on else "nessun aggiornamento in background", accent=theme.color_green if not network_on else theme.color_orange)
    with cols[2]:
        kpi_card("Categorie attive", str(len(get_selected_category_codes(settings))), "perimetro di grafici e calcoli", accent=theme.color_purple)
    with cols[3]:
        kpi_card("Visibilità sezioni", str(settings.get("appearance", {}).get("visibility_mode", "Standard")), "preset di visualizzazione", accent=theme.color_red)
    vertical_gap("sm")


def render_impostazioni(tab: DeltaGenerator, ctx: SimpleNamespace) -> None:
    """Pure rendering for impostazioni page."""
    # Get theme at function entry
    theme = get_theme_context()

    # Extract needed data from context
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
        _render_settings_overview(settings, benchmarking_settings, category_view_settings, theme)
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
                # Valuta base/reporting: la conversione multi-valuta non esiste, ogni importo è in EUR.
                # I campi restano nel file impostazioni (invariati) ma non sono mostrati finché non servono.
                base_currency = str(portfolio_profile.get("base_currency", "EUR"))
                reporting_currency = str(portfolio_profile.get("reporting_currency", "EUR"))
                portfolio_description = st.text_area("Descrizione portafoglio", value=str(portfolio_profile.get("description", "")), height=80)
                bench_default = st.selectbox("Benchmark di portafoglio", PORTFOLIO_BENCH_OPTIONS, index=max(PORTFOLIO_BENCH_OPTIONS.index(benchmarking_settings.get("default_portfolio_benchmark", "Blend automatico")) if benchmarking_settings.get("default_portfolio_benchmark", "Blend automatico") in PORTFOLIO_BENCH_OPTIONS else 0, 0))
                st.caption("Indici ufficiali o ETF proxy dichiarati, conservati esclusivamente in SQLite; i componenti e le date devono avere una copertura comune.")
                st.caption("Il 60/40 seleziona automaticamente un riferimento azionario globale e uno obbligazionario con storico disponibile, esplicitando eventuali ETF proxy.")
                st.caption("L'obiettivo di portafoglio (Core/Difensivo/Satellite) e i radar della scheda Portafoglio si impostano ora in Pianificazione.")
                custom_benchmark_enabled = st.checkbox("Usa benchmark personalizzato", value=bool(benchmarking_settings.get("custom_enabled", False)))
                custom_benchmark_name = st.text_input("Nome benchmark personalizzato", value=str(benchmarking_settings.get("custom_name", "")), disabled=not custom_benchmark_enabled)
                current_components = benchmarking_settings.get("custom_components", []) if isinstance(benchmarking_settings.get("custom_components", []), list) else []
                from core.benchmark_discovery.portfolio import custom_component_options
                from core.verified_benchmarks import IndexStore
                component_options = dict(custom_component_options(IndexStore()))
                for _c in current_components:
                    _code = str((_c or {}).get("ticker", "")) if isinstance(_c, dict) else ""
                    if _code and _code not in component_options.values():
                        component_options[f"{_code} (non in archivio)"] = _code
                custom_component_choices = list(component_options) or ["Nessuna serie in archivio: esegui «Ricalcola la scelta»"]
                component_rows = []
                legend_block("Puoi definire un benchmark composito scegliendo fino a tre componenti e il loro peso relativo. I pesi vengono normalizzati automaticamente.")
                for idx in range(3):
                    existing = current_components[idx] if idx < len(current_components) and isinstance(current_components[idx], dict) else {}
                    existing_ticker = str(existing.get("ticker", ""))
                    reverse_label = next((label for label, ticker in component_options.items() if ticker == existing_ticker), custom_component_choices[0])
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
                    if custom_benchmark_enabled and float(component_weight) > 0 and component_options.get(selected_label):
                        component_rows.append({
                            "ticker": component_options.get(selected_label, ""),
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

                ui_show_portfolio_termometro = st.checkbox("Portafoglio: mostra Termometro",
                    value=bool(ui_preferences.get("show_portfolio_termometro", True)),
                    help="Mostra sopra la tabella del Portafoglio una lettura rapida dell'andamento: variazione su oggi, 5 giorni, 1 mese e da inizio anno, distanza dal picco, tessere per categoria e ampiezza (quanti strumenti salgono o scendono). Calcolata dai dati gia' in memoria, senza rete.",
                    key="appearance_show_portfolio_termometro",
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

                with st.expander("Sezioni per pagina (ON/OFF)", expanded=False):
                    st.caption(
                        "Accendi o spegni le singole sezioni di ogni pagina. Una sezione che non tocchi segue il "
                        "preset scelto qui sopra; solo le differenze dal preset vengono salvate. "
                        "Oggi sono configurabili le sezioni della pagina Portafoglio."
                    )
                    section_choices: dict[tuple[str, str], bool] = {}
                    section_initial: dict[tuple[str, str], bool] = {}
                    for _page_name, _section_names in PAGE_SECTIONS.items():
                        st.markdown(f"**{_page_name}**")
                        for _section_name in _section_names:
                            section_initial[(_page_name, _section_name)] = is_section_visible(_page_name, _section_name, settings)
                            section_choices[(_page_name, _section_name)] = st.checkbox(
                                _section_name,
                                value=section_initial[(_page_name, _section_name)],
                                key=f"section_visibility::{_page_name}::{_section_name}",
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
                loss_threshold_pct = al4.number_input("Perdita soglia % (0 = spenta)", min_value=0.0, max_value=100.0, value=float(alerts_settings.get("loss_threshold_pct") or 0.0), step=1.0, format="%.1f", help="0 = soglia spenta: l'avviso corrispondente non viene mai mostrato.")
                concentration_threshold_pct = al5.number_input("Concentrazione soglia % (0 = spenta)", min_value=0.0, max_value=100.0, value=float(alerts_settings.get("concentration_threshold_pct") or 0.0), step=1.0, format="%.1f", help="0 = soglia spenta: l'avviso corrispondente non viene mai mostrato.")
                al7, al8 = st.columns(2)
                drawdown_threshold_pct = al7.number_input("Drawdown soglia % (0 = spenta)", min_value=0.0, max_value=100.0, value=float(alerts_settings.get("drawdown_threshold_pct") or 0.0), step=1.0, format="%.1f", help="0 = soglia spenta: l'avviso corrispondente non viene mai mostrato.")
                volatility_threshold_pct = al8.number_input("Volatilità soglia % (0 = spenta)", min_value=0.0, max_value=100.0, value=float(alerts_settings.get("volatility_threshold_pct") or 0.0), step=1.0, format="%.1f", help="0 = soglia spenta: l'avviso corrispondente non viene mai mostrato.")
            _section_line()
            with st.container():
                    render_section_title(
                        t(settings, 'settings.domain.data', 'Lingua'),
                        comment=t(settings, 'settings.domain.data_note', 'Lingua di interfaccia e report.'),
                        icon="data",
                    )
                    language_code = st.selectbox("Lingua interfaccia/report", ["it", "en"], index=0 if str(i18n_settings.get("language", "it")).lower() == "it" else 1)
                    st.caption("Date e numeri restano sempre in formato italiano (GG/MM/AAAA, virgola decimale): locale e formati non sono configurabili.")
                    locale_code = str(i18n_settings.get("locale", "it-IT"))
                    date_format_pref = str(i18n_settings.get("date_format", "DD/MM/YYYY"))
                    number_format_pref = str(i18n_settings.get("number_format", "it-IT"))
            _section_line()
            with st.container():
                render_section_title(
                    "Aggiornamenti automatici in rete",
                    comment="Tutto ciò che può usare internet in background, in un solo posto. Sono spenti di default: gli aggiornamenti partono altrimenti solo quando premi i pulsanti (ADR-0018).",
                    icon="quotes",
                )
                benchmark_scheduler_enabled = st.checkbox("Benchmark: aggiorna ogni giorno alle 18:00 i prezzi dei benchmark scelti", value=bool(benchmarking_settings.get("scheduler_enabled", False)), help="Se lo attivi, l'aggiornamento parte all'avvio successivo dell'applicazione. Altrimenti i prezzi si aggiornano solo dai pulsanti in Cruscotti → Benchmark.")
                st.markdown("**Mercati**")
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
                st.markdown("**Profili strumenti (InstrumentAnalysis)**")
                instrument_analysis_auto_refresh_settings = settings.get("instrument_analysis_auto_refresh", {})
                if not isinstance(instrument_analysis_auto_refresh_settings, dict):
                    instrument_analysis_auto_refresh_settings = {}
                st.caption(
                    "Rinnova in background identità ufficiale, benchmark e Core/Difensivo/Satellite degli strumenti "
                    "prima che la cache scada: pochi strumenti per volta, con una pausa tra una richiesta e l'altra, "
                    "senza forzare rerun. Le pagine non aspettano mai la rete: se un dato è scaduto usano quello "
                    "precedente finché non viene rinnovato."
                )
                iar1, iar2 = st.columns(2)
                instrument_analysis_auto_refresh_enabled = iar1.checkbox(
                    "Aggiorna profili strumenti in background",
                    value=bool(instrument_analysis_auto_refresh_settings.get("enabled", False)),
                    help="Avvia un thread leggero che colma la cache InstrumentAnalysis a intervalli regolari, per gli strumenti non ancora coperti.",
                )
                instrument_analysis_auto_refresh_minutes = iar2.number_input(
                    "Ogni (min)",
                    min_value=15,
                    max_value=1440,
                    value=max(15, min(1440, int(instrument_analysis_auto_refresh_settings.get("interval_minutes", 15) or 15))),
                    step=15,
                    disabled=not instrument_analysis_auto_refresh_enabled,
                    help="Intervallo tra un ciclo e il successivo (ogni ciclo rinnova al massimo pochi strumenti).",
                )

            _section_line()
            with st.container():
                render_section_title(
                    "Avanzate",
                    comment="Strumenti tecnici per capire lentezze e gestire la preparazione anticipata dei grafici. Per l'uso quotidiano puoi lasciare i valori consigliati.",
                    icon="settings",
                )
                with st.expander("Opzioni avanzate (diagnostica e preparazione grafici)", expanded=False):
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

            submitted_settings = st.form_submit_button("💾 Salva impostazioni", width="stretch", type="primary")
        if submitted_settings:
            settings_before_save = copy.deepcopy(settings)
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
                    "scheduler_enabled": bool(benchmark_scheduler_enabled),
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
                    "show_portfolio_termometro": ui_show_portfolio_termometro,
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
                settings["instrument_analysis_auto_refresh"] = {
                    **settings.get("instrument_analysis_auto_refresh", {}),
                    "enabled": bool(instrument_analysis_auto_refresh_enabled),
                    "interval_minutes": int(instrument_analysis_auto_refresh_minutes),
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
                    # Solo le caselle toccate in questo salvataggio: le altre seguono
                    # il preset (anche se appena cambiato) o il loro override gia' salvato.
                    "custom_visibility": build_custom_visibility(
                        {key: value for key, value in section_choices.items() if value != section_initial[key]},
                        ui_visibility_mode,
                        settings.get("appearance", {}).get("custom_visibility"),
                    ),
                }
                settings_changed = save_settings(settings)
                logger.info(
                    "Impostazioni salvate: benchmark=%s changed=%s",
                    bench_default,
                    settings_changed,
                )
                if settings_changed:
                    queue_success("Impostazioni salvate")
                    if settings_change_is_diagnostic_only(settings_before_save, settings):
                        # Solo opzioni di diagnosi (log tempi, livello log): nessun calcolo cambia.
                        logger.info("Impostazioni di sola diagnosi: nessuna cache invalidata")
                    else:
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
                    st.info("Nessuna modifica da salvare.")
            except ValueError as exc:
                logger.warning("Validazione impostazioni fallita: %s", exc)
                st.error(str(exc))

        # ── Configurazione AI ─────────────────────────────────────────────────────
        vertical_gap("sm")
        render_section_title(
            "Configurazione AI",
            comment="Chiave API Gemini e modello predefinito, usati dalla pagina AI.",
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
                        test_gemini_connection(key_to_test, model=new_ai_model)
                        st.success("Connessione riuscita: chiave e modello funzionano.")
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
            "⚠️ La chiave API è salvata in chiaro in `data/config/ai_config.json` (cartella fuori da git) "
            "e non è inclusa nei backup: dopo un ripristino su un'altra macchina va reinserita."
        )

        back_to_top(show_prev=True, show_next=False, nav_key="impostazioni")

    st.divider()
    st.caption(f"Sestante v{APP_VERSION} — {fmtd(date.today())}")
