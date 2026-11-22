"""ui/form_server/parita_charts.py — figure Plotly della pagina «A parità di investimento» (PA-01).

Producono il JSON della figura (`fig.to_json()`): la pagina le disegna nel browser con `/assets/plotly.min.js`.
Assi con titolo, ticker sulle etichette (il nome completo è nel suggerimento al mouse), formato numerico italiano.
Con dati vuoti restituiscono una stringa vuota. Colori da `FORM_COLORS`.
"""
from __future__ import annotations

import plotly.graph_objects as go

from ui.theme_tokens import resolve_form_colors


def _font(C: dict) -> dict:
    return dict(family="system-ui,-apple-system,'Segoe UI',sans-serif", size=12, color=C["slate-700"])


_LINES = ["emerald-600", "blue-500", "amber-500", "orange-500", "red-500", "green-500", "slate-500", "indigo-200"]


def _base_layout(C: dict, **extra) -> dict:
    layout = dict(
        font=_font(C), paper_bgcolor=C["white"], plot_bgcolor=C["white"], separators=",.",
        margin=dict(l=70, r=20, t=16, b=60), hoverlabel=dict(font=_font(C), bgcolor=C["white"]),
    )
    layout.update(extra)
    return layout


def _safe(fig: go.Figure) -> str:
    return fig.to_json().replace("<", "\\u003c")


def pl_bars_figure(rows) -> str:
    """Colonne verticali del P/L in euro per strumento (ticker sull'asse x), riferimento in indaco."""
    C = resolve_form_colors()
    if not rows:
        return ""
    colors = [C["indigo-600"] if r.is_reference else (C["emerald-600"] if r.pl >= 0 else C["red-600"]) for r in rows]
    fig = go.Figure(go.Bar(
        x=[r.ticker for r in rows], y=[round(r.pl, 2) for r in rows], marker=dict(color=colors),
        customdata=[[r.name, round(r.ret * 100, 2), "" if r.adv_eur is None else round(r.adv_eur, 2)] for r in rows],
        hovertemplate="<b>%{x}</b> · %{customdata[0]}<br>P/L: %{y:,.2f} €<br>Rendimento: %{customdata[1]:.2f}%"
                      "<extra></extra>"))
    fig.update_layout(**_base_layout(C, 
        height=340, bargap=0.25, showlegend=False,
        xaxis=dict(title=dict(text="Strumento (ticker)"), tickangle=-55, automargin=True, tickfont=dict(size=10)),
        yaxis=dict(title=dict(text="Guadagno / perdita (€)"), gridcolor=C["slate-200"], zerolinecolor=C["slate-500"],
                   tickformat=",.0f", ticksuffix=" €")))
    return _safe(fig)


def paths_figure(paths, capital: float, reference: str, names: dict[str, str]) -> str:
    """Valore giornaliero del capitale per strumento, ciascuno sulle proprie date; linea tratteggiata = capitale."""
    C = resolve_form_colors()
    series = {tk: pts for tk, pts in (paths or {}).items() if pts}
    if not series:
        return ""
    fig = go.Figure()
    days = sorted({d for pts in series.values() for d, _ in pts})
    fig.add_trace(go.Scatter(x=[days[0], days[-1]], y=[capital, capital], mode="lines", name="Capitale iniziale",
                             line=dict(color=C["slate-500"], width=1, dash="dash"), hoverinfo="skip"))
    others = [tk for tk in series if tk != reference]
    for i, tk in enumerate(others + ([reference] if reference in series else [])):
        pts = series[tk]
        is_ref = tk == reference
        fig.add_trace(go.Scatter(
            x=[d for d, _ in pts], y=[round(v, 2) for _, v in pts], mode="lines", name=tk,
            line=dict(color=C["indigo-600"] if is_ref else C[_LINES[i % len(_LINES)]], width=3.2 if is_ref else 1.6),
            opacity=1 if is_ref else 0.8, customdata=[names.get(tk, tk)] * len(pts),
            hovertemplate="<b>" + tk + "</b> · %{customdata}<br>%{x|%d/%m/%Y}: %{y:,.2f} €<extra></extra>"))
    fig.update_layout(**_base_layout(C, 
        height=420, hovermode="closest", margin=dict(l=70, r=10, t=16, b=60),
        legend=dict(orientation="v", x=1.01, y=1, font=dict(size=10), itemwidth=30),
        xaxis=dict(title=dict(text="Data"), gridcolor=C["slate-100"], tickformat="%d/%m"),
        yaxis=dict(title=dict(text="Valore del capitale (€)"), gridcolor=C["slate-200"], tickformat=",.0f",
                   ticksuffix=" €")))
    return _safe(fig)
