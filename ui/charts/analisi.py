from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from core.config import COLORS
from core.domain.returns import normalize_to_first
from core.domain.risk import build_drawdown_series
from ui.charts.settings import apply_settings
from ui.charts.runtime import empty_chart
from ui.formatting import fmt_pct_it, hex_to_rgba
from ui.styles import get_common_colors
from ui.theme import instrument_color, macro_color

# Ownership reale:
# - pagina: ui/pages/analisi.py
# - chart_id principali: analisi_risk_contribution2, analisi_correlation_heatmap,
#   analisi_instrument_drawdown
# build_target_gap_chart/build_performance_attribution rimosse il 2026-07-07:
# duplicate di ui/charts/analitica.py, che e' la versione realmente importata
# da ui/dashboard_bundles.py — verificato con grep sull'intero repo.


def build_risk_contribution_chart(risk_df):
    """Build risk contribution chart for Analisi.

    chart_id: analisi_risk_contribution2
    chiamato da: ui/pages/analisi.py
    """
    if risk_df is None or risk_df.empty:
        return empty_chart("analisi_risk_contribution2")
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
    colors = get_common_colors()
    fig = px.imshow(
        correlation_df,
        text_auto=".2f",
        color_continuous_scale=[(0.0, colors["negative"]), (0.5, chart_bg), (1.0, colors["primary"])],
        zmin=-1,
        zmax=1,
        aspect="auto",
    )
    # La matrice deve crescere con il numero di strumenti/categorie, non
    # restare fissa: settings.py fornisce solo il default per il caso
    # piccolo (poche categorie). force_heatmap_labels_and_square
    # (ui/charts/categories.py) da' priorita' a fig.layout.height/width se
    # gia' impostati qui, quindi questo e' il punto in cui la dimensione
    # dinamica va effettivamente applicata (prima non veniva mai scritta
    # sulla figura: bug reale, 2026-08-20 — matrice per strumenti,
    # tipicamente 20+ righe/colonne, schiacciata nel riquadro fisso da
    # 540px pensato per poche categorie, celle e testo illeggibili).
    fig.update_layout(height=dyn_height, width=dyn_height, margin=dict(b=dyn_bottom))
    # Font scalato sulla dimensione cella reale (dyn_height), non piu' su
    # un 540px presunto: con la matrice ora piu' grande per molti
    # strumenti, il font puo' restare vicino al massimo leggibile invece
    # di rimpicciolirsi senza motivo.
    cell_px = dyn_height / max(labels_count, 1)
    font_size = int(max(8, min(12, cell_px * 0.3)))
    fig.update_traces(textfont=dict(size=font_size, color=colors["text"]), hovertemplate="<b>%{x} vs %{y}</b><br>Correlazione: %{z:.3f}<extra></extra>")
    return apply_settings(fig, "analisi_correlation_heatmap")


def build_instrument_drawdown_time_chart(dh, tickers, date_fmt):
    """Build drawdown chart by instrument for Analisi.

    chart_id: analisi_instrument_drawdown
    chiamato da: ui/pages/analisi.py
    """
    _ = date_fmt
    if dh is None:
        return empty_chart("analisi_instrument_drawdown")
    fig = go.Figure()
    for ticker in tickers:
        prices = dh[ticker].dropna()
        if len(prices) < 2:
            continue
        # Rendimento normalizzato dal primo prezzo disponibile: build_drawdown_series
        # converte in equity=1+v/100, un puro riscalamento moltiplicativo che lascia
        # invariato il rapporto drawdown originale, qualunque sia il livello assoluto
        # dei prezzi. normalize_to_first è la stessa formula centralizzata in core/
        # (vedi core/services/sator.py per lo stesso pattern).
        pct_returns = normalize_to_first(prices, as_pct=True)
        if pct_returns.empty:
            continue
        drawdown = pd.Series(build_drawdown_series(pct_returns.tolist()), index=prices.index)
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
    fig.add_hline(y=0, line_dash="dot", line_color=hex_to_rgba(COLORS["gray"], 0.55), opacity=0.8)
    return apply_settings(fig, "analisi_instrument_drawdown")
