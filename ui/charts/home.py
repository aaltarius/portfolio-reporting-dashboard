from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.graph_objects as go

from core.asset_categories import get_selected_category_codes
from persistence.storage import macro_cat
from ui.charts.runtime import finalize_chart
from ui.charts.tables import small_pie_texts as _small_pie_texts
from ui.charts.settings import apply_settings
from ui.formatting import fmt_eur_it, hex_to_rgba
from ui.theme import instrument_color, macro_color

# Ownership reale:
# - pagina: ui/pages/home.py
# - chart_id principali: home_portfolio_pl, home_concentration, home_instrument_pie,
#   home_category_pie, home_instrument_bar_perf, home_instrument_bar_pl,
#   home_category_bar_value, home_category_bar_pl, home_category_bar_perf,
#   home_radar_allocation, home_radar_quality


def _resolve_visible_categories(settings: dict[str, Any] | None = None) -> list[str]:
    return list(get_selected_category_codes(settings))


def build_concentration_chart(da_frame, total_value, theme, settings: dict[str, Any] | None = None):
    """Build portfolio concentration chart for Home.

    chart_id: home_concentration
    chiamato da: ui/pages/home.py
    """
    type_col = "Tipo" if "Tipo" in da_frame.columns else ("tipo" if "tipo" in da_frame.columns else None)
    base_cols = ["Ticker", "Controvalore"] + ([type_col] if type_col else [])
    top_weights = da_frame.sort_values("Controvalore", ascending=False)[base_cols].copy()
    top_weights["Peso %"] = top_weights["Controvalore"] / total_value if total_value > 0 else 0
    top_weights["Peso cumulato %"] = top_weights["Peso %"].cumsum()
    top_weights["Categoria"] = (
        top_weights[type_col].apply(macro_cat) if type_col else pd.Series([""] * len(top_weights), index=top_weights.index)
    )
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=top_weights["Ticker"],
            y=top_weights["Controvalore"],
            name="Controvalore",
            marker_color=[instrument_color(tk) for tk in top_weights["Ticker"]],
            text=[fmt_eur_it(v, 0) for v in top_weights["Controvalore"]],
            textposition="outside",
            cliponaxis=False,
            customdata=top_weights[["Ticker", "Categoria"]].values,
            hovertemplate="%{customdata[0]}<br>Categoria: %{customdata[1]}<br>Controvalore: %{y:,.2f} €<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=top_weights["Ticker"],
            y=top_weights["Peso cumulato %"],
            name="Peso cumulato",
            mode="lines+markers",
            line=dict(color=theme.color_orange, width=2.2),
            yaxis="y2",
            customdata=top_weights[["Ticker"]].values,
            hovertemplate="%{customdata[0]}<br>Peso cumulato: %{y:.1%}<extra></extra>",
        )
    )
    fig = apply_settings(fig, "home_concentration")
    fig.update_xaxes(
        tickmode="array",
        tickvals=top_weights["Ticker"].tolist(),
        ticktext=top_weights["Ticker"].tolist(),
        automargin=True,
        type="category",
    )
    for cat in _resolve_visible_categories(settings):
        cat_df = top_weights[top_weights["Categoria"].astype(str).str.upper() == cat]
        if cat_df.empty:
            continue
        fig.add_trace(
            go.Scatter(
                x=cat_df["Ticker"],
                y=[-0.34] * len(cat_df),
                mode="text",
                text=[cat] * len(cat_df),
                textposition="bottom center",
                textfont=dict(size=10, color=macro_color(cat)),
                yaxis="y3",
                hoverinfo="skip",
                showlegend=False,
                cliponaxis=False,
                name=f"Categoria {cat}",
            )
        )
    fig.update_layout(
        yaxis3=dict(
            overlaying="y",
            side="left",
            range=[-0.82, 1],
            visible=False,
            fixedrange=True,
        ),
        margin=dict(b=118),
    )
    return fig


def build_portfolio_pl_chart(dfh, delta_colors, delta_text, dfmt, theme):
    """Build standalone Profit / Loss chart for homepage daily focus.

    chart_id: home_portfolio_pl
    chiamato da: ui/pages/home.py
    """
    _ = dfmt
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=dfh["Data"],
            y=dfh["P/L"],
            name="P/L",
            marker_color=delta_colors,
            text=delta_text,
            textposition="outside",
            textfont=dict(size=9),
            cliponaxis=False,
            showlegend=False,
        )
    )
    fig.add_trace(
        go.Scatter(
            x=[None],
            y=[None],
            mode="markers",
            name="P/L in crescita",
            marker=dict(color=theme.color_green, size=10, symbol="square"),
            showlegend=True,
        )
    )
    fig.add_trace(
        go.Scatter(
            x=[None],
            y=[None],
            mode="markers",
            name="P/L in calo",
            marker=dict(color=theme.color_red, size=10, symbol="square"),
            showlegend=True,
        )
    )
    fig = finalize_chart(fig, "home_portfolio_pl", hovermode="x unified", uirevision="home-pl")
    tick_dates = pd.Index(pd.to_datetime(dfh["Data"], errors="coerce").dropna()).drop_duplicates()
    if len(tick_dates) > 0:
        fig.update_xaxes(
            tickmode="array",
            tickvals=tick_dates.to_list(),
            ticktext=[value.strftime("%d/%m") for value in tick_dates],
        )
        last_date = tick_dates[-1]
        try:
            last_pl = float(pd.to_numeric(dfh["P/L"], errors="coerce").iloc[-1] or 0.0)
        except Exception:
            last_pl = 0.0
        label_color = theme.color_green if last_pl >= 0 else theme.color_red
        fig.add_annotation(
            x=1.0,
            y=last_pl,
            xref="paper",
            yref="y",
            text=fmt_eur_it(last_pl, 2, signed=True),
            showarrow=False,
            xanchor="left",
            align="left",
            xshift=6,
            yshift=0,
            font=dict(size=11, color=label_color, family="Courier New, monospace"),
            bgcolor="rgba(255,255,255,0.88)",
            bordercolor=hex_to_rgba(label_color, 0.30),
            borderwidth=1,
            borderpad=3,
        )
    return fig


def build_portfolio_pl_category_chart(dfh, data, theme, settings: dict[str, Any] | None = None):
    """Build 100% stacked daily P/L composition chart by macro category for Home."""
    if dfh is None or dfh.empty:
        return go.Figure()

    visible_categories = _resolve_visible_categories(settings)
    ticker_to_cat = {
        str(s.get("ticker") or ""): macro_cat(s.get("tipo", ""))
        for s in data.get("strumenti", [])
    }
    pl_cols = [c for c in dfh.columns if str(c).startswith("PL_")]
    category_series: dict[str, pd.Series] = {}
    for cat in visible_categories:
        cols = [col for col in pl_cols if ticker_to_cat.get(str(col)[3:]) == cat]
        if not cols:
            continue
        category_series[cat] = pd.to_numeric(dfh[cols].sum(axis=1), errors="coerce").fillna(0.0)

    total_abs = pd.Series(0.0, index=dfh.index, dtype="float64")
    for series in category_series.values():
        total_abs = total_abs.add(series.abs(), fill_value=0.0)
    total_abs = total_abs.replace(0, pd.NA)

    fig = go.Figure()
    last_labels: list[tuple[str, str, float]] = []
    running_last = 0.0
    for cat in visible_categories:
        if cat not in category_series:
            continue
        pct_series = (category_series[cat].abs() / total_abs) * 100.0
        pct_series = pct_series.fillna(0.0)
        if len(pct_series) > 0:
            last_pct = float(pct_series.iloc[-1] or 0.0)
            if last_pct > 0:
                last_labels.append((cat, macro_color(cat), running_last + last_pct / 2.0))
            running_last += last_pct
        fig.add_trace(
            go.Bar(
                x=dfh["Data"],
                y=pct_series,
                name=cat,
                marker_color=macro_color(cat),
                customdata=category_series[cat],
                hovertemplate=(
                    "Data: %{x|%d/%m/%Y}<br>"
                    + f"{cat}: "
                    + "%{y:.1f}%<br>"
                    + "P/L categoria: %{customdata:,.2f} €<extra></extra>"
                ),
            )
        )
    fig.update_layout(barmode="relative")
    fig = finalize_chart(fig, "home_portfolio_pl_category", hovermode="x unified", uirevision="home-pl-cat")
    fig.update_yaxes(domain=[0.0, 0.90])
    fig.update_yaxes(ticksuffix="%", zeroline=True, zerolinecolor=hex_to_rgba(theme.color_blue, 0.18))
    tick_dates = pd.Index(pd.to_datetime(dfh["Data"], errors="coerce").dropna()).drop_duplicates()
    if len(tick_dates) > 0:
        last_date = tick_dates[-1]
        fig.update_xaxes(
            tickmode="array",
            tickvals=tick_dates.to_list(),
            ticktext=[value.strftime("%d/%m") for value in tick_dates],
        )
        for cat, color, y_mid in last_labels:
            pct_value = next(
                (
                    float(((category_series[cat].abs() / total_abs) * 100.0).fillna(0.0).iloc[-1] or 0.0)
                    for _ in [0]
                ),
                0.0,
            )
            pct_text = f"{pct_value:>5.1f}%".replace(" ", "&nbsp;")
            fig.add_annotation(
                x=1.0,
                y=y_mid,
                xref="paper",
                yref="y",
                text=f"<b>{cat}</b>&nbsp;&nbsp;{pct_text}",
                showarrow=False,
                xanchor="left",
                align="left",
                xshift=6,
                font=dict(size=11, color=color, family="Courier New, monospace"),
                bgcolor="rgba(255,255,255,0.88)",
                bordercolor=hex_to_rgba(color, 0.30),
                borderwidth=1,
                borderpad=3,
            )
    return fig


def build_instrument_allocation_pie_chart(da_frame, small_pie_texts=_small_pie_texts):
    """Build allocation pie chart by instrument for Home.

    chart_id: home_instrument_pie
    chiamato da: ui/pages/home.py
    """
    pie_text = small_pie_texts(da_frame["Controvalore"].tolist(), threshold=0.06)
    fig = go.Figure(
        go.Pie(
            labels=da_frame["Ticker"],
            values=da_frame["Controvalore"],
            hole=0.45,
            marker=dict(colors=[instrument_color(tk) for tk in da_frame["Ticker"]]),
            text=pie_text,
            textinfo="text",
            textposition="inside",
            sort=False,
            showlegend=True,
        )
    )
    return apply_settings(fig, "home_instrument_pie")


def build_category_allocation_pie_chart(
    da_frame,
    small_pie_texts=_small_pie_texts,
    settings: dict[str, Any] | None = None,
):
    """Build allocation pie chart by macro category for Home.

    chart_id: home_category_pie
    chiamato da: ui/pages/home.py
    """
    visible_categories = _resolve_visible_categories(settings)
    da_tip = da_frame.copy()
    da_tip["Categoria"] = da_tip["Tipo"].apply(macro_cat)
    grouped = da_tip.groupby("Categoria")["Controvalore"].sum().reindex(visible_categories).dropna().reset_index()
    if grouped.empty:
        return None
    pie_text = small_pie_texts(grouped["Controvalore"].tolist(), threshold=0.05)
    fig = go.Figure(
        go.Pie(
            labels=grouped["Categoria"],
            values=grouped["Controvalore"],
            hole=0.45,
            marker=dict(colors=[macro_color(c) for c in grouped["Categoria"]]),
            text=pie_text,
            textinfo="text",
            textposition="inside",
            sort=False,
            showlegend=True,
        )
    )
    return apply_settings(fig, "home_category_pie")


def build_instrument_bar_chart(data, x_col, title, text_formatter, xaxis_tickformat, decimals):
    """Build horizontal bar chart by instrument for Home.

    chart_id runtime: home_instrument_bar_perf oppure home_instrument_bar_pl
    chiamato da: ui/pages/home.py
    """
    _ = xaxis_tickformat
    fig = go.Figure(
        go.Bar(
            x=data[x_col],
            y=data["Ticker"],
            orientation="h",
            marker_color=[instrument_color(tk) for tk in data["Ticker"]],
            text=[text_formatter(v, decimals, signed=True) for v in data[x_col]],
            textposition="auto",
            textfont=dict(size=11),
            name=title,
        )
    )
    chart_id = "home_instrument_bar_perf" if "%" in str(x_col) or "perf" in str(title).lower() else "home_instrument_bar_pl"
    return apply_settings(fig, chart_id)


def build_category_bar_chart(
    cat_agg,
    y_col,
    title,
    text_formatter,
    yaxis_tickformat,
    settings: dict[str, Any] | None = None,
):
    """Build vertical bar chart by macro category for Home.

    chart_id runtime: home_category_bar_value / home_category_bar_pl / home_category_bar_perf
    chiamato da: ui/pages/home.py
    """
    _ = yaxis_tickformat
    visible_categories = _resolve_visible_categories(settings)
    chart_df = cat_agg[cat_agg["Categoria"].isin(visible_categories)].copy()
    fig = go.Figure(
        go.Bar(
            x=chart_df["Categoria"],
            y=chart_df[y_col],
            marker_color=[macro_color(c) for c in chart_df["Categoria"]],
            text=[text_formatter(v, 0 if y_col != "P/L %" else 2, signed=y_col != "Controvalore") for v in chart_df[y_col]],
            textposition="outside",
            textfont=dict(size=9),
            cliponaxis=False,
            name=title,
        )
    )
    if y_col == "Controvalore":
        chart_id = "home_category_bar_value"
    elif y_col == "P/L %":
        chart_id = "home_category_bar_perf"
    else:
        chart_id = "home_category_bar_pl"
    return apply_settings(fig, chart_id)

# build_asset_allocation_radar/build_quality_profile_radar (e il loro helper
# _build_radar_figure) sono state rimosse il 2026-07-07: duplicate di
# ui/charts/analitica.py, che e' la versione realmente importata da
# ui/dashboard_bundles.py — verificato con grep sull'intero repo.
