from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from core.config import COLORS
from ui.charts.runtime import finalize_chart
from ui.formatting import fmt_num_it, hex_to_rgba

# La pagina ui/pages/andamento.py non esiste piu' (rinominata/assorbita da Cruscotti):
# le uniche due funzioni ancora vive in questo file sono le versioni "per categoria"
# usate dai Cruscotti. Le versioni a livello di intero portafoglio (portfolio_value,
# percentage_return, drawdown, monthly_returns, pl_decomposition,
# latest_instrument_pl) erano rimaste orfane — rimosse il 2026-07-07 dopo verifica
# che nessuna pagina le importasse piu' (sostituite da ui/charts/analitica.py).


def build_category_drawdown_time_chart(dfh, drawdown_series, chart_id, dfmt, theme):
    """Build drawdown chart for a category with parametric chart_id.

    Usato dai cruscotti per i grafici di drawdown per categoria.
    """
    fig = go.Figure(
        go.Scatter(
            x=dfh["Data"],
            y=drawdown_series,
            name="Drawdown %",
            line=dict(color=theme.color_red, width=2),
            fill="tozeroy",
            fillcolor=hex_to_rgba(theme.color_red, 0.12),
        )
    )
    fig.add_hline(y=0, line_dash="dot", line_color=hex_to_rgba(COLORS["gray"], 0.55), opacity=0.7)
    return finalize_chart(fig, chart_id, hovermode="x unified")


def build_category_monthly_returns_time_chart(monthly_data, chart_id, theme):
    """Build monthly returns chart for a category with parametric chart_id.

    Usato dai cruscotti per i grafici di rendimenti mensili per categoria.
    """
    dates = []
    for m_str in monthly_data["months"]:
        try:
            dates.append(pd.to_datetime(m_str + "-01"))
        except Exception:
            dates.append(pd.to_datetime(m_str))
    fig = go.Figure(
        go.Bar(
            x=dates,
            y=monthly_data["returns"],
            marker_color=[theme.color_green if v >= 0 else theme.color_red for v in monthly_data["returns"]],
            text=[fmt_num_it(v, 1, signed=True) + "%" for v in monthly_data["returns"]],
            textposition="outside",
            textfont=dict(size=10),
            name="Rendimento mensile",
            hovertemplate="%{x|%b %Y}: %{y:.2f}%<extra></extra>",
        )
    )
    fig.add_hline(y=0, line_dash="dot", line_color=hex_to_rgba(COLORS["gray"], 0.55), opacity=0.7)
    return finalize_chart(fig, chart_id)
