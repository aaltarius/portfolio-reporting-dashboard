from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from ui.charts.settings import get_chart_setting
from ui.formatting import fmt_eur_it, fmt_num_it, fmt_pct_it
from ui.theme import P

# Modulo shared per i marker MAX/MIN.
# Non appartiene a una pagina singola: viene richiamato dai builder di dominio
# quando il chart_id abilita show_extrema o usa una semantica Base100 multi-serie.


def _resolve_chart_color(value, role: str = "max", theme=None):
    """Resolve semantic extrema colors to concrete CSS/Plotly colors."""
    if value in (None, "", "auto"):
        value = "success" if role == "max" else "danger"
    if isinstance(value, str):
        key = value.lower()
        if theme is not None and hasattr(theme, "colors") and key in getattr(theme, "colors", {}):
            return theme.colors[key]
        aliases = {
            "success": P.get("green", "#16a34a"),
            "green": P.get("green", "#16a34a"),
            "danger": P.get("red", "#dc2626"),
            "red": P.get("red", "#dc2626"),
            "orange": P.get("orange", "#f59e0b"),
            "blue": P.get("blue", "#2563eb"),
            "gray": P.get("gray", "#6b7280"),
        }
        return aliases.get(key, value)
    return value


def _format_extrema_value(value, chart_id: str, value_formatter=None) -> str:
    """Format an extrema value according to the chart-specific setting profile."""
    if value_formatter is not None:
        try:
            return value_formatter(value)
        except Exception:
            pass
    fmt = str(get_chart_setting(chart_id, "extrema_value_format", "eur0"))
    if fmt == "eur2":
        return fmt_eur_it(float(value), 2)
    if fmt == "eur0":
        return fmt_eur_it(float(value), 0)
    if fmt == "pct1":
        return fmt_pct_it(float(value), 1)
    if fmt == "pct2":
        return fmt_pct_it(float(value), 2)
    if fmt == "num0":
        return fmt_num_it(float(value), 0, signed=False)
    if fmt == "num2":
        return fmt_num_it(float(value), 2, signed=False)
    return str(value)


def _extrema_labels(chart_id: str):
    """Return the label pair used for MAX/MIN on a specific chart_id."""
    style = str(get_chart_setting(chart_id, "extrema_labels", "short")).lower()
    if style == "long":
        return "Massimo", "Minimo"
    if style == "absolute":
        return "Massimo assoluto", "Minimo assoluto"
    return "MAX", "MIN"


def add_extrema_markers(
    fig,
    chart_id: str,
    x_values,
    y_values,
    *,
    theme=None,
    series_name: str | None = None,
    yaxis: str | None = None,
    value_formatter=None,
    max_color=None,
    min_color=None,
):
    """Add extrema markers to a single-series chart.

    Uso tipico: andamento/overview/analisi category temporal, dove il builder
    controlla esplicitamente quali valori passare e su quale asse Y annotare.
    """
    if not bool(get_chart_setting(chart_id, "show_extrema", False)):
        return fig
    mode = str(get_chart_setting(chart_id, "extrema_mode", "max_min")).lower()
    if mode in {"off", "none", "false"}:
        return fig
    try:
        s = pd.Series(list(y_values))
        x = pd.Series(list(x_values))
        y_num = pd.to_numeric(s, errors="coerce")
        valid = y_num.notna()
        if valid.sum() == 0:
            return fig
        y_num = y_num[valid]
        x = x[valid]
    except Exception:
        return fig

    idx_max = y_num.idxmax()
    idx_min = y_num.idxmin()
    max_label, min_label = _extrema_labels(chart_id)
    include_series = bool(get_chart_setting(chart_id, "extrema_include_series", False))
    multiline = bool(get_chart_setting(chart_id, "extrema_multiline", False))
    points = []
    if mode in {"max_min", "both", "max_only", "max"}:
        val = float(y_num.loc[idx_max])
        value_txt = _format_extrema_value(val, chart_id, value_formatter)
        label = max_label
        if include_series and series_name:
            label = f"{label}<br>{series_name}" if multiline else f"{label} · {series_name}"
        text = f"{label}<br>{value_txt}" if multiline else f"{label}: {value_txt}"
        points.append((x.loc[idx_max], val, text, "max"))
    if mode in {"max_min", "both", "min_only", "min"} and len(y_num) > 1:
        val = float(y_num.loc[idx_min])
        value_txt = _format_extrema_value(val, chart_id, value_formatter)
        label = min_label
        if include_series and series_name:
            label = f"{label}<br>{series_name}" if multiline else f"{label} · {series_name}"
        text = f"{label}<br>{value_txt}" if multiline else f"{label}: {value_txt}"
        points.append((x.loc[idx_min], val, text, "min"))
    if not points:
        return fig

    max_col = _resolve_chart_color(max_color if max_color is not None else get_chart_setting(chart_id, "extrema_max_color", "success"), "max", theme)
    min_col = _resolve_chart_color(min_color if min_color is not None else get_chart_setting(chart_id, "extrema_min_color", "danger"), "min", theme)
    kwargs = dict(
        x=[p[0] for p in points],
        y=[p[1] for p in points],
        mode="markers+text",
        showlegend=False,
        marker=dict(
            size=int(get_chart_setting(chart_id, "extrema_marker_size", 10)),
            color=[max_col if p[3] == "max" else min_col for p in points],
            symbol=[get_chart_setting(chart_id, "extrema_max_symbol", "triangle-up") if p[3] == "max" else get_chart_setting(chart_id, "extrema_min_symbol", "triangle-down") for p in points],
            line=dict(
                color=get_chart_setting(chart_id, "extrema_marker_line_color", "white"),
                width=float(get_chart_setting(chart_id, "extrema_marker_line_width", 1.5)),
            ),
        ),
        text=[p[2] for p in points],
        textposition=[get_chart_setting(chart_id, "extrema_max_textposition", "top center") if p[3] == "max" else get_chart_setting(chart_id, "extrema_min_textposition", "bottom center") for p in points],
        cliponaxis=bool(get_chart_setting(chart_id, "extrema_cliponaxis", False)),
        textfont=dict(
            size=int(get_chart_setting(chart_id, "extrema_font_size", 9)),
            color=[max_col if p[3] == "max" else min_col for p in points],
        ),
        hovertemplate="%{text}<extra></extra>",
    )
    if yaxis and yaxis != "y":
        kwargs["yaxis"] = yaxis
    fig.add_trace(go.Scatter(**kwargs))
    return fig


def add_global_extrema_markers(fig, frame, chart_id: str):
    """Add extrema markers to a wide multi-series frame after reducing to global max/min.

    Uso tipico: confronti Base100 multi-linea come Quotazioni per strumento o
    macro-categoria, dove il massimo/minimo viene cercato sull'intero frame.
    """
    if not bool(get_chart_setting(chart_id, "show_extrema", False)):
        return fig
    if frame is None or frame.empty or frame.shape[1] == 0:
        return fig
    long = frame.stack().dropna().reset_index()
    if long.empty:
        return fig
    long.columns = ["Data", "Serie", "Valore"]
    max_row = long.loc[long["Valore"].idxmax()]
    min_row = long.loc[long["Valore"].idxmin()]
    max_label, min_label = _extrema_labels(chart_id)
    include_series = bool(get_chart_setting(chart_id, "extrema_include_series", True))
    multiline = bool(get_chart_setting(chart_id, "extrema_multiline", True))
    xs, ys, texts, kinds = [], [], [], []
    for row, label, kind in [(max_row, max_label, "max"), (min_row, min_label, "min")]:
        xs.append(row["Data"])
        ys.append(float(row["Valore"]))
        value_txt = _format_extrema_value(float(row["Valore"]), chart_id)
        serie_txt = str(row["Serie"])
        if include_series:
            label_txt = f"{label}<br>{serie_txt}" if multiline else f"{label} · {serie_txt}"
        else:
            label_txt = label
        texts.append(f"{label_txt}<br>{value_txt}" if multiline else f"{label_txt}: {value_txt}")
        kinds.append(kind)
    max_col = _resolve_chart_color(get_chart_setting(chart_id, "extrema_max_color", "success"), "max")
    min_col = _resolve_chart_color(get_chart_setting(chart_id, "extrema_min_color", "danger"), "min")
    fig.add_trace(
        go.Scatter(
            x=xs,
            y=ys,
            mode="markers+text",
            showlegend=False,
            marker=dict(
                size=int(get_chart_setting(chart_id, "extrema_marker_size", 10)),
                color=[max_col if k == "max" else min_col for k in kinds],
                symbol=[get_chart_setting(chart_id, "extrema_max_symbol", "triangle-up") if k == "max" else get_chart_setting(chart_id, "extrema_min_symbol", "triangle-down") for k in kinds],
                line=dict(color=get_chart_setting(chart_id, "extrema_marker_line_color", "white"), width=float(get_chart_setting(chart_id, "extrema_marker_line_width", 1.5))),
            ),
            text=texts,
            textposition=[get_chart_setting(chart_id, "extrema_max_textposition", "top center") if k == "max" else get_chart_setting(chart_id, "extrema_min_textposition", "bottom center") for k in kinds],
            cliponaxis=bool(get_chart_setting(chart_id, "extrema_cliponaxis", False)),
            textfont=dict(size=int(get_chart_setting(chart_id, "extrema_font_size", 9)), color=[max_col if k == "max" else min_col for k in kinds]),
            hovertemplate="%{text}<extra></extra>",
        )
    )
    return fig
