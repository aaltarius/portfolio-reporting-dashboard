"""
ui/pages/quotazioni.py — Tab Quotazioni (t2): diagnostica, storico prezzi, performance
Pure rendering using pre-computed data from PageContext.
"""
from types import SimpleNamespace
from typing import Any

import pandas as pd
import streamlit as st
from streamlit.delta_generator import DeltaGenerator

from core.asset_categories import get_selected_category_codes
from core.finance import build_ptf_df
from core.figure_cache import get_figure_cache, CachingStrategy
from core.cache_signatures import (
    build_cashflow_data_signature,
    build_historical_data_signature,
    build_market_data_signature,
    build_ticker_data_signature,
    theme_signature,
    charts_settings_signature,
)
from core.dashboard_datasets import get_quotazioni_dataset_bundle
from core.quotes_runtime import build_quotes_refresh_df
from core.settings_profiles import (
    get_effective_quotazioni_full_resolution,
    resolve_figure_cache_strategy,
    resolve_page_render_mode,
)

from persistence.storage import macro_cat
from ui.formatting import (
    fmt_dt_it, fmt_num_it, fmt_eur_it, fmt_pct_it, fmt_qty_it, fmtds,
)
from ui.i18n import t
from ui.theme import get_theme_context
from ui.components import (
    macro_legend_html, macro_color,
    legend_block, kpi_card, back_to_top,
    count_instruments_by_category, kpi_compact_category_html,
    render_styled_table,
    build_price_direction_map, render_section_title, vertical_gap, should_render_section,
)
from ui.charts.quotazioni import (
    build_category_performance_comparison_time_chart,
    build_instrument_performance_comparison_time_chart,
    build_quote_history_time_chart,
)
from ui.charts.analisi import (
    build_instrument_drawdown_time_chart,
    build_correlation_heatmap,
)
from ui.charts.tables import color_pl, style_macro_cols
from ui.charts.quotes_popup import render_quotes_table_with_popup
from ui.dashboard_bundles import get_advanced_analysis_dataset_bundle
from core.render_profiler import profile_step, record_render_event
from ui.page_chrome import render_page_intro as render_page_intro_shared

def _get_freshness_badge(last_refresh_dt: Any) -> str:
    """Ritorna emoji di freschezza basato su quanto tempo fa è avvenuto il refresh."""
    if not last_refresh_dt:
        return "⚪"
    try:
        from datetime import datetime
        if isinstance(last_refresh_dt, str):
            last_dt = datetime.fromisoformat(last_refresh_dt)
        else:
            last_dt = last_refresh_dt
        delta = datetime.now() - last_dt
        minutes = delta.total_seconds() / 60
        if minutes < 5:
            return "🟢"  # Fresco (< 5 min)
        elif minutes < 60:
            return "🟡"  # Recente (5-60 min)
        else:
            return "🔴"  # Stale (> 60 min)
    except Exception:
        return "⚪"


def _render_top_data_kpis(data: dict[str, Any], theme, settings: dict[str, Any] | None = None, chiusi_tickers: frozenset | None = None) -> None:
    """Mostra KPI per storico prezzi e strumenti per categoria."""
    _chiusi = chiusi_tickers or frozenset()
    c1, c2 = st.columns(2)
    with c1:
        sto = data.get("storico_prezzi", {})
        if sto:
            kpi_card(
                "Storico Prezzi",
                f"{len(sto)} giorni",
                f"Dal {fmtds(min(sto.keys()))} al {fmtds(max(sto.keys()))}",
                accent=theme.color_blue,
            )
        else:
            kpi_card("Storico Prezzi", "Nessuno", "Nessuna base storica disponibile", accent=theme.color_blue)

    with c2:
        strumenti_attivi_q = [s for s in data.get("strumenti", []) if str(s.get("ticker") or "") not in _chiusi]
        instrument_counts = count_instruments_by_category(strumenti_attivi_q, settings)
        st.markdown(
            kpi_compact_category_html(len(strumenti_attivi_q), instrument_counts, settings),
            unsafe_allow_html=True,
        )

def render_quotazioni(tab: DeltaGenerator, ctx: SimpleNamespace) -> None:
    """Pure rendering for quotazioni page."""
    # Get theme at function entry
    theme = get_theme_context()

    # Extract needed data from context
    data = ctx.data
    _dh_hist_shared = ctx._dh_hist_shared
    _dh_flow_shared = ctx._dh_flow_shared
    quotes_log = ctx.quotes_log
    settings = getattr(ctx, "settings", {}) if hasattr(ctx, "settings") else {}
    fmtd = ctx.fmtd
    fmtds = ctx.fmtds
    dfmt = ctx.dfmt

    # Compute cache signatures once per page load
    _quotes_data_sig = build_market_data_signature(
        data,
        app_version=str(getattr(ctx, "app_version", "n/d")),
        schema_version=str(getattr(ctx, "schema_version", "n/d")),
        include_benchmark_data=True,
    )
    _flow_data_sig = build_cashflow_data_signature(
        data,
        app_version=str(getattr(ctx, "app_version", "n/d")),
        schema_version=str(getattr(ctx, "schema_version", "n/d")),
        include_benchmark_data=False,
    )
    # Firma storica con operazioni (dh_flow = storico + prezzi operazioni, no prezzi live).
    # Stabile durante refresh intraday; cambia solo se nuovi dati storici o operazioni.
    _hist_flow_sig = build_historical_data_signature(
        data,
        app_version=str(getattr(ctx, "app_version", "n/d")),
        schema_version=str(getattr(ctx, "schema_version", "n/d")),
        include_operations=True,
    )
    _theme_sig = theme_signature(theme)
    _settings_sig = charts_settings_signature("ui/charts/settings.py")
    fcache = get_figure_cache()

    # Resolve cache strategy once, reuse for all figures
    _cache_strategy = resolve_figure_cache_strategy(settings, st.session_state)
    if _cache_strategy == "disabled":
        _cache_strategy = CachingStrategy.DISABLED
    elif _cache_strategy == "session_only":
        _cache_strategy = CachingStrategy.SESSION_ONLY
    elif _cache_strategy == "disk_only":
        _cache_strategy = CachingStrategy.DISK_ONLY
    else:
        _cache_strategy = CachingStrategy.HYBRID

    with tab:
        render_page_intro_shared(
            t(settings, "tab.quotes", "Quotazioni"),
            t(settings, "page_intro.quotazioni.comment", "Controllo operativo di refresh, storico prezzi e stato delle quotazioni disponibili sugli strumenti censiti."),
            "default",
            theme,
        )
        visible_categories = list(get_selected_category_codes(settings))
        categories_text = ", ".join(visible_categories)
        with profile_step("Quotazioni", "render KPI alto pagina"):
            _render_top_data_kpis(data, theme, settings, chiusi_tickers=getattr(ctx, "chiusi_tickers", frozenset()))
        vertical_gap("md")
        with profile_step("Quotazioni", "preparazione tabella diagnostica quotazioni"):
            _chiusi = getattr(ctx, "chiusi_tickers", frozenset())
            strumenti_attivi = [
                item for item in (data.get("strumenti", []) or [])
                if str(item.get("ticker") or "").strip()
                and str(item.get("ticker") or "").strip() not in _chiusi
            ]
            active_tickers = [str(item.get("ticker") or "").strip() for item in strumenti_attivi]
            qdf = getattr(ctx, "quotes_refresh_df", build_quotes_refresh_df(quotes_log, active_tickers)).copy()
            present_tickers = {
                str(tk or "").strip()
                for tk in (qdf["Ticker"].tolist() if "Ticker" in qdf.columns else [])
                if str(tk or "").strip()
            }
            missing_rows: list[dict[str, Any]] = []
            for item in strumenti_attivi:
                ticker = str(item.get("ticker") or "").strip()
                if not ticker or ticker in present_tickers:
                    continue
                missing_rows.append(
                    {
                        "Strumento": item.get("nome") or ticker,
                        "Ticker": ticker,
                        "Prezzo letto": None,
                        "Prezzo precedente": None,
                        "Var. vs prec.": None,
                        "Fonte": item.get("fonte") or "",
                        "Esito": "ASSENTE",
                        "Fallback": "No",
                        "Nota": "Nessuna lettura disponibile nel log quotazioni",
                        "Timestamp": "",
                    }
                )
            if missing_rows:
                qdf = pd.concat([qdf, pd.DataFrame(missing_rows)], ignore_index=True)
                qdf = qdf.sort_values(["Strumento", "Ticker"], kind="stable").reset_index(drop=True)
        if not qdf.empty and "Tipologia" not in qdf.columns:
            tipo_map = {
                str(s.get("ticker") or ""): macro_cat(s.get("tipo", ""))
                for s in data.get("strumenti", [])
            }
            qdf.insert(2, "Tipologia", qdf["Ticker"].map(lambda tk: tipo_map.get(str(tk or ""), "")))
        if qdf.empty:
            st.info(t(settings, "quotes.empty_log", "Nessun log quotazioni disponibile: esegui un aggiornamento per popolare la diagnostica."))
        else:
            q_stats = getattr(ctx, "quotazioni_stats", {"ok": 0, "warning": 0, "error": 0})
            k1, k2, k3, k4 = st.columns(4)
            with k1:
                badge = _get_freshness_badge(quotes_log.get("last_refresh"))
                kpi_card(f"{t(settings, 'quotes.last_refresh', 'Ultimo refresh')} {badge}", fmt_dt_it(quotes_log.get("last_refresh")), t(settings, "quotes.last_refresh_note", "Data e ora dell'ultima lettura"), accent=theme.color_blue)
            with k2:
                kpi_card(t(settings, "quotes.ok", "Letture OK"), fmt_num_it(q_stats["ok"], 0), t(settings, "quotes.ok_note", "Strumenti aggiornati correttamente"), accent=theme.color_green)
            with k3:
                kpi_card(t(settings, "quotes.warning", "Warning"), fmt_num_it(q_stats["warning"], 0), t(settings, "quotes.warning_note", "Fallback o valore mantenuto"), accent=theme.color_orange)
            with k4:
                kpi_card(t(settings, "quotes.errors", "Errori"), fmt_num_it(q_stats["error"], 0), t(settings, "quotes.errors_note", "Nessun nuovo valore disponibile"), accent=theme.color_red)
            vertical_gap("sm")
            render_section_title(
                "Ultime quotazioni aggiornate",
                subtitle=t(settings, "quotes.visible_count", "Letture visibili: {visible} strumenti su {total} presenti in portafoglio.").format(visible=len(qdf), total=sum(1 for s in data.get("strumenti", []) if str(s.get("ticker") or "") not in _chiusi)),
                comment=t(settings, "quotes.table_note", "La tabella riporta l'ultimo valore letto per ciascuno strumento, il confronto con il dato precedente e l'esito finale della lettura. Clicca sul ticker per aprire il dettaglio con grafico e ultime letture disponibili."),
                icon="quotes",
                gap_after="xs",
            )
            with profile_step("Quotazioni", "render tabella diagnostica quotazioni", count=len(qdf)):
                render_quotes_table_with_popup(qdf, data, quotes_log)

        dh = _dh_hist_shared
        if dh.empty:
            st.info(f"📌 {t(settings, 'quotes.history_empty', 'Aggiorna le quotazioni per popolare lo storico.')}")
        else:
            render_section_title(
                t(settings, "quotes.history_title", "Andamento Quotazioni con Benchmark"),
                comment=t(settings, "quotes.history_note", "Andamento del prezzo di ciascuno strumento normalizzato a 100 dalla prima data disponibile, con il benchmark di riferimento in arancione tratteggiato. L'asse verticale non indica il valore del capitale investito, ma la variazione percentuale del prezzo nel tempo."),
                icon="quotes",
                gap_after="xs",
            )

            chart_style = "Linea"

            _render_profile = resolve_page_render_mode(
                settings,
                local_mode=st.session_state.get("quotazioni_view_mode_fast_v1", "Rapida"),
            )
            _show_page_mode_controls = bool(_render_profile.get("show_controls", False))
            if _show_page_mode_controls:
                quick_options = ["Rapida", "Completa"]
                quotes_view_mode = st.radio(
                    "Modalità visualizzazione Quotazioni",
                    quick_options,
                    index=0,
                    horizontal=True,
                    key="quotazioni_view_mode_fast_v1",
                    help=(
                        "La vista Rapida evita il rendering iniziale di tutti i grafici per singolo strumento. "
                        "Usa Completa solo quando vuoi analizzare nel dettaglio ogni strumento con il relativo benchmark."
                    ),
                )
            else:
                quotes_view_mode = str(_render_profile.get("render_mode", "Rapida"))
            is_complete_view = quotes_view_mode == "Completa"
            if not is_complete_view and _show_page_mode_controls:
                st.info(
                    "Vista rapida attiva: per velocizzare il caricamento iniziale vengono mostrati i riepiloghi principali "
                    "e il grafico per macro-categoria. I grafici completi per singolo strumento e il confronto strumenti "
                    "sono disponibili selezionando 'Completa'."
                )

            show_ticker_detail_charts = True  # Abilita i grafici per strumento su 2 colonne (4.9.11)
            show_instrument_flow_chart = is_complete_view

            _closed_tk = tuple(sorted(getattr(ctx, "chiusi_tickers", frozenset())))
            quotazioni_bundle = get_quotazioni_dataset_bundle(
                data=data,
                dh_hist=dh,
                dh_flow=_dh_flow_shared,
                is_complete_view=is_complete_view,
                include_ticker_detail_charts=show_ticker_detail_charts,
                include_instrument_flow_chart=show_instrument_flow_chart,
                quotes_data_sig=_quotes_data_sig,
                flow_data_sig=_flow_data_sig,
                settings=settings,
                closed_tickers=_closed_tk,
                app_version=str(getattr(ctx, "app_version", "n/d")),
                schema_version=str(getattr(ctx, "schema_version", "n/d")),
            )
            tkd = quotazioni_bundle.valid_tickers
            info_map = quotazioni_bundle.info_map
            category_groups = quotazioni_bundle.category_groups

            # Render each category block separately only in complete mode.
            # This is the heaviest part of the Quotazioni page because it builds one Plotly chart per instrument
            # and may also trigger repeated benchmark Series preparation. Keep it opt-in to preserve the native tabs UX.
            def _get_category_color(cat: str) -> str:
                return macro_color(cat)

            _ptf_df = build_ptf_df(data)
            _portfolio_tickers: set[str] = set()
            if isinstance(_ptf_df, pd.DataFrame) and not _ptf_df.empty and "Ticker" in _ptf_df.columns:
                for _, _prow in _ptf_df.iterrows():
                    try:
                        _qty = float(_prow.get("Quote", 0) or 0)
                        _ctv = float(_prow.get("Controvalore", 0) or 0)
                    except Exception:
                        _qty = _ctv = 0.0
                    if abs(_qty) > 0 or abs(_ctv) > 0:
                        _portfolio_tickers.add(str(_prow.get("Ticker", "")))

            def _render_single_ticker_chart(item, chart_style, dfmt, theme, data, ctx, _theme_sig, _settings_sig, _cache_strategy, _portfolio_tickers, fcache, full_res):
                tk = item.ticker
                si = item.instrument_info
                in_portfolio = tk in _portfolio_tickers
                _pd = item.purchase_date
                _tk_data_sig = build_ticker_data_signature(
                    data, tk,
                    app_version=str(getattr(ctx, "app_version", "n/d")),
                    schema_version=str(getattr(ctx, "schema_version", "n/d")),
                )
                fig = fcache.get_or_build(
                    chart_id="quotazioni_quote_history",
                    data_sig=_tk_data_sig,
                    theme_sig=_theme_sig,
                    charts_settings_sig=_settings_sig,
                    builder=lambda t=tk, cs=chart_style, s_i=si, n=item.normalized_series, bs=item.benchmark_series, ip=in_portfolio, pd_=_pd, fr=full_res: build_quote_history_time_chart(t, s_i, n, bs, cs, dfmt, theme, in_portfolio=ip, purchase_date=pd_, full_resolution=fr),
                    page_mode="Rapida",
                    extra_params={"ticker": tk, "chart_style": chart_style, "in_portfolio": "1" if in_portfolio else "0", "purchase_date": str(_pd.date()) if _pd is not None else "", "full_resolution": "1" if full_res else "0"},
                    strategy=_cache_strategy,
                )
                st.plotly_chart(fig, width="stretch")

            _quotazioni_full_res = get_effective_quotazioni_full_resolution(settings)

            if quotazioni_bundle.ticker_bundles:
                for category in visible_categories:
                    bundles_in_category = [item for item in quotazioni_bundle.ticker_bundles if item.category == category]
                    if not bundles_in_category:
                        continue
                    with profile_step("Quotazioni", f"render grafici quotazioni categoria {category}", count=len(bundles_in_category)):
                        colore = _get_category_color(category)
                        st.markdown(f"<div style='margin-bottom: 24px; padding-bottom: 12px; border-bottom: 3px solid {colore};'><span style='font-size: 0.9rem; font-weight: 600; color: {colore}; text-transform: uppercase; letter-spacing: 0.05em;'>{category}</span></div>", unsafe_allow_html=True)

                        # Render tickers in 2-column layout within each category
                        for i in range(0, len(bundles_in_category), 2):
                            cols = st.columns(2)
                            for j, col in enumerate(cols):
                                if i + j >= len(bundles_in_category):
                                    break
                                item = bundles_in_category[i + j]
                                with col:
                                    with profile_step("Quotazioni", "build/render grafico singolo strumento", detail=str(item.ticker)):
                                        _render_single_ticker_chart(item, chart_style, dfmt, theme, data, ctx, _theme_sig, _settings_sig, _cache_strategy, _portfolio_tickers, fcache, _quotazioni_full_res)

                                    st.markdown("<div style='height: 24px;'></div>", unsafe_allow_html=True)

            # Build the per-instrument flow indices only when needed by the complete comparison chart.
            # In the previous layout this was executed on every app load even when the user only needed a quick overview.
            if is_complete_view and show_instrument_flow_chart:
                render_section_title(
                    t(settings, "quotes.instrument_perf", "Confronto Performance per Strumento"),
                    comment=t(settings, "quotes.instrument_perf_note", "Tutti gli strumenti sono riportati su una scala comune con base 100 ancorata alla data del primo investimento effettivo di ciascuna linea, usando prezzi storici integrati dalle date operative e corretti per i flussi reali di cassa. La vista predefinita mostra gli ultimi 3 mesi; usa i pulsanti o lo zoom per esplorare tutto lo storico disponibile."),
                    icon="analysis",
                    gap_after="xs",
                )
                if not quotazioni_bundle.instrument_flow_index_df.empty:
                    with profile_step("Quotazioni", "render confronto performance strumenti", count=len(tkd)):
                        fig = fcache.get_or_build(
                            chart_id="quotazioni_instrument_performance_time_v2",
                            data_sig=_hist_flow_sig,
                            theme_sig=_theme_sig,
                            charts_settings_sig=_settings_sig,
                            builder=lambda: build_instrument_performance_comparison_time_chart(quotazioni_bundle.instrument_flow_index_df, tkd, dfmt, chart_id="quotazioni_instrument_performance_time_v2"),
                            page_mode="Completa",  # Solo in modalità Completa
                            extra_params={
                                "cache_bust": "quotazioni_perf_time_v4",
                                "tickers": "|".join(tkd),
                            },
                            strategy=_cache_strategy,
                        )
                        st.plotly_chart(fig, width="stretch")
            else:
                record_render_event(
                    "Quotazioni",
                    "skip confronto performance strumenti",
                    0.0,
                    detail="confronto strumenti disattivato; abilita il toggle dedicato per costruire gli indici per singolo strumento",
                    count=len(tkd),
                )

        back_to_top(show_prev=False, show_next=True, nav_key="quotazioni")



