# LEGACY (2026-07-07): nessun importer nell'app viva (verificato con grep sull'intero
# repo). Non confondere con core/services/income_scadenze.py, che e' un file diverso
# e attivo (build_income_scadenze_summary, usato da Cruscotti).
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from ui.charts.runtime import empty_chart, finalize_chart


def build_income_projection_chart(future_income_df: pd.DataFrame, theme) -> go.Figure:
    if future_income_df is None or future_income_df.empty:
        return empty_chart("cruscotti_income_projection")
    df = future_income_df.copy()
    df["AnnoLabel"] = df["Anno"].astype(str)
    fig = go.Figure(
        go.Bar(
            x=df["AnnoLabel"],
            y=df["Cedole nette attese"],
            marker_color=theme.color_green,
            text=[f"€ {float(v):,.0f}".replace(",", ".") for v in df["Cedole nette attese"]],
            textposition="outside",
            hovertemplate="Anno %{x}<br>Cedole nette attese: %{y:,.2f} EUR<extra></extra>",
        )
    )
    fig = finalize_chart(
        fig,
        "cruscotti_income_projection",
        hovermode="x",
        xaxis_updates={"type": "category", "rangeselector": {"visible": False}},
    )
    fig.update_layout(updatemenus=[])
    return fig


def build_maturity_ladder_chart(maturity_df: pd.DataFrame, theme) -> go.Figure:
    if maturity_df is None or maturity_df.empty:
        return empty_chart("cruscotti_maturity_ladder")
    df = maturity_df.copy()
    df["AnnoLabel"] = df["Anno"].astype(str)
    fig = go.Figure(
        go.Bar(
            x=df["AnnoLabel"],
            y=df["Capitale a rimborso"],
            marker_color=theme.color_orange,
            text=[f"€ {float(v):,.0f}".replace(",", ".") for v in df["Capitale a rimborso"]],
            textposition="outside",
            hovertemplate="Anno %{x}<br>Capitale a rimborso: %{y:,.2f} EUR<extra></extra>",
        )
    )
    fig = finalize_chart(
        fig,
        "cruscotti_maturity_ladder",
        hovermode="x",
        xaxis_updates={"type": "category", "rangeselector": {"visible": False}},
    )
    fig.update_layout(updatemenus=[])
    return fig
