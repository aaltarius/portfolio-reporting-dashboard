"""ui/pages/cruscotti.py — Tab Cruscotti: dashboard categoria GOV/ETF/FND."""

import html
import json
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import streamlit as st
from streamlit.delta_generator import DeltaGenerator

from core.asset_categories import get_selected_category_codes
from core.cache_signatures import build_historical_data_signature, build_portfolio_data_signature, charts_settings_signature, theme_signature
from core.domain.risk import build_drawdown_series
from core.figure_cache import CachingStrategy, get_figure_cache
from core.finance import calc_positions
from core.settings_profiles import get_effective_show_explanations, resolve_figure_cache_strategy
from core.series_utils import get_current_position_start_dates
from core.render_profiler import profile_step
from ui.components import back_to_top, kpi_card, legend_block, vertical_gap, render_styled_table, render_section_title, should_render_section, macro_legend_html
from ui.dashboard_bundles import get_analysis_category_dashboard_bundles, get_analitica_bundle, get_summary_dataset_bundle, get_advanced_analysis_dataset_bundle
from ui.formatting import fmt_dt_it, fmt_date_only_it, fmt_eur_it, fmt_num_it, fmt_pct_it
from ui.i18n import t
from ui.theme import P, get_theme_context, macro_color
from ui.charts.analisi import build_risk_contribution_chart
from ui.charts.home import build_category_allocation_pie_chart, build_category_bar_chart
from ui.charts.analisi import build_correlation_heatmap, build_instrument_drawdown_time_chart
from ui.charts.quotazioni import build_category_performance_comparison_time_chart
from ui.charts.operazioni import build_monthly_purchase_spending_time_chart, build_purchase_installments_chart
from ui.charts.calendario_btp import build_btp_calendar_figure, render_btp_calendar_table
from ui.charts.settings import apply_settings
from ui.charts.tables import color_pl, style_macro_cols
from ui.charts.summary import quarterly_table_html, monthly_heatmap_html
from core.services import get_category_allocation_breakdown, build_monthly_purchase_spending, get_portfolio_operations
from core.services.income_scadenze import build_income_scadenze_summary
from persistence.storage import macro_cat
from ui.page_chrome import render_page_intro as render_page_intro_shared
from ui.pages.cruscotti_accumuli import render_accumuli
from ui.pages.cruscotti_benchmark import render_benchmark
from ui.streamlit_compat import render_html_iframe


def _render_risk_contribution_analitica(bundle: Any) -> None:
    """Render risk contribution chart from bundle."""
    risk_fig = getattr(bundle, 'risk_contribution_figure', None)

    if risk_fig is None:
        st.info("Dati insufficienti per stimare il contributo al rischio.")
        return

    if hasattr(risk_fig, 'data') and len(risk_fig.data) == 0:
        st.info("Dati insufficienti per stimare il contributo al rischio.")
        return

    st.plotly_chart(risk_fig, width="stretch")
    legend_block("Se la barra del rischio è uguale o inferiore alla barra del peso, la situazione è equilibrata; se la supera, lo strumento pesa sulle oscillazioni più della sua quota.", variant="bottom")


def _format_dashboard_metric(metric: dict[str, Any]) -> tuple[str, str, str | None]:
    kind = str(metric.get("kind") or "")
    value = metric.get("value")
    note = str(metric.get("note") or "")
    value_color = None

    if kind == "date_with_duration":
        display = fmt_date_only_it(value) if value is not None else "—"
    elif kind == "date":
        display = fmt_date_only_it(value) if value is not None else "—"
    elif kind == "int":
        display = fmt_num_it(value, 0) if value is not None else "—"
    elif kind == "float2":
        display = fmt_num_it(value, 2) if value is not None else "—"
    elif kind == "eur":
        display = fmt_eur_it(value, 2) if value is not None else "—"
    elif kind == "eur_signed":
        display = fmt_eur_it(value, 2, signed=True) if value is not None else "—"
        if value is not None:
            value_color = P["green"] if float(value) >= 0 else P["red"]
    elif kind == "pct":
        display = fmt_pct_it(value, 2, signed=True) if value is not None else "—"
        if value is not None:
            value_color = P["green"] if float(value) >= 0 else P["red"]
    else:
        display = str(value) if value not in (None, "") else "—"

    return display, note, value_color


def _render_dashboard_metrics(metrics: list[dict[str, Any]], accent: str) -> None:
    for start in range(0, len(metrics), 4):
        row = metrics[start:start + 4]
        cols = st.columns(4)
        for idx, metric in enumerate(row):
            display, note, value_color = _format_dashboard_metric(metric)
            with cols[idx]:
                kpi_card(
                    str(metric.get("label") or "—"),
                    display,
                    note,
                    accent=accent,
                    value_color=value_color,
                )
        if start + 4 < len(metrics):
            vertical_gap("xs")


def _format_pl_horizon_cell(value: Any) -> str:
    try:
        if pd.isna(value):
            return "—"
        return fmt_eur_it(float(value), 0, signed=True)
    except Exception:
        return "—"


def _style_pl_horizon_total(row: pd.Series) -> list[str]:
    if str(row.get("Ticker") or "") != "TOTALE":
        return ["" for _ in row.index]
    return [
        "font-weight:800;background:rgba(59,130,246,0.08);border-top:2px solid rgba(59,130,246,0.22);"
        for _ in row.index
    ]


def _build_ticker_color_map(category_df: pd.DataFrame | None, fallback: str) -> dict[str, str]:
    if category_df is None or category_df.empty or "Ticker" not in category_df.columns:
        return {}
    type_col = "Tipo" if "Tipo" in category_df.columns else "Tipologia" if "Tipologia" in category_df.columns else None
    if type_col is None:
        return {}
    colors: dict[str, str] = {}
    for _, item in category_df.iterrows():
        ticker = str(item.get("Ticker") or "").strip()
        if not ticker:
            continue
        cat = macro_cat(str(item.get(type_col) or ""))
        colors[ticker] = macro_color(cat) if cat else fallback
    return colors


def _style_pl_horizon_ticker(row: pd.Series, ticker_colors: dict[str, str], fallback: str) -> list[str]:
    styles = ["" for _ in row.index]
    if "Ticker" not in row.index:
        return styles
    ticker_idx = list(row.index).index("Ticker")
    ticker = str(row.get("Ticker") or "")
    styles[ticker_idx] = (
        f"color:{ticker_colors.get(ticker, fallback)} !important;"
        "font-weight:900 !important;"
        "font-size:0.90rem !important;"
        "letter-spacing:0.01em;"
        "-webkit-text-stroke:0.25px currentColor;"
        "text-shadow:0 0 0 currentColor;"
    )
    return styles


def _pl_horizon_signal(row: pd.Series) -> str:
    values = []
    for col in ("5D", "3D", "1D"):
        try:
            value = float(row.get(col))
        except (TypeError, ValueError):
            return "n/d"
        if pd.isna(value):
            return "n/d"
        values.append(value)
    five_d, three_d, one_d = values
    if max(values) - min(values) < 1.0:
        return "→"
    if five_d <= three_d <= one_d:
        return "▲"
    if five_d >= three_d >= one_d:
        return "▼"
    return "◆"


def _style_pl_horizon_signal(row: pd.Series) -> list[str]:
    styles = ["" for _ in row.index]
    if "Trend" not in row.index:
        return styles
    signal_idx = list(row.index).index("Trend")
    signal = str(row.get("Trend") or "")
    if signal == "▲":
        styles[signal_idx] = f"color:{P['green']};font-weight:900;font-size:1.62rem;line-height:1;text-align:center !important;vertical-align:middle;"
    elif signal == "▼":
        styles[signal_idx] = f"color:{P['red']};font-weight:900;font-size:1.62rem;line-height:1;text-align:center !important;vertical-align:middle;"
    elif signal == "◆":
        styles[signal_idx] = f"color:{P['orange']};font-weight:900;font-size:1.42rem;line-height:1;text-align:center !important;vertical-align:middle;"
    elif signal == "→":
        styles[signal_idx] = f"color:{P['muted']};font-weight:900;font-size:1.62rem;line-height:1;text-align:center !important;vertical-align:middle;"
    else:
        styles[signal_idx] = f"color:{P['muted']};font-weight:700;text-align:center !important;vertical-align:middle;"
    return styles


def _style_pl_horizon_values(row: pd.Series, numeric_values: pd.DataFrame, partial_flags: pd.DataFrame) -> list[str]:
    styles = ["" for _ in row.index]
    for idx, col in enumerate(row.index):
        if col not in numeric_values.columns:
            continue
        value = numeric_values.loc[row.name, col] if row.name in numeric_values.index else None
        style = color_pl(value)
        try:
            is_partial = bool(partial_flags.loc[row.name, col]) if col in partial_flags.columns and row.name in partial_flags.index else False
        except Exception:
            is_partial = False
        if is_partial:
            style = f"color:{P['muted']} !important;font-weight:650;font-style:italic;background:rgba(148,163,184,0.10);"
        styles[idx] = style
    return styles


def _render_pl_horizon_table(table: pd.DataFrame, accent: str, category_df: pd.DataFrame | None = None) -> None:
    if table is None or table.empty:
        return
    source = table.copy()
    value_cols = [c for c in source.columns if c != "Ticker" and not str(c).startswith("_")]
    display = source[["Ticker", *value_cols]].copy()
    if "Trend" not in display.columns and {"1D", "3D", "5D"}.issubset(set(display.columns)):
        display.insert(1, "Trend", display.apply(_pl_horizon_signal, axis=1))
    horizon_cols = [c for c in display.columns if c not in {"Ticker", "Trend"}]
    numeric_values = pd.DataFrame(index=display.index)
    partial_flags = pd.DataFrame(False, index=display.index, columns=horizon_cols)
    for col in horizon_cols:
        numeric_values[col] = pd.to_numeric(source[col], errors="coerce")
        partial_col = f"_{col}_partial"
        if partial_col in source.columns:
            partial_flags[col] = source[partial_col].fillna(False).astype(bool)
        display[col] = [
            f"{_format_pl_horizon_cell(value)}{'*' if bool(is_partial) else ''}"
            for value, is_partial in zip(numeric_values[col], partial_flags[col])
        ]
    ticker_colors = _build_ticker_color_map(category_df, accent)

    styled = (
        display.style
        .hide(axis="index")
        .apply(lambda row: _style_pl_horizon_values(row, numeric_values, partial_flags), axis=1)
        .apply(lambda row: _style_pl_horizon_ticker(row, ticker_colors, accent), axis=1)
        .apply(_style_pl_horizon_signal, axis=1)
        .apply(_style_pl_horizon_total, axis=1)
        .set_properties(subset=["Ticker"], **{"font-weight": "800"})
        .set_table_styles(
            [
                {"selector": "table", "props": [("table-layout", "fixed"), ("width", "100%")]},
                {"selector": "th", "props": [("text-align", "right"), ("font-size", "0.80rem"), ("padding-left", "0.30rem"), ("padding-right", "0.30rem")]},
                {"selector": "th:first-child", "props": [("text-align", "left"), ("width", "13%")]},
                {"selector": "th:nth-child(2)", "props": [("text-align", "center"), ("width", "5%")]},
                {"selector": "th:nth-child(n+3)", "props": [("width", "9.1%")]},
                {"selector": "td", "props": [("text-align", "right"), ("font-variant-numeric", "tabular-nums"), ("font-size", "0.84rem"), ("padding-left", "0.35rem"), ("padding-right", "0.35rem"), ("white-space", "nowrap"), ("overflow", "hidden"), ("text-overflow", "ellipsis")]},
                {"selector": "td:first-child", "props": [("text-align", "left"), ("font-weight", "900 !important"), ("font-size", "0.90rem !important"), ("-webkit-text-stroke", "0.25px currentColor"), ("text-shadow", "0 0 0 currentColor")]},
                {"selector": "td:nth-child(2)", "props": [("text-align", "center !important"), ("vertical-align", "middle"), ("padding-left", "0.10rem"), ("padding-right", "0.10rem")]},
            ],
            overwrite=False,
        )
    )
    render_styled_table(styled, height="content", static=True)


def _render_radar_detail_box_local(
    title: str,
    unit_label: str,
    details: list[dict[str, Any]] | None,
    height: int | None = None,
) -> None:
    if not details:
        return
    theme = get_theme_context()
    text_color = theme.font_color
    parts = [
        "<div style='display:block;width:100%;'>",
        f"<div style='font-size:0.78rem;font-weight:800;text-transform:uppercase;letter-spacing:0.04em;margin-bottom:10px;text-align:center;color:{text_color};'>{html.escape(title)}</div>",
    ]
    for idx, item in enumerate(details, start=1):
        axis = html.escape(str(item.get("axis", "") or ""))
        value = item.get("value")
        amount = item.get("amount")
        method = html.escape(str(item.get("method", "") or ""))
        comparison = item.get("comparison")
        is_outside = bool(item.get("is_outside", False))
        if amount is None:
            value_txt = f"{fmt_num_it(value, 2) if value is not None else 'n/d'} / {unit_label}"
            if comparison is not None:
                value_txt += f" vs target {fmt_num_it(comparison, 2)} / {unit_label}"
        else:
            value_txt = (
                f"{fmt_pct_it((float(value or 0.0) / 100.0), 2)}"
                f" con controvalore {fmt_eur_it(float(amount or 0.0), 2)}"
            )
            if comparison is not None:
                value_txt += f" vs benchmark {fmt_pct_it((float(comparison or 0.0) / 100.0), 2)}"
        value_txt = html.escape(value_txt)
        method = method.replace("Formula:", "<span style='color:var(--ptf-primary);font-weight:800;'>Formula:</span>")
        method = method.replace("Qui:", "<span style='color:var(--ptf-primary);font-weight:800;'>Qui:</span>")
        method = method.replace("Strumenti agganciati:", "<span style='color:var(--ptf-primary);font-weight:800;'>Strumenti agganciati:</span>")
        method = method.replace("Nel tuo caso:", "<span style='color:var(--ptf-primary);font-weight:800;'>Nel tuo caso:</span>")
        method = method.replace("Il risultato finale è", "<span style='color:var(--ptf-primary);font-weight:800;'>Il risultato finale è</span>")
        value_color = theme.color_red if is_outside else theme.color_blue
        parts.append(
            f'<div style="margin-top:10px;">'
            f'<div style="font-size:0.92rem;font-weight:700;margin-bottom:3px;color:{text_color};">'
            f'{idx}. {axis}: <span style="color:{value_color};">{value_txt}</span>'
            f'</div>'
            f'<div style="font-size:0.82rem;line-height:1.45;">{method}</div>'
            f'</div>'
        )
    parts.append("</div>")
    st.markdown(
        f"<div class='leg leg-top' style='min-height:{height or 0}px'>{''.join(parts)}</div>",
        unsafe_allow_html=True,
    )


def _estimate_radar_detail_height(details: list[dict[str, Any]] | None) -> int:
    if not details:
        return 220
    base = 64
    total = base
    for item in details:
        method = str(item.get("method", "") or "")
        axis = str(item.get("axis", "") or "")
        value = str(item.get("value", "") or "")
        comparison = str(item.get("comparison", "") or "")
        text_len = len(method) + len(axis) + len(value) + len(comparison)
        extra_lines = max(1, (text_len // 150) + 1)
        total += 42 + (extra_lines * 16)
    return max(260, total + 20)


def _render_analitica_radar_section(bundle: Any) -> None:
    asset_radar = getattr(bundle, "asset_allocation_radar_figure", None)
    quality_radar = getattr(bundle, "quality_profile_radar_figure", None)
    radar_payload = bundle.radar_payload or {}
    if asset_radar is None and quality_radar is None:
        return

    render_section_title("Mappa Strategica del Portafoglio", icon="analysis")
    legend_block(
        "Due letture complementari del profilo di portafoglio: a sinistra la composizione per asset class in percentuale rispetto a un benchmark moderato; a destra un profilo qualitativo 0-10 in cui il valore alto rappresenta sempre la condizione desiderabile.",
        variant="bottom",
    )
    if isinstance(radar_payload, dict) and radar_payload.get("source_note"):
        st.caption(str(radar_payload.get("source_note")))
    vertical_gap("sm")
    radar_left, radar_right = st.columns(2, gap="medium")
    quantitative_detail = ((radar_payload or {}).get("quantitative") or {}).get("detail") if isinstance(radar_payload, dict) else None
    qualitative_detail = ((radar_payload or {}).get("qualitative") or {}).get("detail") if isinstance(radar_payload, dict) else None
    radar_detail_height = max(
        _estimate_radar_detail_height(quantitative_detail),
        _estimate_radar_detail_height(qualitative_detail),
    )
    with radar_left:
        kpi_card(
            "Allocazione Quantitativa",
            "Unità: %",
            "Confronto tra profilo attuale e benchmark moderato su 8 asset class",
            accent=bundle.theme.color_blue if getattr(bundle, "theme", None) else P["blue"],
        )
        st.markdown("<div style='height:14px;'></div>", unsafe_allow_html=True)
        if asset_radar is not None:
            st.plotly_chart(asset_radar, width="stretch")
        if quantitative_detail:
            _render_radar_detail_box_local(
                "Dettaglio valori radar quantitativo",
                "%",
                quantitative_detail,
                height=radar_detail_height,
            )
        st.markdown("<div style='height:10px;'></div>", unsafe_allow_html=True)
    with radar_right:
        kpi_card(
            "Profilo Qualitativo",
            "Unità: scala 0-10",
            "Valore alto sempre desiderabile, con confronto rispetto al profilo target",
            accent=bundle.theme.color_blue if getattr(bundle, "theme", None) else P["blue"],
        )
        st.markdown("<div style='height:14px;'></div>", unsafe_allow_html=True)
        if quality_radar is not None:
            st.plotly_chart(quality_radar, width="stretch")
        if qualitative_detail:
            _render_radar_detail_box_local(
                "Dettaglio valori radar qualitativo",
                "score",
                qualitative_detail,
                height=radar_detail_height,
            )
        st.markdown("<div style='height:10px;'></div>", unsafe_allow_html=True)
    st.markdown(
        f"""
        <div style="display:flex; justify-content:center; gap:26px; align-items:center; margin-top:4px; margin-bottom:6px; flex-wrap:wrap;">
            <div style="display:flex; align-items:center; gap:8px;">
                <span style="width:28px; height:0; border-top:3px solid {bundle.theme.color_blue if getattr(bundle, 'theme', None) else P['blue']}; display:inline-block;"></span>
                <span style="font-size:0.9rem; color:var(--ptf-text);">Portafoglio attuale</span>
            </div>
            <div style="display:flex; align-items:center; gap:8px;">
                <span style="width:28px; height:0; border-top:3px dashed rgba(107,114,128,0.95); display:inline-block;"></span>
                <span style="font-size:0.9rem; color:var(--ptf-text);">Benchmark / target di confronto</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    vertical_gap("sm")


def _render_category_dashboard(bundle: Any, show_explanations: bool) -> None:
    accent = macro_color(bundle.category)
    with profile_step("Cruscotti/UI", f"{bundle.category} - render header"):
        render_section_title(
            bundle.title,
            comment=bundle.intro_text if show_explanations else None,
            icon="analysis",
        )
    if bundle.df is None or bundle.df.empty:
        st.info(f"Nessun {bundle.category} presente nel portafoglio.")
        return

    with profile_step("Cruscotti/UI", f"{bundle.category} - render metrics", count=len(list(bundle.metrics or []))):
        _render_dashboard_metrics(list(bundle.metrics or []), accent)
    vertical_gap("sm")
    with profile_step("Cruscotti/UI", f"{bundle.category} - render compact figure"):
        st.plotly_chart(bundle.compact_figure, width="stretch")
    with profile_step("Cruscotti/UI", f"{bundle.category} - render temporal figure"):
        st.plotly_chart(bundle.temporal_figure, width="stretch")
    pie_left, pie_right = st.columns(2)
    with pie_left:
        with profile_step("Cruscotti/UI", f"{bundle.category} - render value pie"):
            st.plotly_chart(bundle.value_pie_figure, width="stretch")
    with pie_right:
        with profile_step("Cruscotti/UI", f"{bundle.category} - render capital pl pie"):
            st.plotly_chart(bundle.capital_pl_pie_figure, width="stretch")

    if getattr(bundle, "invested_vs_pl_figure", None) is not None:
        with profile_step("Cruscotti/UI", f"{bundle.category} - render invested vs pl section"):
            render_section_title("Investito vs P/L", icon="portfolio")
            st.plotly_chart(bundle.invested_vs_pl_figure, width="stretch")
    # Aggiungi drawdown e rendimenti mensili
    vertical_gap("sm")
    if bundle.drawdown_figure is not None:
        with profile_step("Cruscotti/UI", f"{bundle.category} - render drawdown section"):
            render_section_title("Drawdown", icon="risk")
            st.plotly_chart(bundle.drawdown_figure, width="stretch")
    if bundle.monthly_returns_figure is not None:
        with profile_step("Cruscotti/UI", f"{bundle.category} - render monthly returns section"):
            render_section_title("Rendimenti Mensili", icon="analysis")
            st.plotly_chart(bundle.monthly_returns_figure, width="stretch")
    pl_horizon_table = getattr(bundle, "pl_horizon_table", None)
    if pl_horizon_table is not None and not pl_horizon_table.empty:
        with profile_step("Cruscotti/UI", f"{bundle.category} - render P/L horizon table", count=len(pl_horizon_table)):
            render_section_title(
                "Contributo P/L per orizzonte",
                subtitle="Delta in euro per strumento: ▲ migliora, ▼ peggiora, ◆ misto, → stabile; * periodo parziale per storico insufficiente.",
                icon="analysis",
            )
            _render_pl_horizon_table(pl_horizon_table, accent, bundle.df)


def _render_analitica(bundle: Any) -> None:
    render_section_title(
        "Analisi Trasversale del Portafoglio",
        comment="Sette blocchi di analisi tecnica complementare: andamento del valore, scomposizione P/L, rendimento percentuale, scostamenti da target, contributo al rischio, attribution e mappa strategica.",
        icon="analysis",
    )

    render_section_title("Valore Patrimoniale nel Tempo", icon="portfolio")
    st.plotly_chart(bundle.portfolio_value_figure, width="stretch")
    legend_block("Vista patrimoniale: confronta valore di mercato, costo contabile e capitale versato. Versamenti e prelievi incidono sulle curve monetarie.", variant="bottom")

    render_section_title("Scomposizione P/L per Strumento", icon="analysis")
    st.plotly_chart(bundle.pl_decomposition_figure, width="stretch")
    legend_block("Rappresentazione cumulata che mostra come ciascuno strumento contribuisce al risultato totale di portafoglio nel tempo.", variant="bottom")

    render_section_title("Rendimento % sul Capitale nel Tempo", icon="analysis")
    st.markdown("<div title=\"Indicatore percentuale storico del risultato del portafoglio costruito sulla base del capitale registrato nello storico.\" style=\"margin-top:-0.45rem; margin-bottom:0.35rem; font-size:0.82rem; opacity:0.78;\">ⓘ</div>", unsafe_allow_html=True)
    st.plotly_chart(bundle.percentage_return_figure, width="stretch")
    legend_block("Andamento del rendimento percentuale del portafoglio nel tempo. Misura il guadagno rispetto al capitale versato.", variant="bottom")

    render_section_title("Waterfall Attribution della Performance", icon="analysis")
    st.markdown("<div title=\"Mostra il contributo al P/L per strumento sul risultato corrente del portafoglio.\" style=\"margin-top:-0.45rem; margin-bottom:0.35rem; font-size:0.82rem; opacity:0.78;\">ⓘ</div>", unsafe_allow_html=True)
    st.plotly_chart(bundle.performance_attribution_figure, width="stretch")
    legend_block("Waterfall che mostra il contributo di ogni strumento al P/L totale, dal maggiore al minore.", variant="bottom")

    # Metriche avanzate e Tracciabilità Reporting (spostate da Summary)
    summary_payload = bundle.summary_payload or {}
    reporting_pack = bundle.reporting_pack or {}
    reporting_pack_md = bundle.reporting_pack_md or ""
    _show_advanced_metrics = bundle.show_advanced_metrics
    _show_commentary = bundle.show_commentary
    _show_explanations = bundle.show_explanations
    _layout_full = bundle.layout_full
    _layout_analytic = bundle.layout_analytic
    include_methodology = bundle.include_methodology
    include_benchmark = bundle.include_benchmark
    schema_version = bundle.schema_version
    app_version = bundle.app_version
    theme_obj = bundle.theme

    _adv_metrics = [
        ("Sortino ratio", fmt_num_it(summary_payload.get("sortino"), 2) if summary_payload.get("sortino") is not None else "n/d",
         "Rendimento/rischio al ribasso (rf=0)", P["blue"], None),
        ("Calmar ratio", fmt_num_it(summary_payload.get("calmar"), 2) if summary_payload.get("calmar") is not None else "n/d",
         "CAGR / Max Drawdown", P["orange"], None),
        ("Information ratio", fmt_num_it(summary_payload.get("information_ratio"), 2) if summary_payload.get("information_ratio") is not None else "n/d",
         "Extra-rendimento / Tracking error", P["green"], None),
        ("Tracking error", fmt_pct_it(summary_payload.get("tracking_error"), 2) if summary_payload.get("tracking_error") is not None else "n/d",
         "Deviazione std. dei rendimenti in eccesso", P["muted"], None),
    ]
    if _show_advanced_metrics and any(summary_payload.get(k) is not None for k in ["sortino", "calmar", "information_ratio", "tracking_error"]):
        render_section_title("Metriche avanzate di rischio/rendimento", icon="risk")
        adv_cols = st.columns(4, gap="medium")
        for _col, _item in zip(adv_cols, _adv_metrics):
            with _col:
                kpi_card(_item[0], _item[1], _item[2], accent=_item[3], value_color=_item[4])
        _sortino_v = summary_payload.get("sortino")
        _calmar_v = summary_payload.get("calmar")
        _ir_v = summary_payload.get("information_ratio")
        _te_v = summary_payload.get("tracking_error")
        _sortino_note = (
            "eccellente (>2)" if _sortino_v and _sortino_v > 2
            else "buono (1–2): il portafoglio premia bene il rischio al ribasso" if _sortino_v and _sortino_v > 1
            else "accettabile (0–1): rendimento non del tutto proporzionato al rischio negativo" if _sortino_v and _sortino_v > 0
            else "negativo: il rendimento non compensa il rischio sopportato" if _sortino_v is not None
            else "n/d"
        )
        _calmar_note = (
            "ottimo (>1): il portafoglio rende più di quanto abbia mai perso nel suo peggior momento" if _calmar_v and _calmar_v > 1
            else "discreto (0.5–1)" if _calmar_v and _calmar_v > 0.5
            else "insoddisfacente (<0.5): il rendimento non compensa il drawdown storico" if _calmar_v is not None and _calmar_v >= 0
            else "negativo" if _calmar_v is not None
            else "n/d"
        )
        _ir_note = (
            "buona capacità di battere il benchmark in modo consistente (>0.5)" if _ir_v and _ir_v > 0.5
            else "lieve extra-rendimento (0–0.5)" if _ir_v and _ir_v > 0
            else "sotto il benchmark (<0): la gestione attiva non ha aggiunto valore" if _ir_v is not None
            else "n/d"
        )
        _te_note = (
            "portafoglio molto vicino al benchmark (<5%)" if _te_v and _te_v < 0.05
            else "gestione moderatamente attiva (5–15%)" if _te_v and _te_v < 0.15
            else "gestione molto attiva/differenziata (>15%): ampia divergenza dal benchmark" if _te_v
            else "n/d"
        )
        if _show_commentary:
            commentary_text = f"<div style='white-space: normal; word-wrap: break-word;'><strong>Come leggere le metriche avanzate</strong><br>• <strong>Sortino ratio {fmt_num_it(_sortino_v,2) if _sortino_v is not None else 'n/d'}</strong> — simile allo Sharpe ma penalizza solo i rendimenti negativi (non tutta la volatilità). Giudizio: {_sortino_note}.<br>• <strong>Calmar ratio {fmt_num_it(_calmar_v,2) if _calmar_v is not None else 'n/d'}</strong> — rapporto tra CAGR e massimo drawdown. Giudizio: {_calmar_note}.<br>• <strong>Information ratio {fmt_num_it(_ir_v,2) if _ir_v is not None else 'n/d'}</strong> — extra-rendimento rispetto al benchmark diviso il tracking error. Giudizio: {_ir_note}.<br>• <strong>Tracking error {fmt_pct_it(_te_v,2) if _te_v is not None else 'n/d'}</strong> — deviazione standard dei rendimenti in eccesso rispetto al benchmark. Giudizio: {_te_note}.</div>"
            legend_block(commentary_text, variant="bottom")

    # Tabella Rendimento e rischio per strumento (da quotazioni.py)
    if bundle.analysis_bundle and not bundle.analysis_bundle.dfstats.empty:
        # Soglie di validazione per la presentazione
        MIN_HISTORY_DAYS = 365
        MIN_VOLATILITY = 0.005
        MIN_DRAWDOWN = 0.005

        dfstats = bundle.analysis_bundle.dfstats.copy()

        display_cols = ["Ticker", "Strumento", "Rend. Tot.", "CAGR", "Volatilità Ann.", "Sharpe (rf 0%)", "Max Drawdown"]
        if "VaR 95%" in dfstats.columns:
            display_cols.extend(["VaR 95%", "CVaR 95%", "Sortino", "Calmar"])
        display_cols = [c for c in display_cols if c in dfstats.columns]

        # Prepara DataFrame con indicatori di validazione per ogni strumento
        display_df = dfstats[display_cols].copy()

        # Calcola indicatori di validazione
        history_valid = (dfstats["Giorni coperti"].astype(float) >= MIN_HISTORY_DAYS).values if "Giorni coperti" in dfstats.columns else [True] * len(dfstats)
        vol_significant = (pd.to_numeric(dfstats["Volatilità Ann."], errors="coerce") >= MIN_VOLATILITY).values if "Volatilità Ann." in dfstats.columns else [True] * len(dfstats)
        dd_significant = (pd.to_numeric(dfstats["Max Drawdown"], errors="coerce").abs() >= MIN_DRAWDOWN).values if "Max Drawdown" in dfstats.columns else [True] * len(dfstats)

        # Estrai categorie per colorare i ticker
        from persistence.storage import macro_cat
        ticker_categories = []
        for idx in range(len(dfstats)):
            tipo = dfstats.iloc[idx].get("Tipologia", "")
            category = macro_cat(tipo) if tipo else ""
            ticker_categories.append(category)

        # Formattazione
        format_dict = {
            "Rend. Tot.": lambda v: fmt_pct_it(v, 2, signed=True),
            "CAGR": lambda v: fmt_pct_it(v, 2, signed=True),
            "Volatilità Ann.": lambda v: fmt_pct_it(v, 2),
            "Sharpe (rf 0%)": lambda v: fmt_num_it(v, 2, signed=True),
            "Max Drawdown": lambda v: fmt_pct_it(v, 2),
            "VaR 95%": lambda v: fmt_pct_it(v, 2),
            "CVaR 95%": lambda v: fmt_pct_it(v, 2),
            "Sortino": lambda v: fmt_num_it(v, 2, signed=True),
            "Calmar": lambda v: fmt_num_it(v, 2, signed=True),
        }

        # Crea una mappa di indicatori per ogni cella (usata nel styling)
        cell_is_ns = {}  # (row_idx, col_name) -> True se cella deve mostrare "n.s."
        for idx in range(len(display_df)):
            # Regola 2: Sharpe e Sortino come "n.s." se volatilità < 0.5%
            if not vol_significant[idx]:
                if "Sharpe (rf 0%)" in display_cols:
                    cell_is_ns[(idx, "Sharpe (rf 0%)")] = True
                if "Sortino" in display_cols:
                    cell_is_ns[(idx, "Sortino")] = True

            # Regola 2b: Calmar come "n.s." se drawdown < 0.5%
            if not dd_significant[idx] and "Calmar" in display_cols:
                cell_is_ns[(idx, "Calmar")] = True

        def style_validation_row(row):
            """Applica stili: grigio per CAGR/Calmar con storico < 365gg, colore per valori negativi, grigio per n.s."""
            idx = row.name
            styles = [""] * len(row)

            for col_idx, col in enumerate(row.index):
                val = row.iloc[col_idx]

                # Ticker: colora in base alla categoria
                if col == "Ticker":
                    cat = ticker_categories[idx] if idx < len(ticker_categories) else ""
                    cat_color = macro_color(cat)
                    styles[col_idx] = f"color: {cat_color}; font-weight: 700;"

                # Regola 1: Grigio per CAGR e Calmar se storico < 365gg
                elif col in ["CAGR", "Calmar"] and not history_valid[idx]:
                    styles[col_idx] = "background-color: #e8e8e8; color: #999; opacity: 0.7;"

                # Regola 2: Grigio per "n.s." (non significativo)
                elif (idx, col) in cell_is_ns:
                    styles[col_idx] = "color: #999; font-style: italic;"

                # Regola 3: Colore rosso per valori negativi (Sharpe, Sortino, Calmar)
                elif col in ["Sharpe (rf 0%)", "Sortino", "Calmar"]:
                    try:
                        val_num = float(val)
                        if val_num < 0:
                            styles[col_idx] = "color: #d9534f; font-weight: 500;"
                    except (ValueError, TypeError):
                        pass

            return styles

        # Mantieni le colonne numeriche come numeriche.
        # Nota: se le trasformiamo prima in stringhe/object, Streamlit le considera testo
        # e tende ad allinearle a sinistra anche se lo Styler prova a dire "right".
        display_df_for_style = display_df.copy()

        # Per le celle "n.s." manteniamo comunque la colonna numerica:
        # impostiamo NaN e demandiamo allo Styler la visualizzazione testuale "n.s.".
        for (row_idx, col_name), is_ns in cell_is_ns.items():
            if is_ns and col_name in display_df_for_style.columns:
                display_df_for_style.loc[display_df_for_style.index[row_idx], col_name] = np.nan

        numeric_cols = [c for c in display_cols if c not in {"Ticker", "Strumento", "Tipologia"}]

        def _make_formatter(col_name):
            def _formatter(v):
                if pd.isna(v):
                    return "n.s." if col_name in {"Sharpe (rf 0%)", "Sortino", "Calmar"} else "—"
                try:
                    return format_dict[col_name](v)
                except Exception:
                    return str(v)
            return _formatter

        formatter_dict = {
            col: _make_formatter(col)
            for col in numeric_cols
            if col in format_dict
        }

        styled_stats = (
            display_df_for_style
            .style
            .format(formatter_dict)
            .apply(style_macro_cols, axis=1)
            .apply(style_validation_row, axis=1)
            .map(color_pl, subset=[c for c in ["Rend. Tot.", "Max Drawdown"] if c in display_cols])
        )

        if numeric_cols:
            styled_stats = styled_stats.set_properties(
                subset=numeric_cols,
                **{
                    "text-align": "right",
                    "font-variant-numeric": "tabular-nums",
                }
            )

        render_styled_table(
            styled_stats,
            column_config={"Strumento": st.column_config.TextColumn("Strumento", width="small")}
        )

        # Spiega le regole di validazione della presentazione
        validation_explanation = (
            "<div style='white-space: normal; word-wrap: break-word;'>"
            "<strong>Interpretazione delle celle:</strong><br>"
            "• <strong style='background-color: #e8e8e8; padding: 2px 4px;'>Sfondo grigio</strong> "
            "— CAGR e Calmar: storico inferiore a 365 giorni (valori annualizzati non rappresentativi).<br>"
            "• <strong style='color: #999; font-style: italic;'>n.s.</strong> — Sharpe/Sortino: volatilità "
            "inferiore allo 0,5% (indicatore non significativo). Calmar: drawdown inferiore allo 0,5%.<br>"
            "• <strong style='color: #d9534f;'>Rosso</strong> — Sharpe, Sortino, Calmar negativi "
            "(rendimento non compensa il rischio; non utilizzabili per il confronto tra strumenti).<br>"
            "• <strong>Normali</strong> — Rend. Tot., Volatilità Ann., Max Drawdown, VaR, CVaR: "
            "sempre mostrati indipendentemente dalle limitazioni sopra."
            "</div>"
        )
        legend_block(validation_explanation, variant="bottom")

    _qr = summary_payload.get("quarterly_returns", [])
    _mr = summary_payload.get("monthly_returns", [])
    _show_mr = bool(_mr) and (_layout_full or _layout_analytic)
    if _qr or _show_mr:
        render_section_title("Rendimenti mensili e trimestrali - mappe di calore", icon="metrics")
        _returns_blocks = []
        if _show_mr:
            _returns_blocks.append(monthly_heatmap_html(_mr, theme_obj))
        if _qr:
            _returns_blocks.append(quarterly_table_html(_qr, theme_obj))
        render_html_iframe("<div style='height:22px;'></div>".join(_returns_blocks), height="content")
        legend_block("Intensità del colore proporzionale alla dimensione del rendimento (verde positivo, rosso negativo); la legenda min/max sotto ogni tabella indica gli estremi osservati.", variant="bottom")

    render_section_title("Scostamento da Allocazione Target", icon="portfolio")
    st.plotly_chart(bundle.target_gap_figure, width="stretch")

    runtime_settings = st.session_state.get("_settings_runtime", {})
    objective = runtime_settings.get("portfolio_objective", {"core": 0.55, "difensivo": 0.25, "satellite": 0.20})
    target_comment = (
        f"Confronto tra composizione attuale e obiettivo di portafoglio: "
        f"Core {fmt_pct_it(objective.get('core', 0.0), 0)} / Difensivo {fmt_pct_it(objective.get('difensivo', 0.0), 0)} / "
        f"Satellite {fmt_pct_it(objective.get('satellite', 0.0), 0)}."
    )
    legend_block(target_comment, variant="bottom")

    render_section_title("Contributo al Rischio", icon="risk")
    # Renderizza direttamente il grafico del contributo al rischio (come in analisi.py)
    _render_risk_contribution_analitica(bundle)
    vertical_gap("sm")
    _render_analitica_radar_section(bundle)


def _render_analitica_market_structure(ctx: SimpleNamespace, settings: dict[str, Any], theme, cache_strategy: Any) -> None:
    dh_hist = getattr(ctx, "_dh_hist_shared", pd.DataFrame())
    dh_flow = getattr(ctx, "_dh_flow_shared", pd.DataFrame())
    analysis_bundle = getattr(ctx, "_advanced_analysis_bundle_v5", None)
    if dh_hist is None:
        dh_hist = pd.DataFrame()
    if dh_flow is None:
        dh_flow = pd.DataFrame()
    visible_categories = list(get_selected_category_codes(settings))
    categories_text = ", ".join(visible_categories)
    fcache = get_figure_cache()
    _app_version = str(getattr(ctx, "app_version", "n/d"))
    _schema_version = str(getattr(ctx, "schema_version", "n/d"))
    # Firma storica (end-of-day only, no prezzi live): stabile durante refresh intraday.
    # Usata per chart basati su dh_hist / cat_index_analysis / correlation — mai su prezzi correnti.
    _hist_sig = build_historical_data_signature(
        ctx.data,
        app_version=_app_version,
        schema_version=_schema_version,
    )
    _theme_sig = theme_signature(theme)
    _settings_sig = charts_settings_signature("ui/charts/settings.py")

    cat_index_analysis = getattr(analysis_bundle, "cat_index_analysis", pd.DataFrame()) if analysis_bundle is not None else pd.DataFrame()
    if isinstance(cat_index_analysis, pd.DataFrame) and not cat_index_analysis.empty and cat_index_analysis.shape[1] > 1:
        render_section_title(
            "Andamento omogeneizzato per macro-categoria",
            comment=(
                f"Indice base 100 per macro-categoria costruito sul rendimento aggregato delle categorie visibili ({categories_text}). "
                + macro_legend_html(settings)
            ),
            gap_after="xs",
        )
        fig = fcache.get_or_build(
            chart_id="quotazioni_category_performance_time_v2",
            data_sig=_hist_sig,
            theme_sig=_theme_sig,
            charts_settings_sig=_settings_sig,
            builder=lambda: build_category_performance_comparison_time_chart(cat_index_analysis, ctx.dfmt, chart_id="quotazioni_category_performance_time_v2"),
            page_mode="Completa",
            extra_params={"cache_bust": "cruscotti_macro_perf_transition_v5_open_position_window", "categories": "|".join(list(cat_index_analysis.columns))},
            strategy=cache_strategy,
        )
        st.plotly_chart(fig, width="stretch")

    if not dh_hist.empty and len(dh_hist) >= 2:
        render_section_title(
            "Drawdown dal massimo per strumento",
            comment="Profondità delle discese rispetto al massimo storico per i principali strumenti del portafoglio.",
            gap_after="xs",
        )
        da_frame = getattr(ctx, "da", pd.DataFrame())
        if isinstance(da_frame, pd.DataFrame) and not da_frame.empty and "Ticker" in da_frame.columns:
            qty_col = "Quote" if "Quote" in da_frame.columns else ("Quantita" if "Quantita" in da_frame.columns else None)
            work_positions = da_frame.copy()
            if qty_col is not None:
                work_positions = work_positions[pd.to_numeric(work_positions[qty_col], errors="coerce").fillna(0.0) > 0.0001]
            valid_tickers = [
                str(tk or "").strip()
                for tk in work_positions["Ticker"].astype(str).tolist()
                if str(tk or "").strip()
            ]
        else:
            valid_tickers = [str(s.get("ticker") or "") for s in (ctx.data.get("strumenti", []) or []) if str(s.get("ticker") or "").strip()]
        current_positions = calc_positions(ctx.data)
        position_starts = get_current_position_start_dates(ctx.data, current_positions)
        drawdown_depths = []
        for ticker in valid_tickers:
            if ticker not in dh_hist.columns:
                continue
            prices = pd.to_numeric(dh_hist[ticker], errors="coerce").dropna()
            start_date = position_starts.get(ticker)
            if start_date is not None:
                prices = prices.loc[prices.index >= start_date]
            if len(prices) < 2:
                continue
            # Rendimento percentuale dal primo prezzo disponibile: build_drawdown_series
            # converte in equity=1+v/100, un puro riscalamento moltiplicativo di prices
            # (prices/prices.iloc[0]) che lascia invariato il rapporto drawdown originale
            # (prices/prices.cummax()-1)*100, qualunque sia il livello assoluto dei prezzi.
            pct_returns = ((prices / prices.iloc[0]) - 1) * 100.0
            drawdown_min = min(build_drawdown_series(pct_returns.tolist()))
            drawdown_depths.append((ticker, float(drawdown_min)))
        drawdown_depths.sort(key=lambda item: item[1])
        drawdown_mode = st.radio(
            "Strumenti drawdown",
            ["6 peggiori", "Tutti"],
            horizontal=True,
            label_visibility="collapsed",
            key="cruscotti_analitica_drawdown_mode",
        )
        tickers_to_plot = [
            ticker
            for ticker, _depth in (drawdown_depths if drawdown_mode == "Tutti" else drawdown_depths[:6])
        ]
        if tickers_to_plot:
            fig = fcache.get_or_build(
                chart_id="quotazioni_instrument_drawdown",
                data_sig=_hist_sig,
                theme_sig=_theme_sig,
                charts_settings_sig=_settings_sig,
                builder=lambda: build_instrument_drawdown_time_chart(
                    dh_hist.loc[:, tickers_to_plot].where(
                        pd.DataFrame(
                            {
                                tk: dh_hist.index >= position_starts.get(tk, dh_hist.index.min())
                                for tk in tickers_to_plot
                            },
                            index=dh_hist.index,
                        )
                    ),
                    tickers_to_plot,
                    ctx.dfmt,
                ),
                page_mode="Completa",
                extra_params={"cache_bust": "cruscotti_drawdown_transition_v6_mode_open_position_window", "mode": drawdown_mode, "tickers": "|".join(tickers_to_plot)},
                strategy=cache_strategy,
            )
            st.plotly_chart(fig, width="stretch")

    analysis_bundle = getattr(ctx, "_advanced_analysis_bundle_v5", None)
    if analysis_bundle and analysis_bundle.corr is not None and not analysis_bundle.corr.empty:
        render_section_title(
            "Correlazione per strumento",
            comment="Mappa di correlazione dei rendimenti: utile per leggere concentrazione implicita e diversificazione reale.",
            gap_after="xs",
        )
        fig = fcache.get_or_build(
            chart_id="quotazioni_correlation_instruments",
            data_sig=_hist_sig,
            theme_sig=_theme_sig,
            charts_settings_sig=_settings_sig,
            builder=lambda: build_correlation_heatmap(analysis_bundle.corr, getattr(ctx, "CHART_BG", "#f9f9f9")),
            page_mode="Completa",
            extra_params={"cache_bust": "cruscotti_corr_instr_transition_v1", "tickers": "|".join(list(analysis_bundle.analysis_returns.columns))},
            strategy=cache_strategy,
        )
        st.plotly_chart(fig, width="stretch")

    if analysis_bundle and analysis_bundle.corr_cat is not None and not analysis_bundle.corr_cat.empty:
        render_section_title(
            "Correlazione per macro-categoria",
            comment=f"Correlazione sulle serie aggregate {categories_text}. Valori alti indicano movimenti insieme; bassi o negativi indicano compensazione.",
            gap_after="xs",
        )
        fig = fcache.get_or_build(
            chart_id="quotazioni_correlation_categories",
            data_sig=_hist_sig,
            theme_sig=_theme_sig,
            charts_settings_sig=_settings_sig,
            builder=lambda: build_correlation_heatmap(analysis_bundle.corr_cat, getattr(ctx, "CHART_BG", "#f9f9f9")),
            page_mode="Completa",
            extra_params={"cache_bust": "cruscotti_corr_cat_transition_v1", "categories": "|".join(list(analysis_bundle.cat_flow_returns.columns))},
            strategy=cache_strategy,
        )
        st.plotly_chart(fig, width="stretch")


def _render_reddito_scadenze(ctx: SimpleNamespace, settings: dict[str, Any], theme, cache_strategy: Any, *, data_sig: str, theme_sig: str, charts_settings_sig: str) -> None:
    render_section_title(
        "Reddito e Scadenze",
        comment="Lettura finanziaria orientata al carry del portafoglio governativo: reddito netto atteso, rendimento prospettico e timeline delle scadenze future.",
        icon="income",
    )
    calendar_df = getattr(ctx, "btp_calendar_df", pd.DataFrame())
    if calendar_df is None or calendar_df.empty:
        st.info("Nessun dataset GOV/BTP disponibile per costruire la vista reddito e scadenze.")
        return

    _income_cache_key = f"income_scadenze:{data_sig}"
    _income_cache = st.session_state.setdefault("_cruscotti_income_scadenze_cache", {})
    if _income_cache_key in _income_cache:
        summary = _income_cache[_income_cache_key]
    else:
        summary = build_income_scadenze_summary(ctx.data, getattr(ctx, "da", pd.DataFrame()), calendar_df)
        _income_cache.clear()  # una sola voce viva: la firma cambia ad ogni variazione dati rilevante
        _income_cache[_income_cache_key] = summary
    k1, k2, k3 = st.columns(3)
    with k1:
        kpi_card("Cedole attese 12 mesi", fmt_eur_it(summary["expected_net_income_12m"], 2), "reddito netto prospettico", accent=theme.color_green, value_color=theme.color_green)
    with k2:
        kpi_card("Rimborsi 12 mesi", fmt_eur_it(summary["expected_redemptions_12m"], 2), "capitale atteso a scadenza", accent=theme.color_orange, value_color=theme.color_orange)
    with k3:
        kpi_card("Yield su GOV attuali", fmt_pct_it(summary["yield_on_value_12m"], 2), "cedole 12 mesi / valore di mercato GOV", accent=theme.color_blue, value_color=theme.color_blue)
    vertical_gap("sm")

    if summary["gov_details_df"] is not None and not summary["gov_details_df"].empty:
        render_section_title(
            "Yield prospettico GOV per strumento",
            comment="Confronto tra controvalore residuo e cedole nette attese nei prossimi 12 mesi.",
            icon="income",
            gap_after="xs",
        )
        styled = summary["gov_details_df"].style.format({
            "Valore di Mercato": lambda v: fmt_eur_it(v, 2),
            "Cedole 12 mesi": lambda v: fmt_eur_it(v, 2),
            "Yield su valore": lambda v: fmt_pct_it(v, 2),
        })
        render_styled_table(styled, height="content")

    render_section_title(
        "Timeline BTP",
        comment="Timeline di possesso, cedole future e scadenze dei titoli di Stato presenti in portafoglio.",
        icon="income",
        gap_after="xs",
    )
    _da = getattr(ctx, "da", pd.DataFrame())
    _pmc_map: dict[str, float] = {}
    if not _da.empty and "Ticker" in _da.columns and "PMC" in _da.columns:
        for _, _row in _da.iterrows():
            _t = str(_row.get("Ticker") or "")
            _pmc = _row.get("PMC")
            if _t and _pmc is not None:
                try:
                    _pmc_map[_t] = float(_pmc)
                except (ValueError, TypeError):
                    pass
    fcache = get_figure_cache()
    fig = fcache.get_or_build(
        chart_id="cruscotti_btp_calendar",
        data_sig=data_sig,
        theme_sig=theme_sig,
        charts_settings_sig=charts_settings_sig,
        builder=lambda: build_btp_calendar_figure(calendar_df, theme, pmc_map=_pmc_map),
        page_mode="Completa",
        extra_params={"rows": len(calendar_df)},
        strategy=cache_strategy,
    )
    st.plotly_chart(fig, width="stretch")
    render_btp_calendar_table(calendar_df, theme, pmc_map=_pmc_map)


def _render_flussi_acquisti(ctx: SimpleNamespace, theme, *, data_sig: str, theme_sig: str, charts_settings_sig: str, cache_strategy: Any) -> None:
    fcache = get_figure_cache()
    render_section_title(
        "Flussi e Acquisti",
        comment="Lettura dei flussi di accumulo e della frequenza di acquisto degli strumenti non governativi presenti in portafoglio.",
        icon="operations",
    )
    monthly_purchase_df = build_monthly_purchase_spending(getattr(ctx, "data", {}).get("registro_eventi", []) or [])
    if not monthly_purchase_df.empty:
        render_section_title(
            "Spesa mensile per acquisto strumenti",
            comment="Mostra mese per mese quanto capitale è stato destinato agli acquisti di strumenti, separato dai movimenti di cassa non di investimento.",
            gap_after="xs",
        )
        monthly_fig = fcache.get_or_build(
            chart_id="cruscotti_flussi_monthly_spending",
            data_sig=data_sig,
            theme_sig=theme_sig,
            charts_settings_sig=charts_settings_sig,
            builder=lambda: apply_settings(build_monthly_purchase_spending_time_chart(monthly_purchase_df, theme), "andamento_monthly_spending"),
            page_mode="Completa",
            extra_params={"rows": len(monthly_purchase_df)},
            strategy=cache_strategy,
        )
        st.plotly_chart(monthly_fig, width="stretch")

    operations = getattr(ctx, "_operations_v5_cache", None)
    if operations is None:
        operations = get_portfolio_operations(getattr(ctx, "data", {}).get("registro_eventi", []) or [])
        setattr(ctx, "_operations_v5_cache", operations)
    if operations:
        info_map = {s["ticker"]: s for s in getattr(ctx, "data", {}).get("strumenti", [])}
        pmc_map = {}
        da = getattr(ctx, "da", None)
        if da is not None and not getattr(da, "empty", True) and "Ticker" in da.columns and "PMC" in da.columns:
            pmc_map = dict(zip(da["Ticker"], pd.to_numeric(da["PMC"], errors="coerce")))
        purchase_df = pd.DataFrame(operations)
        purchase_df = purchase_df[purchase_df.get("tipo_evento", "").eq("ACQUISTO")].copy()
        if not purchase_df.empty:
            purchase_df["category"] = purchase_df["ticker"].map(lambda tk: macro_cat(info_map.get(tk, {}).get("tipo", "")))
            purchase_summary = (
                purchase_df.groupby(["ticker"], dropna=False)
                .agg(
                    rate_count=("ticker", "size"),
                    min_price=("prezzo_unitario", "min"),
                    max_price=("prezzo_unitario", "max"),
                    qty_totale=("quantita", "sum"),
                )
                .reset_index()
                .rename(columns={"ticker": "Ticker"})
            )
            purchase_summary["category"] = purchase_summary["Ticker"].map(lambda tk: macro_cat(info_map.get(tk, {}).get("tipo", "")))
            purchase_summary["pmc"] = purchase_summary["Ticker"].map(pmc_map)
            purchase_summary = purchase_summary[purchase_summary["category"] != "GOV"].copy()
            if not purchase_summary.empty:
                render_section_title(
                    "Rate di acquisto per strumento",
                    comment="Conta quante volte gli strumenti ad accumulo sono stati acquistati e mette a confronto PMC attuale e range dei prezzi di acquisto.",
                    gap_after="xs",
                )
                installments_fig = fcache.get_or_build(
                    chart_id="cruscotti_flussi_installments",
                    data_sig=data_sig,
                    theme_sig=theme_sig,
                    charts_settings_sig=charts_settings_sig,
                    builder=lambda: apply_settings(build_purchase_installments_chart(purchase_summary, theme), "operations_purchase_installments"),
                    page_mode="Completa",
                    extra_params={"rows": len(purchase_summary)},
                    strategy=cache_strategy,
                )
                st.plotly_chart(installments_fig, width="stretch")


def _render_cruscotti_inner_nav(current_key: str, category_labels: list[str]) -> None:
    """Disabilitata: la barra iframe ripetuta in ogni sottoscheda Cruscotti
    duplicava componenti HTML/JS nascosti e rendeva la pagina molto più pesante
    rispetto alle altre aree.

    Le linguette Streamlit native restano disponibili in alto; il pulsante
    generale di navigazione della pagina resta renderizzato una sola volta a
    fondo pagina tramite back_to_top().
    """
    return

def render_cruscotti(tab: DeltaGenerator, ctx: SimpleNamespace) -> None:
    with tab:
        settings = getattr(ctx, "settings", {}) if hasattr(ctx, "settings") else {}
        theme = getattr(ctx, "theme", None) or get_theme_context()
        render_page_intro_shared(
            t(settings, "tab.dashboards", "Cruscotti"),
            t(settings, "page_intro.cruscotti.comment", "Hub analitico del portafoglio: cruscotti per categoria, letture trasversali, reddito GOV/BTP, flussi di acquisto e accumuli PAC."),
            "analysis",
            theme,
        )
        show_explanations = get_effective_show_explanations(settings) if isinstance(settings, dict) else True
        data_sig = build_portfolio_data_signature(
            ctx.data,
            app_version=str(getattr(ctx, "app_version", "n/d")),
            schema_version=str(getattr(ctx, "schema_version", "n/d")),
        )
        theme_sig = theme_signature(theme)
        settings_sig = charts_settings_signature("ui/charts/settings.py")
        cache_strategy_name = resolve_figure_cache_strategy(settings, st.session_state)
        if cache_strategy_name == "disabled":
            cache_strategy = CachingStrategy.DISABLED
        elif cache_strategy_name == "session_only":
            cache_strategy = CachingStrategy.SESSION_ONLY
        elif cache_strategy_name == "disk_only":
            cache_strategy = CachingStrategy.DISK_ONLY
        else:
            cache_strategy = CachingStrategy.HYBRID

        with profile_step("Cruscotti", "render dashboard categoria"):
            category_bundles = get_analysis_category_dashboard_bundles(
                dfh_top=ctx.dfh_top,
                da=ctx.da,
                data=ctx.data,
                settings=settings,
                dh_flow=ctx._dh_flow_shared,
                proventi=ctx.proventi,
                data_sig=data_sig,
                theme_sig=theme_sig,
                charts_settings_sig=settings_sig,
                cache_strategy=cache_strategy,
                theme=theme,
                app_version=str(getattr(ctx, "app_version", "n/d")),
                schema_version=str(getattr(ctx, "schema_version", "n/d")),
            )

        with profile_step("Cruscotti", "build summary dataset for analitica"):
            summary_bundle = get_summary_dataset_bundle(
                data=ctx.data,
                da_frame=ctx.da,
                portfolio_df=getattr(ctx, "df", pd.DataFrame()),
                liquidita=float(getattr(ctx, "liquidita_attuale", 0.0) or 0.0),
                settings=settings,
                last_quotes_update=getattr(ctx, "last_quotes_update", ctx.data.get("last_quotes_update")),
                proventi=getattr(ctx, "proventi", []),
                dfh=ctx.dfh_top,
                data_sig=data_sig,
                theme_sig=theme_sig,
                charts_settings_sig=settings_sig,
                render_mode="Completa",
                include_advanced=True,
                cache_strategy=cache_strategy,
                logic_version="5",
                build_figures=False,
            )

        with profile_step("Cruscotti", "render analitica bundle"):
            analitica_bundle = get_analitica_bundle(
                dfh_top=ctx.dfh_top,
                da=ctx.da,
                data=ctx.data,
                settings=settings,
                data_sig=data_sig,
                theme_sig=theme_sig,
                charts_settings_sig=settings_sig,
                cache_strategy=cache_strategy,
                theme=theme,
                dfmt=ctx.dfmt,
                pl_color=ctx.pl_color,
                pl_totale=ctx.pl_totale,
                radar_payload=getattr(ctx, "portfolio_radar_payload", None),
                dh_hist=getattr(ctx, "_dh_hist_shared", pd.DataFrame()),
                dh_flow=ctx._dh_flow_shared,
                proventi=ctx.proventi,
                summary_bundle=summary_bundle,
                schema_version=str(getattr(ctx, "schema_version", "n/d")),
                app_version=str(getattr(ctx, "app_version", "n/d")),
                show_advanced_metrics=True,
                show_commentary=True,
                show_explanations=show_explanations,
                layout_full=True,
                layout_analytic=True,
                include_methodology=True,
                include_benchmark=True,
                i18n_profile=None,
            )

        visible_categories = list(get_selected_category_codes(settings))
        ordered_categories = visible_categories + ["Tutto"]
        bundles_by_category = {bundle.category: bundle for bundle in category_bundles}
        tab_labels = [cat for cat in ordered_categories if cat in bundles_by_category]
        if not tab_labels:
            st.info("Nessun cruscotto categoria disponibile.")
            return

        setattr(ctx, "_advanced_analysis_bundle_v5", analitica_bundle.analysis_bundle)
        tab_labels_with_analitica = tab_labels + ["Analitica", "Benchmark", "Flussi & Acquisti", "Cedole & Scadenze", "Accumuli"]

        # Ancora reale usata dalla barra finale delle sottoschede per tornare
        # all'inizio dell'area Cruscotti dopo il cambio scheda.
        st.markdown('<div id="cruscotti-inner-top"></div>', unsafe_allow_html=True)

        with profile_step("Cruscotti", "create inner tabs", count=len(tab_labels_with_analitica), detail=",".join(tab_labels_with_analitica)):
            inner_tabs = st.tabs(tab_labels_with_analitica)
        for idx, category in enumerate(tab_labels):
            with inner_tabs[idx]:
                with profile_step("Cruscotti", f"render tab categoria {category}"):
                    _render_category_dashboard(bundles_by_category[category], show_explanations)
                    st.markdown("---")
                    _render_cruscotti_inner_nav(category, tab_labels_with_analitica)

        with inner_tabs[len(tab_labels)]:
            with profile_step("Cruscotti", "render tab Analitica"):
                _render_analitica(analitica_bundle)
                vertical_gap("sm")
                _render_analitica_market_structure(ctx, settings, theme, cache_strategy)

        with inner_tabs[len(tab_labels) + 1]:
            with profile_step("Cruscotti", "render tab Benchmark"):
                render_benchmark(ctx, summary_bundle=summary_bundle)

        with inner_tabs[len(tab_labels) + 2]:
            with profile_step("Cruscotti", "render tab Flussi & Acquisti"):
                _render_flussi_acquisti(ctx, theme, data_sig=data_sig, theme_sig=theme_sig, charts_settings_sig=settings_sig, cache_strategy=cache_strategy)

        with inner_tabs[len(tab_labels) + 3]:
            with profile_step("Cruscotti", "render tab Cedole & Scadenze"):
                _render_reddito_scadenze(ctx, settings, theme, cache_strategy, data_sig=data_sig, theme_sig=theme_sig, charts_settings_sig=settings_sig)

        with inner_tabs[len(tab_labels) + 4]:
            with profile_step("Cruscotti", "render tab Accumuli"):
                render_accumuli(ctx, show_explanations=show_explanations)

        with profile_step("Cruscotti", "render back_to_top finale"):
            back_to_top(show_prev=True, show_next=True, nav_key="cruscotti")
