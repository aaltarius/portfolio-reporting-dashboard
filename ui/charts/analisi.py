from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from ui.charts.settings import apply_settings
from ui.formatting import fmt_eur_it, fmt_pct_it, hex_to_rgba
from ui.styles import get_common_colors
from ui.theme import P, instrument_color, macro_color

# Ownership reale:
# - pagina: ui/pages/analisi.py
# - chart_id principali: analisi_risk_contribution1, analisi_risk_contribution2,
#   analisi_correlation_heatmap, analisi_instrument_drawdown,
#   analisi_performance_attribution


def build_target_gap_chart(macro_target_df):
    """Build target allocation gap chart for Analisi.

    chart_id: analisi_risk_contribution1
    chiamato da: ui/pages/analisi.py
    """
    fig = go.Figure()
    peso_attuale = pd.to_numeric(macro_target_df["Peso attuale"], errors="coerce").fillna(0.0)
    fig.add_trace(
        go.Bar(
            y=macro_target_df["Categoria"],
            x=peso_attuale,
            orientation="h",
            name="Peso attuale",
            marker_color=[hex_to_rgba(macro_color(c), 0.45) for c in macro_target_df["Categoria"]],
            text=[fmt_pct_it(v, 1) for v in peso_attuale],
            textposition="outside",
            textfont=dict(size=10),
            cliponaxis=False,
            hovertemplate="%{y}<br>Peso attuale: %{x:.1%}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            y=macro_target_df["Categoria"],
            x=macro_target_df["Peso target"],
            name="Peso target",
            mode="markers",
            marker=dict(symbol="diamond-wide", size=12, color=P["orange"]),
            hovertemplate="%{y}<br>Peso target: %{x:.1%}<extra></extra>",
        )
    )
    fig.update_layout(barmode="overlay")
    return apply_settings(fig, "analisi_risk_contribution1")


def build_risk_contribution_chart(risk_df):
    """Build risk contribution chart for Analisi.

    chart_id: analisi_risk_contribution2
    chiamato da: ui/pages/analisi.py
    """
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            y=risk_df["Etichetta"],
            x=risk_df["Peso %"],
            orientation="h",
            name="Peso di mercato",
            marker_color=[hex_to_rgba(macro_color(c), 0.4) for c in risk_df["Categoria"]],
            text=[fmt_pct_it(v, 1) for v in risk_df["Peso %"]],
            textposition="outside",
        )
    )
    fig.add_trace(
        go.Bar(
            y=risk_df["Etichetta"],
            x=risk_df["Contributo rischio %"],
            orientation="h",
            name="Contributo al rischio",
            marker_color=[macro_color(c) for c in risk_df["Categoria"]],
            text=[fmt_pct_it(v, 1) for v in risk_df["Contributo rischio %"]],
            textposition="inside",
        )
    )
    fig.update_layout(barmode="group")
    return apply_settings(fig, "analisi_risk_contribution2")


def build_correlation_heatmap(correlation_df, chart_bg, height=470, bottom_margin=130, side_domain_pad=0.12):
    """Build correlation heatmap for instruments or categories.

    chart_id: analisi_correlation_heatmap
    chiamato da: ui/pages/analisi.py
    """
    labels_count = max(len(correlation_df.index), len(correlation_df.columns))
    dyn_height = max(height, min(640, 170 + labels_count * 34))
    dyn_bottom = max(bottom_margin, min(180, 30 + labels_count * 10))
    side_domain_pad = min(max(float(side_domain_pad), 0.0), 0.35)
    _ = dyn_height, dyn_bottom, side_domain_pad
    colors = get_common_colors()
    fig = px.imshow(
        correlation_df,
        text_auto=".2f",
        color_continuous_scale=[(0.0, colors["negative"]), (0.5, chart_bg), (1.0, colors["primary"])],
        zmin=-1,
        zmax=1,
        aspect="auto",
    )
    fig.update_traces(textfont=dict(size=12, color=colors["text"]), hovertemplate="<b>%{x} vs %{y}</b><br>Correlazione: %{z:.3f}<extra></extra>")
    return apply_settings(fig, "analisi_correlation_heatmap")


def build_instrument_drawdown_time_chart(dh, tickers, date_fmt):
    """Build drawdown chart by instrument for Analisi.

    chart_id: analisi_instrument_drawdown
    chiamato da: ui/pages/analisi.py
    """
    _ = date_fmt
    fig = go.Figure()
    for ticker in tickers:
        prices = dh[ticker].dropna()
        if len(prices) < 2:
            continue
        drawdown = (prices / prices.cummax() - 1) * 100
        fig.add_trace(
            go.Scatter(
                x=drawdown.index,
                y=drawdown.values,
                name=ticker,
                mode="lines",
                line=dict(width=2.4 if len(tickers) <= 6 else 1.8, color=instrument_color(ticker)),
            )
        )
    fig.update_layout(hovermode="x unified")
    fig.add_hline(y=0, line_dash="dot", line_color="rgba(107,114,128,0.55)", opacity=0.8)
    return apply_settings(fig, "analisi_instrument_drawdown")


def build_performance_attribution(da_frame, dfh):
    """Waterfall chart: contributo P/L di ogni strumento al totale.

    chart_id: analisi_performance_attribution
    chiamato da: ui/pages/analisi.py
    """
    _ = dfh
    if da_frame is None or da_frame.empty:
        fig = go.Figure()
        fig.add_trace(go.Waterfall(y=[0]))
        return apply_settings(fig, "analisi_performance_attribution")
    df = da_frame[["Ticker", "Strumento", "P/L €", "Tipo"]].copy()
    df = df.sort_values("P/L €", ascending=False)
    total = float(df["P/L €"].sum())
    fig = go.Figure(
        go.Waterfall(
            x=df["Ticker"].tolist() + ["TOTALE"],
            y=df["P/L €"].tolist() + [total],
            measure=["relative"] * len(df) + ["total"],
            connector=dict(line=dict(color="rgba(100,100,100,0.3)", width=1)),
            increasing=dict(marker_color=P["green"]),
            decreasing=dict(marker_color=P["red"]),
            totals=dict(marker_color=P["blue"]),
            text=[fmt_eur_it(v, 0, signed=True) for v in df["P/L €"].tolist() + [total]],
            textposition="outside",
            hovertemplate="%{x}<br>P/L: %{y:,.0f}€<extra></extra>",
        )
    )
    fig.update_layout(hovermode="x unified")
    return apply_settings(fig, "analisi_performance_attribution")
