from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from core.series_resample import downsample_for_display
from ui.charts.base100 import apply_settings_base100, base100_hline_kwargs
from ui.charts.extrema import add_global_extrema_markers
from ui.formatting import hex_to_rgba
from ui.theme import instrument_color, macro_color

# Ownership reale:
# - pagina: ui/pages/quotazioni.py
# - chart_id principali: quotazioni_quote_history, quotazioni_instrument_performance,
#   analisi_category_performance


def build_quote_history_time_chart(ticker, instrument, normalized_series, benchmark_series, chart_style, dfmt, theme, in_portfolio: bool = True, purchase_date=None, full_resolution: bool = False):
    """Build quote history chart for a single ticker.

    chart_id: quotazioni_quote_history
    chiamato da: ui/pages/quotazioni.py

    full_resolution: se False (default), i dati oltre gli ultimi 90 giorni
    vengono mostrati a risoluzione settimanale invece che giornaliera (vedi
    core/series_resample.py). Riduce il numero di punti processati dalla
    pipeline di rendering senza alterare i valori mostrati (usa l'ultimo
    valore della settimana, non una media). Tocca solo questo grafico: i
    dati sorgente (normalized_series, benchmark_series) non vengono
    modificati, e nessun calcolo finanziario a monte usa questa funzione.
    """
    display_series = normalized_series if full_resolution else downsample_for_display(normalized_series)

    fig = go.Figure()
    fill_setting = "tozeroy" if chart_style == "Area" else None
    fillcolor_setting = hex_to_rgba(instrument_color(ticker), 0.15) if chart_style == "Area" else None
    fig.add_trace(
        go.Scatter(
            x=display_series.index,
            y=display_series.values,
            name=ticker,
            mode="lines",
            line=dict(color=instrument_color(ticker), width=2.5),
            fill=fill_setting,
            fillcolor=fillcolor_setting,
        )
    )
    if benchmark_series:
        bench_label, bench_dates, bench_values = benchmark_series
        if not full_resolution:
            bench_series_for_display = downsample_for_display(pd.Series(bench_values, index=pd.to_datetime(bench_dates)))
            bench_dates = bench_series_for_display.index
            bench_values = bench_series_for_display.values
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


def build_instrument_performance_comparison_time_chart(
    flow_index_df,
    tickers,
    dfmt,
    chart_id="quotazioni_instrument_performance",
    portfolio_series=None,
    portfolio_label="Portafoglio",
):
    """Build comparison chart by instrument in Quotazioni.

    chart_id: quotazioni_instrument_performance
    chiamato da: ui/pages/quotazioni.py
    """
    fig = go.Figure()
    plotted_series = {}
    for ticker in tickers:
        if ticker not in flow_index_df.columns:
            continue
        series = flow_index_df[ticker].dropna()
        if len(series) < 2:
            continue
        plotted_series[ticker] = series
        fig.add_trace(
            go.Scatter(
                x=series.index,
                y=series.values,
                name=ticker,
                mode="lines",
                line=dict(width=2.2, color=instrument_color(ticker)),
            )
        )
    if portfolio_series is not None:
        ref_series = pd.Series(portfolio_series).dropna()
        if len(ref_series) >= 2:
            fig.add_trace(
                go.Scatter(
                    x=ref_series.index,
                    y=ref_series.values,
                    name=portfolio_label,
                    mode="lines",
                    line=dict(width=1.8, color="rgba(31, 41, 55, 0.42)", dash="dot"),
                    opacity=0.72,
                    legendrank=999,
                    meta={"exclude_from_extrema": True, "role": "portfolio_reference"},
                    hovertemplate=f"{portfolio_label}: %{{y:.2f}}<extra></extra>",
                )
            )
    fig.add_hline(y=100, **base100_hline_kwargs(chart_id))
    if plotted_series:
        add_global_extrema_markers(fig, pd.DataFrame(plotted_series), chart_id)
    fig.update_layout(hovermode="x unified", uirevision="perf-strumento")
    return apply_settings_base100(fig, chart_id)


def build_category_performance_comparison_time_chart(cat_flow_index, dfmt, chart_id="analisi_category_performance"):
    """Build comparison chart by macro-category in Quotazioni.

    chart_id: analisi_category_performance
    chiamato da: ui/pages/quotazioni.py; prewarm da ui/prewarm_bundle.py
    """
    fig = go.Figure()
    plotted_series = {}
    for cat in list(cat_flow_index.columns):
        if cat in cat_flow_index.columns:
            series = cat_flow_index[cat].dropna()
            if len(series) >= 2:
                plotted_series[cat] = series
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
    if plotted_series:
        add_global_extrema_markers(fig, pd.DataFrame(plotted_series), chart_id)
    fig.update_layout(hovermode="x unified", uirevision="perf-categoria")
    return apply_settings_base100(fig, chart_id)
