from datetime import date

import pandas as pd
import plotly.graph_objects as go

from core.asset_categories import get_selected_category_codes
from ui.charts.extrema import add_extrema_markers
from ui.charts.runtime import finalize_chart
from ui.charts.settings import apply_settings
from ui.formatting import fmt_eur_it, hex_to_rgba
from ui.theme import P, macro_color

# Ownership reale:
# - pagina: ui/pages/overview.py
# - chart_id principali: overview_pl_portafoglio, overview_pl_categoria


def _with_current_point(
    dates: pd.Series,
    series: pd.Series,
    current_value: float,
) -> tuple[pd.Series, pd.Series]:
    chart_dates = pd.to_datetime(dates, errors="coerce").copy()
    chart_series = pd.to_numeric(series, errors="coerce").copy()
    if chart_dates.empty or chart_series.empty:
        return chart_dates, chart_series

    last_value = float(chart_series.iloc[-1]) if pd.notna(chart_series.iloc[-1]) else 0.0
    if abs(last_value - float(current_value)) <= 0.01:
        return chart_dates, chart_series

    current_date = pd.Timestamp(date.today())
    if pd.notna(chart_dates.iloc[-1]) and chart_dates.iloc[-1].normalize() == current_date:
        chart_series.iloc[-1] = float(current_value)
        return chart_dates, chart_series

    # Mantieni la logica "niente weekend" dell'app: nel fine settimana
    # non mostriamo una nuova data, ma riallineiamo l'ultimo punto visibile
    # al valore corrente del portafoglio/categoria.
    if current_date.weekday() >= 5 and len(chart_series) > 0:
        chart_series.iloc[-1] = float(current_value)
        return chart_dates, chart_series

    chart_dates = pd.concat([chart_dates, pd.Series([current_date])], ignore_index=True)
    chart_series = pd.concat([chart_series, pd.Series([float(current_value)])], ignore_index=True)
    return chart_dates, chart_series


def _uirevision_key(view: str, dates: pd.Series, values: pd.Series) -> str:
    last_date = ""
    last_value = 0.0
    if len(dates):
        try:
            last_date = str(pd.to_datetime(dates.iloc[-1], errors="coerce").date())
        except Exception:
            last_date = str(dates.iloc[-1])
    if len(values):
        try:
            last_value = float(pd.to_numeric(values.iloc[-1], errors="coerce"))
        except Exception:
            last_value = 0.0
    return f"pl-home-v34-{view}-{len(values)}-{last_date}-{round(last_value, 2)}"


def build_overview_time_chart(dfh_top, da_frame, view, pl_color, pl_total, chart_bg, dfmt, theme, settings=None):
    """Build the selected overview chart shown above the main tabs.

    chart_id runtime: overview_pl_portafoglio / overview_pl_categoria
    chiamato da: ui/pages/overview.py
    """
    _ = chart_bg, dfmt
    if view == "P/L per Categoria":
        visible_categories = list(get_selected_category_codes(settings))
        cat_map = da_frame.set_index("Ticker")["Categoria"].to_dict() if da_frame is not None and (not da_frame.empty) else {}
        pl_cols = [c for c in dfh_top.columns if c.startswith("PL_")]
        fig = go.Figure()
        for cat in visible_categories:
            ticker_cols = [c for c in pl_cols if cat_map.get(c[3:]) == cat]
            if ticker_cols:
                series = pd.to_numeric(dfh_top[ticker_cols].sum(axis=1), errors="coerce")
                current_cat_pl = 0.0
                if da_frame is not None and not da_frame.empty and "Categoria" in da_frame.columns and "P/L €" in da_frame.columns:
                    current_cat_pl = float(pd.to_numeric(da_frame.loc[da_frame["Categoria"] == cat, "P/L €"], errors="coerce").fillna(0.0).sum())
                chart_dates, chart_series = _with_current_point(dfh_top["Data"], series, current_cat_pl)
                fig.add_trace(
                    go.Scatter(
                        x=chart_dates,
                        y=chart_series,
                        name=cat,
                        mode="lines",
                        stackgroup="one",
                        line=dict(color=macro_color(cat), width=1.2),
                        fillcolor=macro_color(cat),
                        opacity=0.82,
                        hovertemplate=f"{cat}: € %{{y:,.2f}}<extra></extra>",
                    )
                )
        total_all = pd.to_numeric(dfh_top[pl_cols].sum(axis=1), errors="coerce").dropna() if pl_cols else pd.Series(dtype=float)
        if len(total_all) >= 2:
            extrema_x = dfh_top.loc[total_all.index, "Data"]
            add_extrema_markers(
                fig,
                "overview_pl_categoria",
                extrema_x,
                total_all,
                theme=theme,
                value_formatter=lambda v: f"{v:,.0f} €".replace(",", "."),
            )
        fig.update_layout(hovermode="x unified", uirevision="pl-cat-home")
        return apply_settings(fig, "overview_pl_categoria")

    fig = go.Figure()
    if view == "P/L del portafoglio":
        pl_cols = [c for c in dfh_top.columns if c.startswith("PL_")]
        pl_attuale = pd.to_numeric(dfh_top[pl_cols].sum(axis=1), errors="coerce") if pl_cols else pd.Series(0.0, index=dfh_top.index)
        realized_net = pd.to_numeric(dfh_top.get("P/L Realizzato Netto", 0), errors="coerce").fillna(0.0)
        pl_storico = pl_attuale + realized_net
        current_open_pl = 0.0
        if da_frame is not None and not da_frame.empty and "P/L €" in da_frame.columns:
            current_open_pl = float(pd.to_numeric(da_frame["P/L €"], errors="coerce").fillna(0.0).sum())
        chart_dates_total, chart_pl_storico = _with_current_point(dfh_top["Data"], pl_storico, float(pl_total))
        chart_dates_open, chart_pl_attuale = _with_current_point(dfh_top["Data"], pl_attuale, current_open_pl)
        fig.add_trace(
            go.Scatter(
                x=chart_dates_total,
                y=chart_pl_storico,
                mode="lines",
                name="P/L storico",
                line=dict(color=pl_color, width=3.0),
                fill="tozeroy",
                fillcolor=hex_to_rgba(theme.colors["success"], 0.08) if pl_total >= 0 else hex_to_rgba(theme.colors["danger"], 0.08),
                hovertemplate="Data: %{x|%d/%m/%Y}<br>P/L complessivo: € %{y:,.2f}<extra></extra>",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=chart_dates_open,
                y=chart_pl_attuale,
                mode="lines",
                name="P/L pos. aperte",
                line=dict(color=P["blue"], width=2.2, dash="dash"),
                hovertemplate="Data: %{x|%d/%m/%Y}<br>P/L posizioni aperte: € %{y:,.2f}<extra></extra>",
            )
        )
        add_extrema_markers(
            fig,
            "overview_pl_portafoglio",
            chart_dates_total,
            chart_pl_storico,
            theme=theme,
            value_formatter=lambda v: fmt_eur_it(v, 2),
        )
        return finalize_chart(
            fig,
            "overview_pl_portafoglio",
            hovermode="x unified",
            uirevision=_uirevision_key(view, chart_dates_total, chart_pl_storico),
        )

    return finalize_chart(fig, "overview_pl_portafoglio", hovermode="x unified", uirevision=_uirevision_key(view, dfh_top["Data"], pd.Series(dtype=float)))
