from __future__ import annotations

from typing import Any

import plotly.graph_objects as go

from ui.charts.settings import apply_settings

# Modulo shared del sottosistema grafici.
# Ruolo:
# - punto unico per chiudere la pipeline finale apply_settings + ritocchi runtime
# - usato dai builder di dominio sotto ui/charts/*


def empty_chart(chart_id: str) -> go.Figure:
    """Return an empty figure with the standard chart settings already applied.

    Uso: fallback coerente per builder che non hanno dati ma vogliono rispettare
    comunque il chart_id e i settings del grafico chiamante.
    """
    return apply_settings(go.Figure(), chart_id)


def finalize_chart(
    fig: go.Figure,
    chart_id: str,
    *,
    hovermode: str | None = None,
    uirevision: str | None = None,
    layout_updates: dict[str, Any] | None = None,
    xaxis_updates: dict[str, Any] | None = None,
    yaxis_updates: dict[str, Any] | None = None,
) -> go.Figure:
    """Apply the recurring chart finalization pipeline without altering visual semantics.

    Uso: helper shared chiamato dai builder di dominio quando il chart_id e'
    noto e serve chiudere il grafico con updates locali prima dei settings.
    """
    payload: dict[str, Any] = dict(layout_updates or {})
    if payload:
        fig.update_layout(**payload)
    if xaxis_updates:
        fig.update_xaxes(**xaxis_updates)
    if yaxis_updates:
        fig.update_yaxes(**yaxis_updates)
    fig = apply_settings(fig, chart_id)
    runtime_payload: dict[str, Any] = {}
    if hovermode is not None:
        runtime_payload["hovermode"] = hovermode
    if uirevision is not None:
        runtime_payload["uirevision"] = uirevision
    if runtime_payload:
        fig.update_layout(**runtime_payload)
    return fig
