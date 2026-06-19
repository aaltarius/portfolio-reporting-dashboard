from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from ui.charts.settings import apply_settings, get_chart_setting

BASE100_RED = "rgba(220,38,38,0.95)"
BASE100_LABEL = "Base 100 = inizio investimento"

# Modulo shared per i grafici indicizzati in Base 100.
# Chart_id vivi che lo usano oggi:
# - quotazioni_quote_history
# - quotazioni_instrument_performance
# - analisi_category_performance
# - summary_history


def base100_hline_kwargs(chart_id: str) -> dict:
    """Return the standard Base100 hline config for a specific chart_id."""
    return dict(
        line_dash=str(get_chart_setting(chart_id, "base100_line_dash", "dash")),
        line_color=str(get_chart_setting(chart_id, "base100_line_color", BASE100_RED)),
        opacity=float(get_chart_setting(chart_id, "base100_line_opacity", 0.95)),
        line_width=float(get_chart_setting(chart_id, "base100_line_width", 1.8)),
    )


def _base100_last_x(fig):
    try:
        xs = []
        for tr in list(getattr(fig, "data", []) or []):
            x = getattr(tr, "x", None)
            if x is None:
                continue
            vals = [v for v in list(x) if v is not None]
            if vals:
                xs.extend(vals)
        if not xs:
            return None
        try:
            xs_dt = pd.to_datetime(xs, errors="coerce")
            xs_dt = xs_dt[~pd.isna(xs_dt)]
            if len(xs_dt) > 0:
                x_min = xs_dt.min()
                x_max = xs_dt.max()
                span = x_max - x_min
                if span <= pd.Timedelta(0):
                    return x_max
                return x_min + span * 0.95
        except Exception:
            pass
        try:
            nums = [float(v) for v in xs]
            x_min = min(nums)
            x_max = max(nums)
            span = x_max - x_min
            if span == 0:
                return x_max
            return x_min + span * 0.95
        except Exception:
            pass
    except Exception:
        pass
    return None


def _drop_base100_layout_annotations(fig):
    anns = list(getattr(fig.layout, "annotations", []) or [])
    if not anns:
        return fig
    kept = []
    for ann in anns:
        try:
            txt = str(getattr(ann, "text", "") or "")
        except Exception:
            txt = ""
        if "base 100" in txt.lower():
            continue
        kept.append(ann)
    try:
        fig.update_layout(annotations=kept)
    except Exception:
        pass
    return fig


def _force_base100_axis_title_red(fig):
    try:
        for key in fig.layout:
            k = str(key)
            if not (k.startswith("yaxis") or k.startswith("xaxis")):
                continue
            axis = getattr(fig.layout, k, None)
            title = getattr(axis, "title", None)
            text = str(getattr(title, "text", "") or "")
            if "base 100" not in text.lower():
                continue
            fig.update_layout({k: dict(title=dict(font=dict(color=BASE100_RED)))})
    except Exception:
        pass
    return fig


def _add_base100_text_trace(fig):
    x = _base100_last_x(fig)
    if x is None:
        return fig
    try:
        fig.add_trace(
            go.Scatter(
                x=[x],
                y=[100],
                mode="text",
                text=[BASE100_LABEL],
                textposition="top left",
                textfont=dict(size=10, color=BASE100_RED),
                showlegend=False,
                hoverinfo="skip",
                hovertemplate=None,
                cliponaxis=False,
                name="__base100_label__",
            )
        )
    except Exception:
        pass
    return fig


def apply_settings_base100(fig, chart_id: str):
    """Apply generic settings plus the extra Base100 cleanup/annotation pass.

    Uso: builder Base100-oriented in ui/charts/quotazioni.py e ui/charts/summary.py.
    """
    res = apply_settings(fig, chart_id)
    fig = res if res is not None else fig
    fig = _drop_base100_layout_annotations(fig)
    fig = _force_base100_axis_title_red(fig)
    fig = _add_base100_text_trace(fig)
    return fig
