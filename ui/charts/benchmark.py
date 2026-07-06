from __future__ import annotations

from datetime import date as _date
from dateutil.relativedelta import relativedelta
from typing import Any

import pandas as pd
import plotly.graph_objects as go

from ui.charts.settings import apply_settings
from ui.theme import P, macro_color


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


_PERIOD_DELTAS: dict[str, relativedelta | None] = {
    "1M": relativedelta(months=1),
    "3M": relativedelta(months=3),
    "6M": relativedelta(months=6),
    "1A": relativedelta(years=1),
    "3A": relativedelta(years=3),
    "Tutto": None,
}


def resolve_period_start_date(sorted_dates: list[str], period: str) -> str:
    """Calcola la start_date sottraendo il periodo dalla data più recente nello storico."""
    if not sorted_dates:
        return ""
    first = sorted_dates[0][:10]
    last = sorted_dates[-1][:10]
    delta = _PERIOD_DELTAS.get(period)
    if delta is None:
        return first
    ref = _date.fromisoformat(last) - delta
    computed = ref.strftime("%Y-%m-%d")
    return computed if computed >= first else first


def get_all_historical_tickers(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Ritorna tutti i ticker mai presenti in storico_prezzi, con flag active.

    "active" significa "in portafoglio ora" (stato == "aperto"): uno strumento
    chiuso ha ancora un record in strumenti (l'anagrafica resta per lo
    storico) ma non conta come posseduto, esattamente come un ticker mai
    acquistato (es. un benchmark di riferimento o uno strumento solo
    osservato)."""
    storico: dict[str, dict[str, float]] = data.get("storico_prezzi") or {}
    strumenti: list[dict] = data.get("strumenti") or []
    active_set = {
        s.get("ticker", "")
        for s in strumenti
        if s.get("ticker") and str(s.get("stato", "aperto")) == "aperto"
    }
    all_tickers: set[str] = set()
    for prices in storico.values():
        all_tickers.update(prices.keys())
    return [
        {"ticker": tk, "active": tk in active_set}
        for tk in sorted(all_tickers)
    ]


def build_normalized_performance_chart(
    storico_prezzi: dict[str, dict[str, float]],
    tickers: list[str],
    start_date: str,
    *,
    align_starts: bool = False,
) -> go.Figure:
    """Grafico a linee sovrapposte: rendimento % normalizzato a 0%.

    align_starts=False (default): asse X = date di calendario, tutte le serie
        partono da start_date (o dalla prima data disponibile se start_date è
        antecedente allo storico).

    align_starts=True: asse X = giorni trascorsi dal punto zero di ciascuna
        serie. Ogni strumento parte da (giorno 0, rendimento 0%) usando la
        propria prima data disponibile, indipendentemente dal calendario.
        Questo consente di confrontare la traiettoria di performance anche fra
        strumenti entrati in portafoglio in momenti diversi.
    """
    chart_id = "benchmark_normalized_performance"
    fig = go.Figure()
    if not storico_prezzi or not tickers:
        return apply_settings(fig, chart_id)

    sorted_dates = sorted(storico_prezzi.keys())

    palette = [
        P["blue"], P["orange"], P["green"], P["red"],
        "#7E57C2", "#42A5F5", "#FF7043", "#9CCC65", "#AB47BC", "#26C6DA",
    ]

    added = 0
    for tk in tickers:
        # Raccoglie (date, prezzo) per questo ticker — tutti i punti disponibili
        series: list[tuple[str, float]] = []
        for d in sorted_dates:
            price = storico_prezzi[d].get(tk)
            if price is None:
                continue
            series.append((d, float(price)))

        if not series:
            continue

        if align_starts:
            # Modalità allineamento: usa tutta la storia del ticker, parte da giorno 0
            ref_price = series[0][1]
            if ref_price == 0.0:
                continue
            x_vals = list(range(len(series)))
            y_vals = [(p / ref_price) - 1.0 for _, p in series]
            hover = f"<b>{tk}</b><br>Giorno %{{x}}<br>Rendimento: %{{y:+.2%}}<extra></extra>"
        else:
            # Modalità data comune: taglia dalla start_date (o prima data utile)
            ref_price = None
            trim_idx = 0
            for i, (d, p) in enumerate(series):
                if d >= start_date:
                    ref_price = p
                    trim_idx = i
                    break
            if ref_price is None or ref_price == 0.0:
                continue
            series = series[trim_idx:]
            x_vals = [pd.to_datetime(d) for d, _ in series]
            y_vals = [(p / ref_price) - 1.0 for _, p in series]
            hover = f"<b>{tk}</b><br>%{{x|%d/%m/%Y}}<br>Rendimento: %{{y:+.2%}}<extra></extra>"

        color = palette[added % len(palette)]
        fig.add_trace(
            go.Scatter(
                x=x_vals,
                y=y_vals,
                mode="lines",
                name=tk,
                line=dict(color=color, width=2.2),
                hovertemplate=hover,
            )
        )
        added += 1

    fig.add_hline(y=0, line_dash="dot", line_color="rgba(100,116,139,0.4)", line_width=1)
    x_title = "Giorni dal punto zero" if align_starts else ""
    title = "Performance normalizzata — base 0% (origini allineate)" if align_starts else "Performance normalizzata — base 0%"
    fig.update_layout(
        height=420,
        margin=dict(l=8, r=8, t=42, b=16),
        title=title,
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    fig.update_yaxes(title_text="Rendimento %", tickformat="+.1%", automargin=True, zeroline=False)
    fig.update_xaxes(title_text=x_title, automargin=True, rangeslider=dict(visible=False))
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
