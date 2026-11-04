from __future__ import annotations

import logging
import time

import streamlit as st

from core.render_profiler import record_render_event
from ui.formatting import fmt_eur_it

_PREPARED_FIGURE_IDS: set[int] = set()
_PREPARED_FIGURE_IDS_MAX = 2048


def _figure_runtime_prepared(fig) -> bool:
    try:
        return bool(getattr(fig, "_sestante_streamlit_runtime_prepared", False))
    except Exception:
        return id(fig) in _PREPARED_FIGURE_IDS


def _mark_figure_runtime_prepared(fig) -> None:
    try:
        setattr(fig, "_sestante_streamlit_runtime_prepared", True)
        return
    except Exception:
        pass
    _PREPARED_FIGURE_IDS.add(id(fig))
    if len(_PREPARED_FIGURE_IDS) > _PREPARED_FIGURE_IDS_MAX:
        _PREPARED_FIGURE_IDS.clear()


def _default_plotly_config(config):
    payload = dict(config or {}) if isinstance(config, dict) else {}
    payload.setdefault("responsive", True)
    payload.setdefault("displaylogo", False)
    return payload


def reset_plotly_auto_key_counter() -> None:
    """Rende stabili le key automatiche Plotly tra rerun dello stesso processo."""

    try:
        safe_plotly_chart._counter = 0
    except Exception:
        pass


def clear_plotly_theme_overrides(fig):
    try:
        if getattr(fig.layout, "font", None):
            fig.layout.font.color = None
            fig.layout.font.size = 11
        if getattr(fig.layout, "legend", None):
            fig.layout.legend.bgcolor = "rgba(0,0,0,0)"
            fig.layout.legend.bordercolor = None
            fig.layout.legend.title.text = ""
            if getattr(fig.layout.legend, "font", None):
                fig.layout.legend.font.color = None
                fig.layout.legend.font.size = 10
        if getattr(fig.layout, "hoverlabel", None):
            fig.layout.hoverlabel.bgcolor = None
            if getattr(fig.layout.hoverlabel, "font", None):
                fig.layout.hoverlabel.font.color = None
                fig.layout.hoverlabel.font.size = 10
        title_obj = getattr(fig.layout, "title", None)
        if title_obj is not None:
            title_text = getattr(title_obj, "text", None)
            if title_text not in (None, "undefined") and getattr(title_obj, "font", None):
                title_obj.font.color = None
                title_obj.font.size = 14
        if getattr(fig.layout, "annotations", None):
            for ann in fig.layout.annotations:
                if getattr(ann, "font", None):
                    ann.font.color = None
                    ann.font.size = min(getattr(ann.font, "size", 11) or 11, 11)
        for axis in list(fig.select_xaxes()) + list(fig.select_yaxes()):
            axis.automargin = True
            axis.color = None
            axis.gridcolor = None
            axis.zerolinecolor = None
            if getattr(axis, "tickfont", None):
                axis.tickfont.color = None
                axis.tickfont.size = 10
            else:
                axis.tickfont = dict(size=10)
            if getattr(axis, "title", None):
                axis_title_text = getattr(axis.title, "text", None)
                if axis_title_text in (None, "undefined"):
                    axis.title.text = ""
                if getattr(axis.title, "font", None):
                    axis.title.font.color = None
                    axis.title.font.size = 11
                else:
                    axis.title.font = dict(size=11)
        if getattr(fig.layout, "polar", None):
            polar = fig.layout.polar
            polar.bgcolor = "rgba(0,0,0,0)"
            for subaxis_name in ("radialaxis", "angularaxis"):
                subaxis = getattr(polar, subaxis_name, None)
                if subaxis:
                    if getattr(subaxis, "tickfont", None):
                        subaxis.tickfont.color = None
                        subaxis.tickfont.size = 9 if subaxis_name == "angularaxis" else 10
                    else:
                        subaxis.tickfont = dict(size=9 if subaxis_name == "angularaxis" else 10)
                    if getattr(subaxis, "gridcolor", None) is not None:
                        subaxis.gridcolor = None
    except Exception:
        pass


def count_legend_items(fig):
    try:
        total = 0
        for tr in fig.data:
            if getattr(tr, "showlegend", True) is False:
                continue
            labels = getattr(tr, "labels", None)
            if labels is not None:
                try:
                    total += len(labels)
                except Exception:
                    total += 1
            else:
                total += 1
        return max(total, 1)
    except Exception:
        return 1


def add_min_max_annotations(fig):
    try:
        for trace in fig.data:
            mode = getattr(trace, "mode", "") or ""
            trace_type = type(trace).__name__.lower()
            if trace_type not in ("scatter", "scattergl"):
                continue
            if "lines" not in mode and "line" not in mode:
                continue
            if getattr(trace, "showlegend", True) is False:
                continue
            yaxis_ref = getattr(trace, "yaxis", "y") or "y"
            if yaxis_ref not in ("y", "y1", None, ""):
                continue
            xs = getattr(trace, "x", None)
            ys = getattr(trace, "y", None)
            if xs is None or ys is None:
                continue
            try:
                ys_clean = [(i, float(v)) for i, v in enumerate(ys) if v is not None]
            except (TypeError, ValueError):
                continue
            if len(ys_clean) < 3:
                continue
            i_max = max(ys_clean, key=lambda t: t[1])
            i_min = min(ys_clean, key=lambda t: t[1])
            color = getattr(trace.line, "color", "#888") if getattr(trace, "line", None) else "#888"
            if not color:
                color = "#888"
            labels = [
                (i_max[0], i_max[1], f"▲ {(fmt_eur_it(i_max[1], 0) if abs(i_max[1]) >= 100 else f'{i_max[1]:.2f}')}", -28),
                (i_min[0], i_min[1], f"▼ {(fmt_eur_it(i_min[1], 0) if abs(i_min[1]) >= 100 else f'{i_min[1]:.2f}')}", 28),
            ]
            for idx, val, label, ay in labels:
                fig.add_annotation(
                    x=xs[idx],
                    y=val,
                    text=label,
                    showarrow=True,
                    arrowhead=2,
                    arrowsize=1,
                    arrowwidth=1.2,
                    arrowcolor=color,
                    ax=0,
                    ay=ay,
                    font=dict(size=9, color=color),
                    bgcolor="rgba(0,0,0,0)",
                    bordercolor="rgba(0,0,0,0)",
                    xanchor="center",
                )
    except Exception:
        pass


def safe_plotly_chart(
    fig,
    *,
    get_chart_setting,
    orig_plotly_chart,
    fallback_plotly_chart,
    **kwargs,
):
    kwargs.setdefault("width", "stretch")
    kwargs.setdefault("theme", "streamlit")
    kwargs["config"] = _default_plotly_config(kwargs.get("config"))
    try:
        if not _figure_runtime_prepared(fig):
            clear_plotly_theme_overrides(fig)
            has_lines = any(
                "lines" in (getattr(tr, "mode", "") or "")
                for tr in fig.data
                if type(tr).__name__.lower() in ("scatter", "scattergl")
            )
            if has_lines and (not fig.layout.annotations) and bool(
                get_chart_setting("_default_timeseries", "auto_streamlit_extrema", False)
            ):
                add_min_max_annotations(fig)
            _mark_figure_runtime_prepared(fig)
    except Exception:
        pass
    if kwargs.get("key") is None:
        counter = getattr(safe_plotly_chart, "_counter", 0) + 1
        safe_plotly_chart._counter = counter
        kwargs["key"] = f"plotly_{counter}"
    current_orig = orig_plotly_chart
    if current_orig is safe_plotly_chart:
        current_orig = fallback_plotly_chart
    profile_enabled = bool(st.session_state.get("_plotly_profile_enabled", False))
    if not profile_enabled:
        return current_orig(fig, **kwargs)

    trace_count = len(getattr(fig, "data", []) or [])
    total_points = 0
    for tr in getattr(fig, "data", []) or []:
        xs = getattr(tr, "x", None)
        ys = getattr(tr, "y", None)
        if ys is not None:
            try:
                total_points += len(ys)
                continue
            except Exception:
                pass
        if xs is not None:
            try:
                total_points += len(xs)
            except Exception:
                pass
    chart_label = str(
        getattr(getattr(fig.layout, "title", None), "text", "")
        or kwargs.get("key")
        or "plotly_chart"
    )
    t0 = time.perf_counter()
    try:
        result = current_orig(fig, **kwargs)
    finally:
        try:
            elapsed = time.perf_counter() - t0
            record_render_event(
                "PlotlyRender",
                "st.plotly_chart",
                elapsed,
                detail=f"label={chart_label}; traces={trace_count}; points={total_points}; key={kwargs.get('key')}",
                count=trace_count,
            )
            logging.getLogger("portafoglio").info(
                "Plotly render: %.3fs | label=%s | traces=%s | points=%s | key=%s",
                elapsed,
                chart_label,
                trace_count,
                total_points,
                kwargs.get("key"),
            )
        except Exception:
            pass
    return result


def bind_safe_plotly_chart(*, get_chart_setting, orig_plotly_chart, fallback_plotly_chart=None):
    if fallback_plotly_chart is None:
        fallback_plotly_chart = orig_plotly_chart

    def _bound_safe_plotly_chart(fig, **kwargs):
        return safe_plotly_chart(
            fig,
            get_chart_setting=get_chart_setting,
            orig_plotly_chart=orig_plotly_chart,
            fallback_plotly_chart=fallback_plotly_chart,
            **kwargs,
        )

    return _bound_safe_plotly_chart


__all__ = [
    "add_min_max_annotations",
    "bind_safe_plotly_chart",
    "clear_plotly_theme_overrides",
    "count_legend_items",
    "reset_plotly_auto_key_counter",
    "safe_plotly_chart",
]
