"""Aree impilate «con segno»: i contributi positivi si impilano sopra lo zero, quelli negativi sotto, più una linea del totale netto.

Plotly impila le aree sommando i valori in ordine: con segni misti (guadagni e perdite insieme) i bordi cumulati non
corrispondono a nulla di leggibile e le perdite finiscono nascoste sotto i guadagni (TM-03). Qui ogni serie si divide in
parte positiva (gruppo `<prefisso>_pos`, impilato verso l'alto) e parte negativa (`<prefisso>_neg`, verso il basso); la
somma algebrica è la linea «Totale netto». Nessuna formula nuova: sono gli stessi valori, solo disegnati separando i segni.

Gli aspetti (opacità, spessori, colore della linea del totale e suo alone) NON sono qui: stanno nel blocco del grafico in
`ui/charts/settings.py` (`stack_opacity`, `stack_line_width`, `net_line_*`, `net_halo_*`), letto con `get_chart_setting`.
"""
from __future__ import annotations

from typing import Iterable

import pandas as pd
import plotly.graph_objects as go

from ui.charts.settings import get_chart_setting
from ui.formatting import fmt_eur_it

NET_NAME = "Totale netto"


def net_line_style(theme, chart_id: str | None = None) -> tuple[str, str]:
    """(colore della linea, colore dell'alone): colori dal blocco del grafico in settings.py (chiaro/scuro) e alone nel colore dello sfondo."""
    bg = str(getattr(theme, "bg_chart", None) or "#ffffff").lstrip("#")
    try:
        r, g, b = (int(bg[i:i + 2], 16) for i in (0, 2, 4))
        dark = (0.299 * r + 0.587 * g + 0.114 * b) < 110
    except (ValueError, IndexError):
        dark = False
    key = "net_line_color_dark" if dark else "net_line_color"
    color = get_chart_setting(chart_id, key, "#cbd5e1" if dark else "#475569") if chart_id else ("#cbd5e1" if dark else "#475569")
    return str(color), (f"#{bg}" if len(bg) == 6 else "#ffffff")


def zero_line_style(theme, chart_id: str) -> tuple[float, str]:
    """(spessore, colore) della linea dello zero: grigio scuro (chiaro sui temi scuri), dal blocco del grafico in settings.py."""
    bg = str(getattr(theme, "bg_chart", None) or "#ffffff").lstrip("#")
    try:
        r, g, b = (int(bg[i:i + 2], 16) for i in (0, 2, 4))
        dark = (0.299 * r + 0.587 * g + 0.114 * b) < 110
    except (ValueError, IndexError):
        dark = False
    color = get_chart_setting(chart_id, "zero_line_color_strong_dark" if dark else "zero_line_color_strong", "#9ca3af" if dark else "#4b5563")
    return float(get_chart_setting(chart_id, "zero_line_width", 2.0)), str(color)


def add_signed_stack(
    fig: go.Figure,
    x: pd.Series,
    series: Iterable[tuple[str, pd.Series, str]],
    *,
    prefix: str,
    chart_id: str,
    theme=None,
    show_net: bool = True,
) -> pd.Series:
    """Aggiunge le tracce impilate (positive e negative) e la linea del totale netto. Restituisce il totale netto.

    `series` = (nome, valori, colore). Tutte le serie hanno lo stesso asse `x`. I valori mancanti valgono 0.
    L'aspetto viene dal blocco `chart_id` di settings.py."""
    opacity = float(get_chart_setting(chart_id, "stack_opacity", 0.85))
    line_width = float(get_chart_setting(chart_id, "stack_line_width", 0.8))
    net_width = float(get_chart_setting(chart_id, "net_line_width", 2.2))
    halo_width = float(get_chart_setting(chart_id, "net_halo_width", 5.5))
    halo_opacity = float(get_chart_setting(chart_id, "net_halo_opacity", 0.9))
    net_color, halo_color = net_line_style(theme, chart_id)

    items = [(name, pd.to_numeric(pd.Series(values).reset_index(drop=True), errors="coerce").fillna(0.0), color)
             for name, values, color in series]
    x = pd.Series(x).reset_index(drop=True)
    net = pd.Series(0.0, index=x.index)
    for name, values, color in items:
        net = net.add(values, fill_value=0.0)
        for sign, clipped, group in (("pos", values.clip(lower=0.0), f"{prefix}_pos"), ("neg", values.clip(upper=0.0), f"{prefix}_neg")):
            if not (clipped != 0.0).any():
                continue
            hover = [f"{name}: {fmt_eur_it(v, 2, signed=True)}" if v != 0 else None for v in clipped]
            fig.add_trace(go.Scatter(
                x=x, y=clipped, name=name, mode="lines", stackgroup=group,
                legendgroup=name, showlegend=(sign == "pos" or not (values > 0).any()),
                line=dict(width=line_width, color=color), fillcolor=color, opacity=opacity,
                hoverinfo="text", hovertext=hover,
            ))
    if show_net and items:
        fig.add_trace(go.Scatter(     # alone: stacca la linea dalle aree colorate, senza voce in legenda né hover
            x=x, y=net, mode="lines", line=dict(width=halo_width, color=halo_color), opacity=halo_opacity,
            showlegend=False, hoverinfo="skip", name=f"{NET_NAME} (alone)",
        ))
        fig.add_trace(go.Scatter(
            x=x, y=net, name=NET_NAME, mode="lines", line=dict(width=net_width, color=net_color),
            hoverinfo="text", hovertext=[f"{NET_NAME}: {fmt_eur_it(v, 2, signed=True)}" for v in net],
        ))
    return net
