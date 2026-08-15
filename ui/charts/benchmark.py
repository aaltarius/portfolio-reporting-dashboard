from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from ui.charts.settings import apply_settings
from ui.theme import INSTRUMENT_PALETTE, P, macro_color


def build_portfolio_benchmark_comparison_chart(history: pd.DataFrame) -> go.Figure:
    """Curva Portafoglio vs Benchmark normalizzata a 100."""
    chart_id = "cruscotti_benchmark_comparison"
    fig = go.Figure()
    if history is None or history.empty or "date" not in history.columns:
        return apply_settings(fig, chart_id)
    plot = history.copy()
    plot["date"] = pd.to_datetime(plot["date"], errors="coerce")
    plot["portafoglio"] = pd.to_numeric(plot.get("portafoglio"), errors="coerce")
    plot["benchmark"] = pd.to_numeric(plot.get("benchmark"), errors="coerce")
    plot = plot.dropna(subset=["date", "portafoglio"]).sort_values("date")
    if plot.empty:
        return apply_settings(fig, chart_id)
    fig.add_trace(
        go.Scatter(
            x=plot["date"],
            y=plot["portafoglio"],
            mode="lines",
            name="Portafoglio",
            line=dict(color=P["blue"], width=2.8),
            hovertemplate="%{x|%d/%m/%Y}<br>Portafoglio: %{y:.2f}<extra></extra>",
        )
    )
    if plot["benchmark"].notna().sum() >= 2:
        fig.add_trace(
            go.Scatter(
                x=plot["date"],
                y=plot["benchmark"],
                mode="lines",
                name="Benchmark",
                line=dict(color=P["orange"], width=2.4, dash="dash"),
                hovertemplate="%{x|%d/%m/%Y}<br>Benchmark: %{y:.2f}<extra></extra>",
            )
        )
    fig.update_layout(
        height=430,
        margin=dict(l=8, r=8, t=42, b=16),
        title="Portafoglio vs Benchmark — base 100",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    fig.update_yaxes(title_text="Indice base 100", tickformat=",.1f", automargin=True, zeroline=False)
    fig.update_xaxes(automargin=True, rangeslider=dict(visible=False))
    return apply_settings(fig, chart_id)


def build_instrument_benchmark_scatter(matrix: pd.DataFrame) -> go.Figure:
    """Scatter Compatibilità vs Extra-rendimento per strumenti/benchmark."""
    chart_id = "cruscotti_benchmark_instrument_scatter"
    fig = go.Figure()
    if matrix is None or matrix.empty:
        return apply_settings(fig, chart_id)
    df = matrix.copy()
    df["compatibility_score"] = pd.to_numeric(df.get("compatibility_score"), errors="coerce")
    df["extra_return"] = pd.to_numeric(df.get("extra_return"), errors="coerce")
    df["controvalore"] = pd.to_numeric(df.get("controvalore"), errors="coerce").fillna(0.0)
    df = df.dropna(subset=["compatibility_score", "extra_return"])
    if df.empty:
        return apply_settings(fig, chart_id)
    max_value = max(float(df["controvalore"].max()), 1.0)
    df["marker_size"] = 14.0 + (df["controvalore"].clip(lower=0.0) / max_value) * 24.0
    for cat, sub in df.groupby(df.get("categoria", pd.Series(["ALTRO"] * len(df))).fillna("ALTRO")):
        fig.add_trace(
            go.Scatter(
                x=sub["compatibility_score"],
                y=sub["extra_return"],
                mode="markers+text",
                text=sub["ticker"],
                textposition="top center",
                name=str(cat),
                marker=dict(
                    size=sub["marker_size"],
                    color=macro_color(str(cat)),
                    opacity=0.82,
                    line=dict(color="rgba(17,24,39,0.28)", width=1),
                ),
                customdata=sub[["benchmark_label", "compatibility_label", "correlation", "tracking_error", "controvalore"]].to_numpy(),
                hovertemplate=(
                    "<b>%{text}</b><br>"
                    "Benchmark: %{customdata[0]}<br>"
                    "Compatibilità: %{customdata[1]} (%{x:.0%})<br>"
                    "Extra-rendimento: %{y:+.2%}<br>"
                    "Correlazione: %{customdata[2]:.2f}<br>"
                    "Tracking error: %{customdata[3]:.2%}<br>"
                    "Controvalore: € %{customdata[4]:,.0f}<extra></extra>"
                ),
            )
        )
    fig.add_hline(y=0, line_dash="dash", line_color="rgba(100,116,139,0.55)", line_width=1)
    fig.add_vrect(x0=0.0, x1=0.40, fillcolor="rgba(239,68,68,0.04)", line_width=0)
    fig.add_vrect(x0=0.78, x1=1.0, fillcolor="rgba(34,197,94,0.04)", line_width=0)
    fig.update_layout(
        height=430,
        margin=dict(l=8, r=8, t=42, b=42),
        title="Compatibilità benchmark vs extra-rendimento",
        hovermode="closest",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    fig.update_xaxes(title_text="Compatibilità benchmark", tickformat=".0%", range=[-0.03, 1.03], automargin=True, zeroline=False)
    fig.update_yaxes(title_text="Extra-rendimento", tickformat="+.0%", automargin=True, zeroline=True)
    return apply_settings(fig, chart_id)
