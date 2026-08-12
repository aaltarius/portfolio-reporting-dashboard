from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from ui.charts.runtime import empty_chart, finalize_chart
from ui.charts.settings import apply_settings
from ui.formatting import fmt_eur_it, fmt_qty_it, hex_to_rgba
from ui.theme import instrument_color, macro_color

# Ownership reale:
# - pagina: ui/pages/operazioni.py
# - chart_id principali: andamento_monthly_spending, operations_purchase_installments


def build_monthly_purchase_spending_time_chart(monthly_df: pd.DataFrame, theme) -> go.Figure:
    """Build monthly purchase spending chart with monthly bars and cumulative line.

    chart_id: andamento_monthly_spending
    chiamato da: ui/pages/operazioni.py
    """
    if monthly_df is None or monthly_df.empty:
        return empty_chart("andamento_monthly_spending")
    chart_df = monthly_df.copy()
    chart_df["DataMese"] = pd.to_datetime(chart_df["Mese"] + "-01", errors="coerce")
    chart_df = chart_df.dropna(subset=["DataMese"]).sort_values("DataMese").reset_index(drop=True)
    if chart_df.empty:
        return empty_chart("andamento_monthly_spending")

    chart_df["MeseLabel"] = chart_df["DataMese"].dt.strftime("%m/%Y")
    text_values = [fmt_eur_it(v, 0) for v in chart_df["Spesa Acquisti"]]
    cumulative = chart_df["Cumulato Acquisti"] if "Cumulato Acquisti" in chart_df.columns else chart_df["Spesa Acquisti"].cumsum()

    x1 = chart_df["DataMese"].max()
    x0 = x1 - pd.DateOffset(months=11)
    x0 = x0.replace(day=1) - pd.DateOffset(days=15)
    x1_pad = x1 + pd.DateOffset(days=20)
    y1_max = max(float(chart_df["Spesa Acquisti"].max() or 0) * 1.25, 1.0)
    y2_max = max(float(cumulative.max() or 0) * 1.10, 1.0)

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=chart_df["DataMese"],
            y=chart_df["Spesa Acquisti"],
            name="Spesa acquisti",
            marker_color=theme.color_blue,
            text=text_values,
            textposition="outside",
            textfont=dict(size=10),
            cliponaxis=False,
            customdata=chart_df["MeseLabel"],
            hovertemplate="%{customdata}<br>Spesa acquisti: %{y:,.2f} EUR<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=chart_df["DataMese"],
            y=cumulative,
            mode="lines+markers",
            name="Cumulato acquisti",
            line=dict(color=theme.color_orange, width=2.2),
            marker=dict(size=6),
            yaxis="y2",
            customdata=chart_df["MeseLabel"],
            hovertemplate="%{customdata}<br>Cumulato acquisti: %{y:,.2f} EUR<extra></extra>",
        )
    )
    return finalize_chart(
        fig,
        "andamento_monthly_spending",
        hovermode="x unified",
        layout_updates={"bargap": 0.24, "yaxis2": dict(range=[0, y2_max])},
        xaxis_updates={
            "tickmode": "array",
            "tickvals": chart_df["DataMese"],
            "ticktext": chart_df["MeseLabel"],
            "range": [x0, x1_pad],
            "maxallowed": x1_pad,
            "automargin": True,
        },
        yaxis_updates={"range": [0, y1_max]},
    )


def build_purchase_installments_chart(purchase_df: pd.DataFrame, theme) -> go.Figure:
    """Build purchase frequency chart for all purchased instruments.

    chart_id: operations_purchase_installments
    chiamato da: ui/pages/operazioni.py
    """
    fig = go.Figure()
    if purchase_df is None or purchase_df.empty:
        return empty_chart("operations_purchase_installments")

    # Compatibilità: accetta sia il nuovo nome (n_acquisti) che il vecchio (rate_count)
    count_col = "n_acquisti" if "n_acquisti" in purchase_df.columns else "rate_count"
    plot_df = purchase_df.copy().sort_values([count_col, "Ticker"], ascending=[True, True]).reset_index(drop=True)
    x_base = list(range(len(plot_df)))
    x_range = [x + 0.22 for x in x_base]
    price_values = pd.concat(
        [
            pd.to_numeric(plot_df.get("min_price"), errors="coerce"),
            pd.to_numeric(plot_df.get("pmc"), errors="coerce"),
            pd.to_numeric(plot_df.get("max_price"), errors="coerce"),
        ],
        ignore_index=True,
    ).dropna()
    tick_text = []
    for _, row in plot_df.iterrows():
        pmc_txt = fmt_eur_it(row["pmc"], 2) if pd.notna(row["pmc"]) else "n/d"
        cat_txt = str(row.get("category", "") or "").upper()
        cat_color = macro_color(cat_txt or "ALT")
        qty_txt = fmt_qty_it(row["qty_totale"], 4) if "qty_totale" in plot_df.columns and pd.notna(row.get("qty_totale")) else "n/d"
        tick_text.append(
            f"{row['Ticker']}<br><span style='color:{cat_color};font-weight:800'>{cat_txt}</span>"
            f"<br>{qty_txt} quote<br>PMC {pmc_txt}"
        )
    customdata = [
        [
            fmt_eur_it(row["min_price"], 2) if pd.notna(row["min_price"]) else "n/d",
            fmt_eur_it(row["pmc"], 2) if pd.notna(row["pmc"]) else "n/d",
            fmt_eur_it(row["max_price"], 2) if pd.notna(row["max_price"]) else "n/d",
            row.get("category", ""),
            fmt_qty_it(row["qty_totale"], 4) if "qty_totale" in plot_df.columns and pd.notna(row.get("qty_totale")) else "n/d",
        ]
        for _, row in plot_df.iterrows()
    ]
    fig.add_trace(
        go.Bar(
            x=x_base,
            y=plot_df[count_col],
            width=0.34,
            marker_color=[instrument_color(tk) for tk in plot_df["Ticker"]],
            customdata=customdata,
            text=[str(int(v)) for v in plot_df[count_col]],
            textposition="outside",
            textfont=dict(size=10),
            cliponaxis=False,
            hovertemplate=(
                "<b>%{customdata[3]}</b><br>"
                "N. acquisti: %{y}<br>"
                "Quote totali: %{customdata[4]}<br>"
                "Min acquisto: %{customdata[0]}<br>"
                "PMC attuale: %{customdata[1]}<br>"
                "Max acquisto: %{customdata[2]}<extra></extra>"
            ),
            name="N. acquisti",
        )
    )
    range_x = []
    range_y = []
    guide_x = []
    guide_y = []
    for i, row in plot_df.iterrows():
        if pd.notna(row["min_price"]) and pd.notna(row["max_price"]):
            range_x.extend([x_range[i], x_range[i], None])
            range_y.extend([row["min_price"], row["max_price"], None])
            guide_x.extend([x_range[i], x_range[i], None])
            guide_y.extend([25, 200, None])

    if guide_x:
        fig.add_trace(
            go.Scatter(
                x=guide_x,
                y=guide_y,
                mode="lines",
                yaxis="y2",
                line=dict(color=hex_to_rgba(theme.color_gray, 0.35), width=1, dash="dot"),
                hoverinfo="skip",
                showlegend=False,
                name="Guida prezzi",
            )
        )

    if range_x:
        fig.add_trace(
            go.Scatter(
                x=range_x,
                y=range_y,
                mode="lines",
                yaxis="y2",
                line=dict(color=theme.color_orange, width=10),
                opacity=0.9,
                hoverinfo="skip",
                showlegend=False,
                name="Range acquisti",
            )
        )

    fig.add_trace(
        go.Scatter(
            x=x_range,
            y=plot_df["pmc"],
            mode="markers",
            yaxis="y2",
            marker=dict(
                size=10,
                color=theme.color_orange,
                line=dict(color="#ffffff", width=1.5),
                symbol="diamond",
            ),
            customdata=customdata,
            hovertemplate=(
                "<b>PMC</b><br>"
                "PMC attuale: %{customdata[1]}<br>"
                "Range acquisti: %{customdata[0]} - %{customdata[2]}<extra></extra>"
            ),
            showlegend=False,
            name="PMC",
        )
    )
    if not price_values.empty:
        price_min = float(price_values.min())
        price_max = float(price_values.max())
        price_span = max(price_max - price_min, 0.01)
        price_pad = max(price_span * 0.18, price_max * 0.03, 0.5)
        y2_range = [max(0, price_min - price_pad), price_max + price_pad]
    else:
        y2_range = None
    fig.update_layout(
        xaxis=dict(
            tickmode="array",
            tickvals=x_base,
            ticktext=tick_text,
            tickangle=0,
            automargin=True,
        ),
        yaxis2=dict(
            title="Prezzi acquisto",
            overlaying="y",
            side="right",
            showgrid=False,
            zeroline=False,
            tickformat=",.2f",
            range=y2_range,
        ),
    )
    fig = apply_settings(fig, "operations_purchase_installments")
    fig.update_xaxes(tickangle=0, automargin=True)
    return fig


def build_purchase_installments_by_value_chart(purchase_df: pd.DataFrame, theme) -> go.Figure:
    """Variante di build_purchase_installments_chart con l'asse Y sul
    controvalore posseduto invece del numero di acquisti (in valutazione,
    non sostituisce quella storica — vedi ui/pages/cruscotti.py).

    Il numero di acquisti resta visibile come etichetta sopra ogni barra e
    nell'hover; asse secondario (range prezzi/PMC) invariato.

    chart_id: operations_purchase_installments_by_value
    chiamato da: ui/pages/cruscotti.py
    """
    fig = go.Figure()
    if purchase_df is None or purchase_df.empty:
        return empty_chart("operations_purchase_installments_by_value")

    count_col = "n_acquisti" if "n_acquisti" in purchase_df.columns else "rate_count"
    plot_df = purchase_df.copy()
    plot_df["controvalore"] = (
        pd.to_numeric(plot_df["controvalore"], errors="coerce").fillna(0.0)
        if "controvalore" in plot_df.columns
        else 0.0
    )
    plot_df = plot_df.sort_values(["controvalore", "Ticker"], ascending=[True, True]).reset_index(drop=True)
    x_base = list(range(len(plot_df)))
    x_range = [x + 0.22 for x in x_base]
    price_values = pd.concat(
        [
            pd.to_numeric(plot_df.get("min_price"), errors="coerce"),
            pd.to_numeric(plot_df.get("pmc"), errors="coerce"),
            pd.to_numeric(plot_df.get("max_price"), errors="coerce"),
        ],
        ignore_index=True,
    ).dropna()
    tick_text = []
    for _, row in plot_df.iterrows():
        pmc_txt = fmt_eur_it(row["pmc"], 2) if pd.notna(row["pmc"]) else "n/d"
        cat_txt = str(row.get("category", "") or "").upper()
        cat_color = macro_color(cat_txt or "ALT")
        qty_txt = fmt_qty_it(row["qty_totale"], 3) if "qty_totale" in plot_df.columns and pd.notna(row.get("qty_totale")) else "n/d"
        tick_text.append(
            f"{row['Ticker']}<br><span style='color:{cat_color};font-weight:800'>{cat_txt}</span>"
            f"<br>{qty_txt} quote<br>PMC<br>{pmc_txt}"
        )
    customdata = [
        [
            fmt_eur_it(row["min_price"], 2) if pd.notna(row["min_price"]) else "n/d",
            fmt_eur_it(row["pmc"], 2) if pd.notna(row["pmc"]) else "n/d",
            fmt_eur_it(row["max_price"], 2) if pd.notna(row["max_price"]) else "n/d",
            row.get("category", ""),
            fmt_qty_it(row["qty_totale"], 4) if "qty_totale" in plot_df.columns and pd.notna(row.get("qty_totale")) else "n/d",
            fmt_eur_it(row["controvalore"], 2),
        ]
        for _, row in plot_df.iterrows()
    ]
    fig.add_trace(
        go.Bar(
            x=x_base,
            y=plot_df["controvalore"],
            width=0.34,
            marker_color=[instrument_color(tk) for tk in plot_df["Ticker"]],
            customdata=customdata,
            text=[str(int(v)) for v in plot_df[count_col]],
            textposition="outside",
            textfont=dict(size=10),
            cliponaxis=False,
            hovertemplate=(
                "<b>%{customdata[3]}</b><br>"
                "Controvalore posseduto: %{customdata[5]}<br>"
                "N. acquisti: %{text}<br>"
                "Quote totali: %{customdata[4]}<br>"
                "Min acquisto: %{customdata[0]}<br>"
                "PMC attuale: %{customdata[1]}<br>"
                "Max acquisto: %{customdata[2]}<extra></extra>"
            ),
            name="Controvalore posseduto",
        )
    )
    range_x = []
    range_y = []
    guide_x = []
    guide_y = []
    for i, row in plot_df.iterrows():
        if pd.notna(row["min_price"]) and pd.notna(row["max_price"]):
            range_x.extend([x_range[i], x_range[i], None])
            range_y.extend([row["min_price"], row["max_price"], None])
            guide_x.extend([x_range[i], x_range[i], None])
            guide_y.extend([25, 200, None])

    if guide_x:
        fig.add_trace(
            go.Scatter(
                x=guide_x,
                y=guide_y,
                mode="lines",
                yaxis="y2",
                line=dict(color=hex_to_rgba(theme.color_gray, 0.35), width=1, dash="dot"),
                hoverinfo="skip",
                showlegend=False,
                name="Guida prezzi",
            )
        )

    if range_x:
        fig.add_trace(
            go.Scatter(
                x=range_x,
                y=range_y,
                mode="lines",
                yaxis="y2",
                line=dict(color=theme.color_orange, width=10),
                opacity=0.9,
                hoverinfo="skip",
                showlegend=False,
                name="Range acquisti",
            )
        )

    fig.add_trace(
        go.Scatter(
            x=x_range,
            y=plot_df["pmc"],
            mode="markers",
            yaxis="y2",
            marker=dict(
                size=10,
                color=theme.color_orange,
                line=dict(color="#ffffff", width=1.5),
                symbol="diamond",
            ),
            customdata=customdata,
            hovertemplate=(
                "<b>PMC</b><br>"
                "PMC attuale: %{customdata[1]}<br>"
                "Range acquisti: %{customdata[0]} - %{customdata[2]}<extra></extra>"
            ),
            showlegend=False,
            name="PMC",
        )
    )
    if not price_values.empty:
        price_min = float(price_values.min())
        price_max = float(price_values.max())
        price_span = max(price_max - price_min, 0.01)
        price_pad = max(price_span * 0.18, price_max * 0.03, 0.5)
        y2_range = [max(0, price_min - price_pad), price_max + price_pad]
    else:
        y2_range = None
    fig.update_layout(
        xaxis=dict(
            tickmode="array",
            tickvals=x_base,
            ticktext=tick_text,
            tickangle=0,
            automargin=True,
        ),
        yaxis2=dict(
            title="Prezzi acquisto",
            overlaying="y",
            side="right",
            showgrid=False,
            zeroline=False,
            tickformat=",.2f",
            range=y2_range,
        ),
    )
    fig = apply_settings(fig, "operations_purchase_installments_by_value")
    fig.update_xaxes(tickangle=0, automargin=True)
    return fig
