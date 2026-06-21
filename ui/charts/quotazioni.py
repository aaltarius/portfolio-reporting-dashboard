from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from core.series_utils import slice_recent
from ui.charts.base100 import apply_settings_base100, base100_hline_kwargs
from ui.charts.extrema import add_global_extrema_markers
from ui.formatting import hex_to_rgba
from ui.theme import instrument_color, macro_color

# Ownership reale:
# - pagina: ui/pages/quotazioni.py
# - chart_id principali: quotazioni_quote_history, quotazioni_instrument_performance,
#   analisi_category_performance


def build_quote_history_time_chart(ticker, instrument, normalized_series, benchmark_series, chart_style, dfmt, theme, in_portfolio: bool = True, purchase_date=None):
    """Build quote history chart for a single ticker.

    chart_id: quotazioni_quote_history
    chiamato da: ui/pages/quotazioni.py
    """
    fig = go.Figure()
    fill_setting = "tozeroy" if chart_style == "Area" else None
    fillcolor_setting = hex_to_rgba(instrument_color(ticker), 0.15) if chart_style == "Area" else None
    fig.add_trace(
        go.Scatter(
            x=normalized_series.index,
            y=normalized_series.values,
            name=ticker,
            mode="lines",
            line=dict(color=instrument_color(ticker), width=2.5),
            fill=fill_setting,
            fillcolor=fillcolor_setting,
        )
    )
    if benchmark_series:
        bench_label, bench_dates, bench_values = benchmark_series
        fig.add_trace(
            go.Scatter(
                x=bench_dates,
                y=bench_values,
                name=bench_label,
                mode="lines",
                line=dict(color=theme.color_orange, width=1.5, dash="dash"),
            )
        )
    fig.add_hline(y=100, **base100_hline_kwargs("quotazioni_quote_history"))
    if purchase_date is not None:
        try:
            fig.add_vline(
                x=pd.Timestamp(purchase_date).timestamp() * 1000,
                line_dash="dot",
                line_color="rgba(220,38,38,0.70)",
                line_width=1.5,
                annotation_text="Acquisto",
                annotation_position="top right",
                annotation_font_size=10,
                annotation_font_color="rgba(220,38,38,0.90)",
            )
        except Exception:
            pass
    quote_title_name = str(instrument.get("nome", "") or "").strip() if isinstance(instrument, dict) else ""
    quote_title_suffix = f" — {quote_title_name[:30]}" if quote_title_name else ""
    fig.update_layout(title=f"<b>{ticker}</b>{quote_title_suffix}", hovermode="x unified")
    fig = apply_settings_base100(fig, "quotazioni_quote_history")
    if not in_portfolio:
        fig.update_layout(
            paper_bgcolor="rgba(255,251,235,0.85)",
            modebar=dict(
                bgcolor="rgba(255,251,235,0.9)",
                color="rgba(161,117,40,0.75)",
                activecolor="rgba(120,80,20,1.0)",
            ),
        )
    return fig


def build_instrument_performance_comparison_time_chart(flow_index_df, tickers, dfmt, chart_id="quotazioni_instrument_performance"):
    """Build comparison chart by instrument in Quotazioni.

    chart_id: quotazioni_instrument_performance
    chiamato da: ui/pages/quotazioni.py
    """
    fig = go.Figure()
    for ticker in tickers:
        if ticker not in flow_index_df.columns:
            continue
        series = flow_index_df[ticker].dropna()
        if len(series) < 2:
            continue
        fig.add_trace(
            go.Scatter(
                x=series.index,
                y=series.values,
                name=ticker,
                mode="lines",
                line=dict(width=2.2, color=instrument_color(ticker)),
            )
        )
    fig.add_hline(y=100, **base100_hline_kwargs(chart_id))
    add_global_extrema_markers(fig, slice_recent(flow_index_df, 30), chart_id)
    fig.update_layout(hovermode="x unified", uirevision="perf-strumento")
    return apply_settings_base100(fig, chart_id)


def build_category_performance_comparison_time_chart(cat_flow_index, dfmt, chart_id="analisi_category_performance"):
    """Build comparison chart by macro-category in Quotazioni.

    chart_id: analisi_category_performance
    chiamato da: ui/pages/quotazioni.py; prewarm da ui/prewarm_bundle.py
    """
    fig = go.Figure()
    for cat in list(cat_flow_index.columns):
        if cat in cat_flow_index.columns:
            fig.add_trace(
                go.Scatter(
                    x=cat_flow_index.index,
                    y=cat_flow_index[cat],
                    name=cat,
                    mode="lines",
                    line=dict(width=2.8, color=macro_color(cat)),
                )
            )
    fig.add_hline(y=100, **base100_hline_kwargs(chart_id))
    add_global_extrema_markers(fig, slice_recent(cat_flow_index, 30), chart_id)
    fig.update_layout(hovermode="x unified", uirevision="perf-categoria")
    return apply_settings_base100(fig, chart_id)
