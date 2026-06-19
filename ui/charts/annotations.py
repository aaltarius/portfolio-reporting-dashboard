from __future__ import annotations

from typing import Any, Callable


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
