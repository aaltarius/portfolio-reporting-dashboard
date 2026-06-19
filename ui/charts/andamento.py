from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from ui.charts.extrema import add_extrema_markers
from ui.charts.runtime import empty_chart, finalize_chart
from ui.formatting import fmt_eur_it, fmt_num_it, hex_to_rgba
from ui.theme import P, instrument_color

# Ownership reale:
# - pagina: ui/pages/andamento.py
# - chart_id principali: andamento_portfolio_value, andamento_pl_decomp_stacked,
#   andamento_pl_decomp_grouped, andamento_percentage_return, andamento_drawdown,
#   andamento_monthly_returns, summary_latest_instrument_pl


def build_portfolio_value_time_chart(dfh, dfmt, theme):
    """Build standalone portfolio value chart.

    chart_id: andamento_portfolio_value
    chiamato da: ui/pages/andamento.py e ui/prewarm_bundle.py
    """
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=dfh["Data"],
            y=dfh["Valore"],
            name="Valore di Mercato",
            line=dict(color=theme.color_blue, width=2.5),
            fill="tozeroy",
            fillcolor=hex_to_rgba(theme.color_blue, 0.08),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=dfh["Data"],
            y=dfh["Costo"],
            name="Costo Contabile",
            line=dict(color=theme.color_orange, width=2, dash="dash"),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=dfh["Data"],
            y=dfh["Capitale"],
            name="Capitale Versato",
            line=dict(color=theme.color_gray, width=1.5, dash="dashdot"),
        )
    )
    return finalize_chart(fig, "andamento_portfolio_value", hovermode="x unified", uirevision="andamento-value")


def build_percentage_return_time_chart(dfh, pct_cap, pct_cost, pl_color, pl_total, dfmt, theme):
    """Build percentage return chart for Andamento.

    chart_id: andamento_percentage_return
    chiamato da: ui/pages/andamento.py e ui/prewarm_bundle.py
    """
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=dfh["Data"],
            y=pct_cap,
            name="Rend. su Capitale %",
            line=dict(color=pl_color, width=2.5),
            fill="tozeroy",
            fillcolor=hex_to_rgba(theme.color_green, 0.08) if pl_total >= 0 else hex_to_rgba(theme.color_red, 0.08),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=dfh["Data"],
            y=pct_cost,
            name="Rend. su Costo %",
            line=dict(color=theme.color_orange, width=1.8, dash="dash"),
        )
    )
    fig.add_hline(y=0, line_dash="dot", line_color="rgba(107,114,128,0.55)", opacity=0.8)
    return finalize_chart(fig, "andamento_percentage_return", hovermode="x unified", uirevision="rend-capitale")


def build_portfolio_drawdown_time_chart(dfh, drawdown_series, dfmt, theme):
    """Build portfolio drawdown chart for Andamento.

    chart_id: andamento_drawdown
    chiamato da: ui/pages/andamento.py e ui/prewarm_bundle.py
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
    fig.add_hline(y=0, line_dash="dot", line_color="rgba(107,114,128,0.55)", opacity=0.7)
    return finalize_chart(fig, "andamento_drawdown", hovermode="x unified", uirevision="drawdown-ptf")


def build_monthly_returns_time_chart(monthly_data, theme):
    """Build monthly returns bar chart for Andamento.

    chart_id: andamento_monthly_returns
    chiamato da: ui/pages/andamento.py e ui/prewarm_bundle.py
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
    fig.add_hline(y=0, line_dash="dot", line_color="rgba(107,114,128,0.55)", opacity=0.7)
    return finalize_chart(fig, "andamento_monthly_returns")


def build_pl_decomposition_time_chart(dfh, pl_cols, viz_mode, dfmt, theme):
    """Build P/L contribution by instrument for Andamento.

    chart_id runtime: andamento_pl_decomp_stacked oppure andamento_pl_decomp_grouped
    chiamato da: ui/pages/andamento.py; stacked anche da ui/prewarm_bundle.py
    """
    _ = dfmt
    fig = go.Figure()
    for col in pl_cols:
        tk = col[3:]
        stackgroup = "pl" if viz_mode == "Stacked" else None
        fig.add_trace(
            go.Scatter(
                x=dfh["Data"],
                y=dfh[col].fillna(0),
                name=tk,
                mode="lines",
                stackgroup=stackgroup,
                line=dict(width=0.7, color=instrument_color(tk)),
                fillcolor=instrument_color(tk),
            )
        )
    chart_id = "andamento_pl_decomp_stacked" if viz_mode == "Stacked" else "andamento_pl_decomp_grouped"
    if "P/L" in dfh.columns and (not dfh["P/L"].dropna().empty):
        add_extrema_markers(
            fig,
            chart_id,
            dfh["Data"],
            pd.to_numeric(dfh["P/L"], errors="coerce"),
            theme=theme,
            value_formatter=lambda v: fmt_eur_it(v, 2),
        )
    return finalize_chart(
        fig,
        chart_id,
        hovermode="x unified",
        uirevision="stacked-pl",
        layout_updates={"barmode": "stack" if viz_mode == "Stacked" else "group"},
    )


def build_latest_instrument_pl_time_chart(pl_items, title):
    """Build latest P/L horizontal bar chart by instrument.

    chart_id: summary_latest_instrument_pl
    chiamato da: ui/pages/andamento.py
    """
    _ = title
    tickers = [item[0] for item in pl_items]
    values = [item[1] for item in pl_items]
    deltas = [item[2] if len(item) > 2 else None for item in pl_items]
    texts = []
    customdata = []
    for value, delta in zip(values, deltas):
        label = fmt_eur_it(value, 0, signed=True)
        if delta is None or pd.isna(delta):
            texts.append(label)
            customdata.append(["", ""])
            continue
        delta_label = fmt_eur_it(delta, 2, signed=True)
        delta_color = P["green"] if float(delta) >= 0 else P["red"]
        texts.append(f"{label} <span style='color:{delta_color}'>({delta_label})</span>")
        customdata.append([delta_label, delta_color])
    fig = go.Figure(
        go.Bar(
            y=tickers,
            x=values,
            orientation="h",
            marker_color=[instrument_color(tk) for tk in tickers],
            text=texts,
            customdata=customdata,
            textposition="auto",
            textfont=dict(size=11),
            name="P/L ultimo aggiornamento",
            hovertemplate="%{y}<br>P/L: %{x:,.2f} €<br>Delta vs quotazione precedente: %{customdata[0]}<extra></extra>",
        )
    )
    return finalize_chart(fig, "summary_latest_instrument_pl")


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
    fig.add_hline(y=0, line_dash="dot", line_color="rgba(107,114,128,0.55)", opacity=0.7)
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
    fig.add_hline(y=0, line_dash="dot", line_color="rgba(107,114,128,0.55)", opacity=0.7)
    return finalize_chart(fig, chart_id)
