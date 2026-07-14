from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from core.services.accumuli import IMPATTO_RATA_ALTO_PCT
from ui.charts.settings import apply_settings
from ui.formatting import fmt_eur_it, fmt_num_it, fmt_pct_it, hex_to_rgba
from ui.theme import P, macro_color


def _empty_figure(chart_id: str) -> go.Figure:
    return apply_settings(go.Figure(), chart_id)


def build_accumulo_price_pmc_chart(series: pd.DataFrame, operations: pd.DataFrame | None = None) -> go.Figure:
    """Grafico prezzo corrente vs PMC dinamico con marker acquisti."""
    chart_id = "cruscotti_accumuli_price_pmc"
    if series is None or series.empty or "Data" not in series.columns:
        return _empty_figure(chart_id)
    plot = series.copy()
    plot["Data"] = pd.to_datetime(plot["Data"], errors="coerce")
    plot = plot.dropna(subset=["Data"]).sort_values("Data")
    if plot.empty:
        return _empty_figure(chart_id)

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=plot["Data"],
            y=pd.to_numeric(plot.get("Prezzo"), errors="coerce"),
            name="Prezzo",
            mode="lines",
            line=dict(color=P["blue"], width=2.3),
            hovertemplate="%{x|%d/%m/%Y}<br>Prezzo: %{y:,.4f} €<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=plot["Data"],
            y=pd.to_numeric(plot.get("PMC"), errors="coerce"),
            name="PMC",
            mode="lines",
            line=dict(color=P["orange"], width=2.1, dash="dash"),
            hovertemplate="%{x|%d/%m/%Y}<br>PMC: %{y:,.4f} €<extra></extra>",
        )
    )
    if operations is not None and not operations.empty:
        ops = operations.copy()
        ops["data"] = pd.to_datetime(ops.get("data"), errors="coerce")
        ops = ops.dropna(subset=["data"])
        if not ops.empty:
            fig.add_trace(
                go.Scatter(
                    x=ops["data"],
                    y=pd.to_numeric(ops.get("price"), errors="coerce"),
                    name="Acquisti",
                    mode="markers",
                    marker=dict(color=P["red"], size=8, line=dict(color="white", width=1.2)),
                    customdata=list(zip(pd.to_numeric(ops.get("qty"), errors="coerce"), pd.to_numeric(ops.get("importo_lordo"), errors="coerce"))),
                    hovertemplate=(
                        "%{x|%d/%m/%Y}<br>Prezzo acquisto: %{y:,.4f} €"
                        "<br>Quote: %{customdata[0]:,.4f}<br>Importo: %{customdata[1]:,.2f} €<extra></extra>"
                    ),
                )
            )

    # Linea di riferimento orizzontale sul PMC di oggi (non il PMC storico, che
    # è già la linea tratteggiata sopra): mostra dove si colloca il costo medio
    # attuale rispetto a tutta la distribuzione dei prezzi del periodo — è la
    # stessa soglia usata per calcolare il percentile PMC nel dettaglio.
    pmc_series = pd.to_numeric(plot.get("PMC"), errors="coerce").dropna()
    if not pmc_series.empty:
        pmc_now = float(pmc_series.iloc[-1])
        fig.add_hline(
            y=pmc_now,
            line_dash="dot",
            line_color=P["green"],
            line_width=1.6,
            opacity=0.9,
            annotation_text=f"PMC attuale {fmt_eur_it(pmc_now, 2)} €",
            annotation_position="top left",
            annotation_font=dict(color=P["green"], size=11),
        )

    fig.update_layout(
        height=330,
        margin=dict(l=8, r=8, t=36, b=8),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        title=dict(text="Prezzo vs PMC", x=0.0, xanchor="left", font=dict(size=14)),
        hovermode="x unified",
    )
    fig.update_yaxes(title_text="€/quota", tickformat=",.2f", automargin=True, zeroline=False)
    fig.update_xaxes(automargin=True, rangeslider=dict(visible=False))
    return apply_settings(fig, chart_id)


def build_accumulo_value_chart(series: pd.DataFrame) -> go.Figure:
    """Grafico capitale investito vs controvalore con shading P/L semplificato."""
    chart_id = "cruscotti_accumuli_value"
    if series is None or series.empty or "Data" not in series.columns:
        return _empty_figure(chart_id)
    plot = series.copy()
    plot["Data"] = pd.to_datetime(plot["Data"], errors="coerce")
    plot = plot.dropna(subset=["Data"]).sort_values("Data")
    if plot.empty:
        return _empty_figure(chart_id)
    invested = pd.to_numeric(plot.get("Capitale investito"), errors="coerce")
    value = pd.to_numeric(plot.get("Controvalore"), errors="coerce")
    diff = value - invested

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=plot["Data"],
            y=invested,
            name="Capitale investito",
            mode="lines",
            line=dict(color=P["muted"], width=1.8),
            hovertemplate="%{x|%d/%m/%Y}<br>Capitale: %{y:,.2f} €<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=plot["Data"],
            y=value,
            name="Controvalore",
            mode="lines",
            line=dict(color=P["green"], width=2.4),
            hovertemplate="%{x|%d/%m/%Y}<br>Controvalore: %{y:,.2f} €<extra></extra>",
        )
    )

    pos_y = value.where(diff >= 0, invested)
    neg_y = value.where(diff < 0, invested)
    fig.add_trace(
        go.Scatter(
            x=plot["Data"],
            y=invested,
            mode="lines",
            line=dict(width=0),
            showlegend=False,
            hoverinfo="skip",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=plot["Data"],
            y=pos_y,
            mode="lines",
            fill="tonexty",
            fillcolor=hex_to_rgba(P["green"], 0.16),
            line=dict(width=0),
            name="Area utile",
            hoverinfo="skip",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=plot["Data"],
            y=invested,
            mode="lines",
            line=dict(width=0),
            showlegend=False,
            hoverinfo="skip",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=plot["Data"],
            y=neg_y,
            mode="lines",
            fill="tonexty",
            fillcolor=hex_to_rgba(P["red"], 0.16),
            line=dict(width=0),
            name="Area perdita",
            hoverinfo="skip",
        )
    )
    fig.update_layout(
        height=330,
        margin=dict(l=8, r=8, t=36, b=8),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        title=dict(text="Capitale investito vs Controvalore", x=0.0, xanchor="left", font=dict(size=14)),
        hovermode="x unified",
    )
    fig.update_yaxes(title_text="€", tickformat=",.0f", automargin=True, zeroline=False)
    fig.update_xaxes(automargin=True, rangeslider=dict(visible=False))
    return apply_settings(fig, chart_id)


def _overview_label_positions(plot: pd.DataFrame) -> list[str]:
    """Distribuisce le etichette dei marker per ridurre le sovrapposizioni.

    Plotly non ha un solver di collisione nativo per le text labels; usiamo una
    griglia normalizzata e alterniamo le posizioni quando più strumenti cadono
    nella stessa zona operativa della mappa.
    """
    if plot is None or plot.empty:
        return []
    x = pd.to_numeric(plot.get("distanza_pareggio_pct"), errors="coerce").fillna(0.0)
    y = pd.to_numeric(plot.get("impatto_pmc_rata_pct"), errors="coerce").fillna(0.0)
    x_span = max(float(x.max() - x.min()), 1e-9)
    y_span = max(float(y.max() - y.min()), 1e-9)
    occupied: list[tuple[float, float]] = []
    cycle = ["top center", "bottom center", "middle right", "middle left", "top right", "bottom left"]
    positions: list[str] = []
    for xi, yi in zip(x, y):
        nx = float((xi - x.min()) / x_span)
        ny = float((yi - y.min()) / y_span)
        near = sum(1 for ox, oy in occupied if abs(nx - ox) <= 0.12 and abs(ny - oy) <= 0.12)
        positions.append(cycle[min(near, len(cycle) - 1)])
        occupied.append((nx, ny))
    return positions


def _padded_axis_range(values: pd.Series, pad_ratio: float = 0.14) -> list[float] | None:
    nums = pd.to_numeric(values, errors="coerce").dropna()
    if nums.empty:
        return None
    v_min = float(nums.min())
    v_max = float(nums.max())
    span = max(v_max - v_min, abs(v_max) * 0.1, abs(v_min) * 0.1, 0.01)
    return [v_min - span * pad_ratio, v_max + span * pad_ratio]


def build_accumuli_overview_chart(summary: pd.DataFrame) -> go.Figure:
    """Mappa operativa degli accumuli.

    Ascissa = distanza (segnata) dal pareggio sul PMC all-in: positiva è
    cuscinetto prima del pareggio, negativa è recupero necessario. Ordinata =
    impatto simulato sul PMC di una rata tipica (non un peso sul capitale).
    La dimensione del marker rappresenta il capitale investito aperto e il colore la categoria dello strumento.
    """
    chart_id = "cruscotti_accumuli_overview"
    if summary is None or summary.empty:
        return _empty_figure(chart_id)
    plot = summary.copy()
    plot["distanza_pareggio_pct"] = pd.to_numeric(plot.get("distanza_pareggio_pct"), errors="coerce")
    plot["impatto_pmc_rata_pct"] = pd.to_numeric(plot.get("impatto_pmc_rata_pct"), errors="coerce")
    plot["capitale"] = pd.to_numeric(plot.get("capitale"), errors="coerce").fillna(0.0)
    plot["pl_pct"] = pd.to_numeric(plot.get("pl_pct"), errors="coerce").fillna(0.0)
    plot = plot.dropna(subset=["distanza_pareggio_pct", "impatto_pmc_rata_pct"])
    if plot.empty:
        return _empty_figure(chart_id)

    max_capital = float(plot["capitale"].max()) if not plot.empty else 0.0
    if max_capital > 0:
        sizes = 18 + (plot["capitale"] / max_capital) * 34
    else:
        sizes = pd.Series([24] * len(plot), index=plot.index)
    plot["_label_position"] = _overview_label_positions(plot)

    fig = go.Figure()
    for categoria, group in plot.groupby(plot.get("categoria", pd.Series([""] * len(plot))).astype(str), sort=True):
        idx = group.index
        customdata = list(
            zip(
                group.get("categoria", pd.Series([""] * len(group), index=group.index)),
                group.get("tipo_accumulo", pd.Series([""] * len(group), index=group.index)),
                group["capitale"],
                group.get("controvalore", pd.Series([0.0] * len(group), index=group.index)),
                group["pl_pct"],
                group.get("stato", pd.Series([""] * len(group), index=group.index)),
                group.get("priorita", pd.Series([""] * len(group), index=group.index)),
            )
        )
        fig.add_trace(
            go.Scatter(
                x=group["distanza_pareggio_pct"],
                y=group["impatto_pmc_rata_pct"],
                mode="markers+text",
                text=group["ticker"].astype(str),
                textposition=group["_label_position"].astype(str).tolist(),
                textfont=dict(size=10),
                cliponaxis=False,
                name=str(categoria or "Altro"),
                marker=dict(
                    size=sizes.loc[idx],
                    color=macro_color(str(categoria)),
                    opacity=0.76,
                    line=dict(color="white", width=1.4),
                ),
                customdata=customdata,
                hovertemplate=(
                    "<b>%{text}</b><br>Categoria: %{customdata[0]} · %{customdata[1]}"
                    "<br>Cuscinetto/recupero pareggio: %{x:.2%}"
                    "<br>Impatto rata tipica sul PMC: %{y:.2%}"
                    "<br>Capitale: %{customdata[2]:,.2f} €"
                    "<br>Controvalore: %{customdata[3]:,.2f} €"
                    "<br>P/L: %{customdata[4]:.2%}"
                    "<br>Stato: %{customdata[5]} · Priorità %{customdata[6]}<extra></extra>"
                ),
            )
        )
    fig.add_vline(x=0, line_dash="dot", line_color=hex_to_rgba(P["muted"], 0.7), opacity=0.8)
    fig.add_hline(y=IMPATTO_RATA_ALTO_PCT, line_dash="dot", line_color=hex_to_rgba(P["orange"], 0.65), opacity=0.7)
    fig.update_layout(
        height=max(320, min(460, 250 + len(plot) * 10)),
        margin=dict(l=8, r=36, t=42, b=22),
        title="Mappa sintetica accumuli",
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    fig.update_xaxes(
        title_text="Cuscinetto (+) / recupero (-) al pareggio",
        tickformat=".1%",
        automargin=True,
        zeroline=True,
        range=_padded_axis_range(plot["distanza_pareggio_pct"]),
    )
    fig.update_yaxes(
        title_text="Impatto rata tipica sul PMC",
        tickformat=".2%",
        automargin=True,
        zeroline=False,
        range=_padded_axis_range(plot["impatto_pmc_rata_pct"]),
    )
    return apply_settings(fig, chart_id)
