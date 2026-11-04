from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from core.config import COLORS
from persistence.storage import macro_cat
from ui.charts.extrema import add_extrema_markers
from ui.charts.settings import apply_settings, get_chart_setting
from ui.charts.tables import small_pie_texts
from ui.formatting import fmt_eur_it, fmt_pct_it, hex_to_rgba
from ui.theme import CATEGORY_COLORS, P, instrument_color, macro_color

# Ownership reale:
# - pagina: ui/pages/cruscotti.py
# - chart_id principali: cruscotti_compact_category_dashboard,
#   cruscotti_category_temporal, cruscotti_category_value_pie,
#   cruscotti_category_capital_pl_pie


def build_category_instrument_distribution_pie_chart(df: pd.DataFrame) -> go.Figure:
    """Distribuzione del controvalore del comparto per strumento.

    chart_id: cruscotti_category_value_pie
    chiamato da: ui/dashboard_bundles.py e ui/pages/cruscotti.py
    """
    fig = go.Figure()
    if df is None or df.empty or "Ticker" not in df.columns or "Controvalore" not in df.columns:
        return apply_settings(fig, "cruscotti_category_value_pie")
    plot_df = df[["Ticker", "Controvalore"]].copy()
    plot_df["Controvalore"] = pd.to_numeric(plot_df["Controvalore"], errors="coerce").fillna(0.0)
    plot_df = plot_df[plot_df["Controvalore"] > 0].sort_values("Controvalore", ascending=False)
    if plot_df.empty:
        return apply_settings(fig, "cruscotti_category_value_pie")
    pie_text = small_pie_texts(plot_df["Controvalore"].tolist(), threshold=0.07)
    fig.add_trace(
        go.Pie(
            labels=plot_df["Ticker"],
            values=plot_df["Controvalore"],
            hole=0.40,
            marker=dict(colors=[instrument_color(tk) for tk in plot_df["Ticker"]]),
            text=pie_text,
            textinfo="label+percent",
            textposition="outside",
            sort=False,
            showlegend=True,
            hovertemplate="%{label}<br>Controvalore: %{value:,.2f} €<br>Peso comparto: %{percent}<extra></extra>",
        )
    )
    return apply_settings(fig, "cruscotti_category_value_pie")


def build_category_capital_pl_pie_chart(df: pd.DataFrame, category: str) -> go.Figure:
    """Distribuzione tra capitale versato e P/L del comparto.

    chart_id: cruscotti_category_capital_pl_pie
    chiamato da: ui/dashboard_bundles.py e ui/pages/cruscotti.py
    """
    fig = go.Figure()
    if df is None or df.empty:
        return apply_settings(fig, "cruscotti_category_capital_pl_pie")
    cost_total = float(pd.to_numeric(df.get("Costo"), errors="coerce").fillna(0.0).sum()) if "Costo" in df.columns else 0.0
    pl_total = float(pd.to_numeric(df.get("P/L €"), errors="coerce").fillna(0.0).sum()) if "P/L €" in df.columns else 0.0
    labels = ["Capitale versato"]
    values = [max(cost_total, 0.0)]
    colors = [hex_to_rgba(macro_color(category), 0.78)]
    pulls = [0.0]
    if abs(pl_total) > 1e-9:
        labels.append("P/L" if pl_total >= 0 else "Perdita")
        values.append(abs(pl_total))
        colors.append(P["green"] if pl_total >= 0 else P["red"])
        pulls.append(0.10)
    fig.add_trace(
        go.Pie(
            labels=labels,
            values=values,
            hole=0.28,
            marker=dict(colors=colors),
            textinfo="label+percent",
            textposition="inside",
            sort=False,
            pull=pulls,
            showlegend=True,
            hovertemplate="%{label}<br>Valore: %{value:,.2f} €<br>Peso: %{percent}<extra></extra>",
        )
    )
    return apply_settings(fig, "cruscotti_category_capital_pl_pie")


def build_compact_category_dashboard_chart(df: pd.DataFrame, accent: str) -> go.Figure:
    """Build the compact category dashboard chart shown in Cruscotti.

    chart_id: cruscotti_compact_category_dashboard
    chiamato da: ui/dashboard_bundles.py e ui/pages/cruscotti.py
    """
    fig_dash = make_subplots(rows=1, cols=2, horizontal_spacing=0.20, subplot_titles=("Peso interno al comparto", "P/L per strumento"))
    required_columns = {"Ticker", "Controvalore", "Peso comparto %", "P/L €"}
    if df is None or df.empty or not required_columns.issubset(df.columns):
        return apply_settings(fig_dash, "cruscotti_compact_category_dashboard")

    plot_df = df.copy().sort_values("Controvalore", ascending=True)
    plot_df["Peso comparto %"] = pd.to_numeric(plot_df["Peso comparto %"], errors="coerce").fillna(0.0)
    plot_df["Controvalore"] = pd.to_numeric(plot_df["Controvalore"], errors="coerce").fillna(0.0)
    plot_df["P/L €"] = pd.to_numeric(plot_df["P/L €"], errors="coerce").fillna(0.0)
    fig_dash.add_trace(
        go.Bar(
            x=plot_df["Peso comparto %"] * 100.0,
            y=plot_df["Ticker"],
            orientation="h",
            marker_color=accent,
            text=[f"{fmt_pct_it(v, 1)}<br>{fmt_eur_it(cv, 0)}" for v, cv in zip(plot_df["Peso comparto %"], plot_df["Controvalore"])],
            textposition="outside",
            cliponaxis=False,
            textfont=dict(size=10),
            hovertemplate="%{y}<br>Peso comparto: %{x:.2f}%<br>Controvalore: %{customdata}<extra></extra>",
            customdata=[fmt_eur_it(v, 2) for v in plot_df["Controvalore"]],
            showlegend=False,
        ),
        row=1,
        col=1,
    )
    fig_dash.add_trace(
        go.Bar(
            x=plot_df["P/L €"],
            y=plot_df["Ticker"],
            orientation="h",
            marker_color=[P["green"] if v >= 0 else P["red"] for v in plot_df["P/L €"]],
            text=[fmt_eur_it(v, 0, signed=True) for v in plot_df["P/L €"]],
            textposition="outside",
            cliponaxis=False,
            textfont=dict(size=10),
            hovertemplate="%{y}<br>P/L: %{x:.2f} €<extra></extra>",
            showlegend=False,
        ),
        row=1,
        col=2,
    )

    fig_height = max(250, min(420, 150 + len(plot_df) * 36))
    max_weight = float((plot_df["Peso comparto %"] * 100.0).max()) if not plot_df.empty else 0.0
    pl_min = float(plot_df["P/L €"].min()) if not plot_df.empty else 0.0
    pl_max = float(plot_df["P/L €"].max()) if not plot_df.empty else 0.0
    weight_range = [0, max(8, max_weight * 1.28)]
    pl_span = max(abs(pl_min), abs(pl_max), 1.0)
    pl_range = [min(pl_min, 0) - pl_span * 0.18, max(pl_max, 0) + pl_span * 0.26]

    fig_dash.update_layout(height=fig_height, showlegend=False)
    fig_dash.update_xaxes(title_text="% del comparto", row=1, col=1, ticksuffix="%", range=weight_range, automargin=True)
    fig_dash.update_xaxes(title_text="P/L €", row=1, col=2, range=pl_range, automargin=True)
    fig_dash.update_yaxes(automargin=True, tickfont=dict(size=9), row=1, col=1)
    fig_dash.update_yaxes(automargin=True, tickfont=dict(size=9), row=1, col=2)
    if plot_df["P/L €"].min() < 0 < plot_df["P/L €"].max():
        fig_dash.add_vline(x=0, line_dash="dot", line_color=hex_to_rgba(COLORS["gray"], 0.55), row=1, col=2)
    return apply_settings(fig_dash, "cruscotti_compact_category_dashboard")


def build_category_invested_vs_pl_chart(df: pd.DataFrame, accent: str) -> go.Figure:
    """Barre per strumento: controvalore corrente con etichetta P/L% e legenda stabile P/L +/-."""
    fig = go.Figure()
    required_columns = {"Ticker", "Controvalore", "P/L €"}
    if df is None or df.empty or not required_columns.issubset(df.columns):
        return apply_settings(fig, "cruscotti_category_invested_vs_pl")

    plot_df = df[["Ticker", "Controvalore", "P/L €"]].copy()
    if "P/L %" in df.columns:
        plot_df["P/L %"] = pd.to_numeric(df["P/L %"], errors="coerce").fillna(0.0)
    elif "Costo" in df.columns:
        cost_series = pd.to_numeric(df["Costo"], errors="coerce").fillna(0.0)
        plot_df["P/L %"] = pd.to_numeric(df["P/L €"], errors="coerce").fillna(0.0) / cost_series.replace(0.0, pd.NA)
        plot_df["P/L %"] = pd.to_numeric(plot_df["P/L %"], errors="coerce").fillna(0.0)
    else:
        plot_df["P/L %"] = 0.0

    plot_df["Controvalore"] = pd.to_numeric(plot_df["Controvalore"], errors="coerce").fillna(0.0)
    plot_df["P/L €"] = pd.to_numeric(plot_df["P/L €"], errors="coerce").fillna(0.0)
    plot_df = plot_df[(plot_df["Controvalore"].abs() > 1e-9) | (plot_df["P/L €"].abs() > 1e-9)]
    plot_df = plot_df.sort_values("Controvalore", ascending=True)
    if plot_df.empty:
        return apply_settings(fig, "cruscotti_category_invested_vs_pl")

    fig.add_trace(
        go.Bar(
            x=plot_df["Controvalore"],
            y=plot_df["Ticker"],
            orientation="h",
            name="Controvalore",
            marker_color=hex_to_rgba(accent, 0.72),
            hovertemplate="%{y}<br>Controvalore: %{x:,.2f} €<br>P/L: %{customdata[0]:,.2f} €<br>P/L %: %{customdata[1]:.2%}<extra></extra>",
            customdata=list(zip(plot_df["P/L €"], plot_df["P/L %"])),
        )
    )

    pos_df = plot_df[plot_df["P/L €"] > 0].copy()
    neg_df = plot_df[plot_df["P/L €"] < 0].copy()

    if not pos_df.empty:
        fig.add_trace(
            go.Bar(
                x=pos_df["P/L €"].abs(),
                y=pos_df["Ticker"],
                orientation="h",
                base=(pos_df["Controvalore"] - pos_df["P/L €"].abs()).tolist(),
                name="P/L positivo",
                marker_color=P["green"],
                hoverinfo="skip",
            )
        )
    else:
        fig.add_trace(
            go.Bar(
                x=[0],
                y=[""],
                orientation="h",
                name="P/L positivo",
                marker_color=P["green"],
                visible="legendonly",
                hoverinfo="skip",
                showlegend=True,
            )
        )

    if not neg_df.empty:
        fig.add_trace(
            go.Bar(
                x=neg_df["P/L €"].abs(),
                y=neg_df["Ticker"],
                orientation="h",
                base=(neg_df["Controvalore"] - neg_df["P/L €"].abs()).tolist(),
                name="P/L negativo",
                marker_color=P["red"],
                hoverinfo="skip",
            )
        )
    else:
        fig.add_trace(
            go.Bar(
                x=[0],
                y=[""],
                orientation="h",
                name="P/L negativo",
                marker_color=P["red"],
                visible="legendonly",
                hoverinfo="skip",
                showlegend=True,
            )
        )

    max_controvalore = float(plot_df["Controvalore"].max()) if not plot_df.empty else 0.0
    label_gap = max(max_controvalore * 0.018, 1.0)
    for _, row in plot_df.iterrows():
        row_controvalore = float(row["Controvalore"])
        row_pl = float(row["P/L €"])
        row_pl_pct = float(row["P/L %"])
        row_invested = row_controvalore - row_pl
        fig.add_annotation(
            x=row_controvalore + label_gap,
            y=row["Ticker"],
            text=(
                f"Inv {fmt_eur_it(row_invested, 0)} | "
                f"Ctv {fmt_eur_it(row_controvalore, 0)}<br>"
                f"P/L {fmt_eur_it(row_pl, 0, signed=True)} | {fmt_pct_it(row_pl_pct, 2, signed=True)}"
            ),
            showarrow=False,
            font=dict(size=10, color="rgba(71,85,105,0.95)"),
            xanchor="left",
            yanchor="middle",
        )
    row_height = float(get_chart_setting("cruscotti_category_invested_vs_pl", "row_height", 48) or 48)
    min_height = float(get_chart_setting("cruscotti_category_invested_vs_pl", "min_height", 280) or 280)
    max_height = float(get_chart_setting("cruscotti_category_invested_vs_pl", "max_height", 860) or 860)
    top_bottom_pad = float(get_chart_setting("cruscotti_category_invested_vs_pl", "height_base_pad", 120) or 120)
    dynamic_height = max(min_height, min(max_height, top_bottom_pad + len(plot_df) * row_height))
    fig.update_layout(barmode="overlay", height=dynamic_height)
    fig.update_xaxes(
        title_text="Euro",
        automargin=True,
        range=[0, max(max_controvalore * 1.42, 1.0)],
    )
    fig.update_yaxes(automargin=True, tickfont=dict(size=9))
    if plot_df["P/L €"].min() < 0 < plot_df["Controvalore"].max():
        fig.add_vline(x=0, line_dash="dot", line_color=hex_to_rgba(COLORS["gray"], 0.55))
    return apply_settings(fig, "cruscotti_category_invested_vs_pl")


def build_category_temporal_dual_axis(dfh, da, category, data, start_date=None):
    """Crea figura a doppio asse: P/L e controvalore del comparto nel tempo.

    chart_id: cruscotti_category_temporal
    chiamato da: ui/dashboard_bundles.py e ui/pages/cruscotti.py

    Args:
        start_date: Data (date object) da cui iniziare il grafico. Se None, usa tutti i dati disponibili.
    """
    if dfh is None or dfh.empty or da is None or da.empty:
        fig = go.Figure()
        fig.add_annotation(text=f"Dati insufficienti per {category}")
        return apply_settings(fig, "cruscotti_category_temporal")

    # Caso speciale: categoria "Tutto" = tutti gli strumenti
    if category == "Tutto":
        category_tickers_from_positions = da["Ticker"].tolist()
        category_rows = da
    else:
        cat_col = "Categoria" if "Categoria" in da.columns else None
        if cat_col:
            category_tickers_from_positions = da[da["Categoria"] == category]["Ticker"].tolist()
            category_rows = da[da["Categoria"] == category]
        else:
            type_col = "Tipo" if "Tipo" in da.columns else "tipo"
            category_rows = da[da[type_col].apply(macro_cat) == category]
            category_tickers_from_positions = category_rows["Ticker"].tolist()

    if not category_tickers_from_positions:
        fig = go.Figure()
        fig.add_annotation(text=f"Nessun {category} nel portafoglio")
        return apply_settings(fig, "cruscotti_category_temporal")

    pl_cols: list[tuple[str, str]] = []
    for ticker in category_tickers_from_positions:
        col = f"PL_{ticker}"
        if col in dfh.columns:
            pl_cols.append((ticker, col))
    if not pl_cols:
        fig = go.Figure()
        fig.add_annotation(text=f"Nessun {category} nel portafoglio")
        return apply_settings(fig, "cruscotti_category_temporal")

    dates = pd.to_datetime(dfh["Data"], errors="coerce")

    # Filtra da start_date se fornito
    if start_date is not None:
        mask = dates >= pd.Timestamp(start_date)
        dfh_filtered = dfh[mask].copy()
        dates = dates[mask]
    else:
        dfh_filtered = dfh.copy()
    ticker_cost = category_rows.set_index("Ticker")["Costo"].to_dict() if "Costo" in category_rows.columns else {}
    pl_cols_list = [col for _, col in pl_cols]
    pl_series = dfh_filtered[pl_cols_list].fillna(0).astype(float).sum(axis=1)
    pl_vals = pl_series.tolist()
    total_cost = sum(ticker_cost.get(ticker, 0) for ticker, _ in pl_cols)
    controvalore_vals = (pl_series + total_cost).tolist()

    # Allinea il punto finale alla situazione corrente senza introdurre una data weekend extra.
    try:
        current_pl = float(pd.to_numeric(category_rows.get("P/L €"), errors="coerce").fillna(0.0).sum())
        current_controvalore = float(pd.to_numeric(category_rows.get("Controvalore"), errors="coerce").fillna(0.0).sum())
        if pl_vals and controvalore_vals:
            if abs(pl_vals[-1] - current_pl) > 0.01:
                pl_vals[-1] = current_pl
            if abs(controvalore_vals[-1] - current_controvalore) > 0.01:
                controvalore_vals[-1] = current_controvalore
    except Exception:
        pass

    fig = go.Figure()
    color_cat = CATEGORY_COLORS.get(category, "#aaa")
    fig.add_trace(
        go.Scatter(
            x=dates,
            y=pl_vals,
            name=f"P/L {category}",
            mode="lines",
            line=dict(color=color_cat, width=2),
            yaxis="y",
            hovertemplate="<b>P/L</b><br>%{x|%d/%m/%Y}<br>%{y:,.2f}€<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=dates,
            y=controvalore_vals,
            name=f"Controvalore {category}",
            mode="lines",
            line=dict(color=hex_to_rgba(color_cat, 0.5), width=2, dash="dash"),
            yaxis="y2",
            hovertemplate="<b>Controvalore</b><br>%{x|%d/%m/%Y}<br>%{y:,.2f}€<extra></extra>",
        )
    )

    if pl_vals:
        add_extrema_markers(
            fig,
            "cruscotti_category_temporal",
            dates,
            pl_vals,
            series_name=f"P/L {category}",
            yaxis="y",
            value_formatter=lambda v: fmt_eur_it(v, 0),
        )
    if controvalore_vals:
        add_extrema_markers(
            fig,
            "cruscotti_category_temporal",
            dates,
            controvalore_vals,
            series_name=f"Controvalore {category}",
            yaxis="y2",
            value_formatter=lambda v: fmt_eur_it(v, 0),
        )

    fig.update_layout(hovermode="x unified")
    return apply_settings(fig, "cruscotti_category_temporal")
