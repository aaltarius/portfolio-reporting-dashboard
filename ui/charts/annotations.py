from __future__ import annotations

from datetime import date as _date
from typing import Any, Callable

import pandas as _pd


def is_baseline_annotation(text: str) -> bool:
    """Riconosce le annotazioni tecniche tipo Base 100, da non trattare come titoli."""
    t = str(text or "").lower().replace("<b>", "").replace("</b>", "")
    return "base 100" in t


def plotly_obj_to_dict(obj) -> dict[str, Any]:
    """Converte oggetti Plotly in dizionari modificabili."""
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return dict(obj)
    try:
        return dict(obj.to_plotly_json())
    except Exception:
        try:
            return dict(obj)
        except Exception:
            return {}


def normalise_baseline_lines(fig, settings: dict[str, Any], global_style: dict[str, Any]) -> None:
    shapes = list(getattr(fig.layout, "shapes", []) or [])
    if not shapes:
        return

    color = settings.get("baseline_line_color", global_style.get("baseline_line_color"))
    dash = settings.get("baseline_line_dash", global_style.get("baseline_line_dash"))
    width = settings.get("baseline_line_width", global_style.get("baseline_line_width"))
    opacity = settings.get("baseline_line_opacity", global_style.get("baseline_line_opacity"))

    changed = False
    for shp in shapes:
        try:
            if getattr(shp, "type", None) != "line":
                continue
            y0 = float(getattr(shp, "y0", None))
            y1 = float(getattr(shp, "y1", None))
            if abs(y0 - 100.0) > 1e-9 or abs(y1 - 100.0) > 1e-9:
                continue
            line = plotly_obj_to_dict(getattr(shp, "line", None))
            if color is not None:
                line["color"] = str(color)
            if dash is not None:
                line["dash"] = str(dash)
            if width is not None:
                line["width"] = float(width)
            shp.line = line
            if opacity is not None:
                shp.opacity = float(opacity)
            changed = True
        except Exception:
            continue

    if changed:
        try:
            fig.update_layout(shapes=shapes)
        except Exception:
            pass


def normalise_baseline_axis_titles(fig, settings: dict[str, Any], global_style: dict[str, Any]) -> None:
    color = settings.get(
        "baseline_axis_title_color",
        global_style.get("baseline_axis_title_color", global_style.get("baseline_annotation_color")),
    )
    if not color:
        return

    axis_updates: dict[str, Any] = {}
    try:
        for key in fig.layout:
            axis_name = str(key)
            if not (axis_name.startswith("xaxis") or axis_name.startswith("yaxis")):
                continue

            axis = getattr(fig.layout, axis_name, None)
            title = getattr(axis, "title", None) if axis is not None else None
            text = str(getattr(title, "text", "") or "")
            if not is_baseline_annotation(text):
                continue

            title_dict = plotly_obj_to_dict(title)
            font = plotly_obj_to_dict(title_dict.get("font", getattr(title, "font", None)))
            font["color"] = str(color)
            title_dict["text"] = text
            title_dict["font"] = font
            axis_updates[axis_name] = dict(title=title_dict)

        if axis_updates:
            fig.update_layout(**axis_updates)
    except Exception:
        pass


def normalise_annotations(
    fig,
    settings: dict[str, Any],
    global_style: dict[str, Any],
    *,
    show_title: bool,
    is_undefined: Callable[[str], bool],
) -> None:
    anns = list(getattr(fig.layout, "annotations", []) or [])
    if not anns:
        return

    new_anns: list[dict[str, Any]] = []

    base_font_color = str(settings.get(
        "baseline_annotation_color",
        global_style.get("baseline_annotation_color", "rgba(220,38,38,0.95)"),
    ))
    base_font_size = int(settings.get(
        "baseline_annotation_font_size",
        global_style.get("baseline_annotation_font_size", 10),
    ))
    base_yshift = settings.get("baseline_annotation_yshift", global_style.get("baseline_annotation_yshift", 0))

    for ann in anns:
        ann_dict = plotly_obj_to_dict(ann)
        txt = str(ann_dict.get("text", getattr(ann, "text", "")) or "")
        if is_undefined(txt):
            continue

        try:
            if is_baseline_annotation(txt):
                font = plotly_obj_to_dict(ann_dict.get("font", getattr(ann, "font", None)))
                font.update({
                    "size": base_font_size,
                    "family": global_style["font_family"],
                    "color": base_font_color,
                })
                ann_dict["font"] = font
                if base_yshift is not None:
                    ann_dict["yshift"] = int(base_yshift)
                new_anns.append(ann_dict)
                continue

            if not show_title and ann_dict.get("y", 0) and float(ann_dict.get("y", 0)) > 0.92:
                continue

            ann_dict["font"] = dict(
                size=int(settings.get("subplot_title_font_size", global_style.get("subplot_title_font_size", global_style["title_font_size"]))),
                family=global_style["font_family"],
                color=str(settings.get("subplot_title_color", global_style.get("title_color", "#111827"))),
            )
        except Exception:
            pass

        new_anns.append(ann_dict)

    try:
        fig.update_layout(annotations=new_anns)
    except Exception:
        pass


# ── Linee verticali di trimestre / anno ──────────────────────────────────────

def _display_range(fig) -> tuple[_pd.Timestamp | None, _pd.Timestamp | None]:
    """Legge SOLO il range X già impostato sul layout (dopo force_time_default_range).
    Nessun fallback alle tracce: se il range non è esplicitamente impostato
    sul layout, restituisce (None, None) e le linee non vengono aggiunte."""
    try:
        rng = getattr(fig.layout.xaxis, "range", None)
        if rng and len(rng) == 2:
            t0 = _pd.Timestamp(rng[0])
            t1 = _pd.Timestamp(rng[1])
            if not _pd.isna(t0) and not _pd.isna(t1):
                return (t0, t1) if t0 <= t1 else (t1, t0)
    except Exception:
        pass
    return None, None


def _all_quarter_starts(from_year: int, to_year: int) -> list[tuple[int, int, _date]]:
    """Tutti i confini di trimestre da from_year a to_year incluso (+ 1 extra per midpoint)."""
    result: list[tuple[int, int, _date]] = []
    for year in range(from_year, to_year + 2):
        for q, month in enumerate([1, 4, 7, 10], start=1):
            result.append((year, q, _date(year, month, 1)))
    return result


def add_quarter_gridlines(fig, settings: dict[str, Any], global_style: dict[str, Any]) -> None:
    """Aggiunge linee verticali di trimestre/anno ai grafici temporali.

    Range visibile: legge fig.layout.xaxis.range (impostato da force_time_default_range).
    Se non è impostato, non aggiunge nulla (niente fallback alle tracce).

    Logica densità sul range visibile:
      < 90 gg   → niente
      90–730 gg → modalità trimestrale:
                   - linee verticali a ogni confine Q (Jan/Apr/Jul/Oct)
                   - anno (bold) sulla linea di Q1, y=0.96
                   - etichetta Tq centrata nell'intervallo tra due linee, y=0.88
      > 730 gg  → modalità annuale:
                   - linea verticale solo a Jan 1
                   - anno (bold) sulla linea, y=0.96
    """
    if settings.get("type") != "time":
        return
    if not global_style.get("quarter_gridlines", True):
        return

    min_dt, max_dt = _display_range(fig)
    if min_dt is None or max_dt is None:
        return

    span_days = (max_dt - min_dt).days
    if span_days < 90:
        return

    quarterly_mode = span_days <= 730

    # Genera tutti i confini nel range (+ 1 extra dopo max_dt per calcolare midpoint dell'ultimo Tq)
    all_bounds = _all_quarter_starts(min_dt.year, max_dt.year)
    max_d = max_dt.date()
    min_d = min_dt.date()

    font_family = global_style.get("font_family", "Inter, Arial, sans-serif")
    line_color = "rgba(120,120,120,0.60)"
    year_color = "rgba(80,80,80,0.85)"
    q_color = "rgba(100,100,100,0.70)"

    new_shapes: list[dict[str, Any]] = []
    new_anns: list[dict[str, Any]] = []

    for i, (year, q, d) in enumerate(all_bounds):
        if d > max_d:
            break  # oltre il range visibile

        if quarterly_mode:
            # Linea su ogni confine di trimestre che cade nel range
            if d >= min_d:
                new_shapes.append(dict(
                    type="line", x0=d.isoformat(), x1=d.isoformat(),
                    y0=0, y1=1, yref="paper", xref="x",
                    line=dict(color=line_color, width=2, dash="dot"),
                    layer="below",
                ))
                # Anno solo su Q1, in alto sulla linea
                if q == 1:
                    new_anns.append(dict(
                        x=d.isoformat(), y=0.99,
                        yref="paper", xref="x",
                        text=f"<b>{year}</b>",
                        showarrow=False,
                        font=dict(size=11, color=year_color, family=font_family),
                        yanchor="top", xanchor="left", xshift=4,
                    ))

            # Etichetta Tq centrata tra questa linea e la prossima
            # (anche se d < min_d, il midpoint potrebbe essere nel range visibile)
            if i + 1 < len(all_bounds):
                next_d = all_bounds[i + 1][2]
                mid_ts = _pd.Timestamp(d) + (_pd.Timestamp(next_d) - _pd.Timestamp(d)) / 2
                mid_d = mid_ts.date()
                if min_d <= mid_d <= max_d:
                    new_anns.append(dict(
                        x=mid_ts.isoformat(), y=0.99,
                        yref="paper", xref="x",
                        text=f"T{q}",
                        showarrow=False,
                        font=dict(size=11, color=q_color, family=font_family),
                        yanchor="top", xanchor="center",
                    ))

        else:
            # Modalità annuale: solo confini Q1 (1 gennaio)
            if q == 1 and d >= min_d:
                new_shapes.append(dict(
                    type="line", x0=d.isoformat(), x1=d.isoformat(),
                    y0=0, y1=1, yref="paper", xref="x",
                    line=dict(color=line_color, width=2, dash="dot"),
                    layer="below",
                ))
                new_anns.append(dict(
                    x=d.isoformat(), y=0.99,
                    yref="paper", xref="x",
                    text=f"<b>{year}</b>",
                    showarrow=False,
                    font=dict(size=11, color=year_color, family=font_family),
                    yanchor="top", xanchor="left", xshift=4,
                ))

    if new_shapes:
        existing = list(getattr(fig.layout, "shapes", []) or [])
        fig.update_layout(shapes=existing + new_shapes)
    if new_anns:
        existing = list(getattr(fig.layout, "annotations", []) or [])
        fig.update_layout(annotations=existing + new_anns)
