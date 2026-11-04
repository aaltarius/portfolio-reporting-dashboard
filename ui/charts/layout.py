from __future__ import annotations

import math
from typing import Any

from ui.charts.streamlit_runtime import count_legend_items


def layout_has_xaxis_title(fig) -> bool:
    try:
        txt = getattr(getattr(fig.layout.xaxis, "title", None), "text", "")
        return bool(str(txt or "").strip())
    except Exception:
        return False


def coerce_axis_range(value):
    if value is None:
        return None
    try:
        if isinstance(value, (list, tuple)) and len(value) == 2:
            return [value[0], value[1]]
    except Exception:
        return None
    return None


def title_text(fig) -> str:
    try:
        return str(getattr(fig.layout.title, "text", "") or "")
    except Exception:
        return ""


def is_undefined(text: str) -> bool:
    t = str(text or "").strip().lower().replace("<b>", "").replace("</b>", "")
    return t in {"", "undefined", "none", "nan"}


def setting_title(settings: dict[str, Any]) -> str:
    return str(settings.get("title", "") or "")


def effective_title(settings: dict[str, Any], fig) -> str:
    dynamic_title = title_text(fig)
    if not is_undefined(dynamic_title):
        return dynamic_title
    return setting_title(settings)


def show_title(settings: dict[str, Any], fig, global_style: dict[str, Any]) -> bool:
    return (
        bool(global_style.get("show_titles", True))
        and bool(settings.get("show_title", True))
        and not is_undefined(effective_title(settings, fig))
    )


def show_legend(settings: dict[str, Any], global_style: dict[str, Any]) -> bool:
    return bool(global_style.get("show_legends", True)) and bool(settings.get("show_legend", True)) and settings.get("legend") != "off"


def show_buttons(settings: dict[str, Any], global_style: dict[str, Any]) -> bool:
    return bool(global_style.get("show_buttons", True)) and bool(settings.get("show_buttons", True)) and settings.get("type") == "time"


def _estimate_extra_legend_rows(fig, global_style: dict[str, Any]) -> int:
    """Righe di legenda oltre la prima, stimate dal numero reale di voci
    (una per strumento su grafici come "Contributo al P/L" o "Rendimento
    dello strumento", quindi non fisso). Condivisa da margine e posizione
    della legenda, per non stimare due volte con numeri diversi."""
    if fig is None:
        return 0
    try:
        n_items = count_legend_items(fig)
        items_per_row = max(1, int(global_style.get("legend_items_per_row_estimate", 9)))
        return max(0, math.ceil(n_items / items_per_row) - 1)
    except Exception:
        return 0


def legend_layout(
    where: str,
    global_style: dict[str, Any],
    fig=None,
    chart_height: int | None = None,
) -> dict[str, Any] | None:
    if where == "off":
        return None
    font = dict(size=int(global_style["legend_font_size"]), family=global_style["font_family"])
    if where == "top":
        return dict(orientation="h", yanchor="bottom", y=1.04, xanchor="center", x=0.5, font=font)
    if where == "right":
        return dict(orientation="v", yanchor="middle", y=0.5, xanchor="left", x=1.02, font=font)
    if where == "left":
        return dict(orientation="v", yanchor="middle", y=0.5, xanchor="right", x=-0.12, font=font)

    # Con una legenda dinamica su più righe, la legenda deve scendere insieme
    # al margine extra riservato (vedi _extra_bottom_legend_margin), altrimenti
    # resta ancorata alla posizione pensata per una riga sola e lascia uno
    # spazio vuoto tra sé e il bordo del margine, invece di usarlo.
    y = float(global_style["bottom_legend_y"])
    extra_rows = _estimate_extra_legend_rows(fig, global_style)
    if extra_rows > 0:
        height = int(chart_height or 400)
        row_height = int(global_style.get("legend_row_height_px", 20))
        y -= (extra_rows * row_height) / max(height, 1)

    return dict(
        orientation="h",
        yanchor="top",
        y=y,
        xanchor="center",
        x=0.5,
        font=font,
        tracegroupgap=int(global_style["bottom_legend_tracegroupgap"]),
        itemwidth=int(global_style.get("legend_itemwidth", 30)),
    )


def apply_margin_delta(base: dict[str, int], delta: dict[str, Any] | None) -> dict[str, int]:
    if not isinstance(delta, dict):
        return base
    return dict(
        t=int(base.get("t", 0)) + int(delta.get("t", 0)),
        b=int(base.get("b", 0)) + int(delta.get("b", 0)),
        l=int(base.get("l", 0)) + int(delta.get("l", 0)),
        r=int(base.get("r", 0)) + int(delta.get("r", 0)),
    )


def _extra_bottom_legend_margin(fig, global_style: dict[str, Any]) -> int:
    """Margine extra per una legenda orizzontale in basso con molte voci
    (vedi _estimate_extra_legend_rows)."""
    extra_rows = _estimate_extra_legend_rows(fig, global_style)
    return extra_rows * int(global_style.get("legend_row_height_px", 20))


def computed_margin(fig, settings: dict[str, Any], global_style: dict[str, Any]) -> dict[str, int]:
    typ = settings.get("type", "custom")
    title = show_title(settings, fig, global_style)
    buttons = show_buttons(settings, global_style)
    legend = show_legend(settings, global_style)
    legend_where = settings.get("legend", "bottom")
    has_x_title = layout_has_xaxis_title(fig)

    top = int(global_style["margin_top_base"])
    if title:
        top = max(top, int(global_style["margin_top_with_title"]))
    if buttons:
        top = max(top, int(global_style["margin_top_with_buttons"]))

    bottom = int(global_style["margin_bottom_base"])
    if has_x_title:
        bottom = max(bottom, int(global_style["margin_bottom_with_x_title"]))
    if legend and legend_where == "bottom":
        bottom = max(bottom, int(global_style["margin_bottom_with_bottom_legend"]))
        bottom += _extra_bottom_legend_margin(fig, global_style)

    left = int(settings.get("left", global_style["margin_left_base"]))
    right_default = global_style["temporal_right_margin"] if typ == "time" else global_style["margin_right_base"]
    right = int(settings.get("right", right_default))

    if typ == "time":
        right = max(right, int(global_style["temporal_right_margin"]))
    if typ in {"bar", "waterfall"}:
        left = max(left, int(global_style.get("horizontal_bar_left_margin_min", 56)))
        right = max(right, int(global_style.get("horizontal_bar_right_margin_min", 64)))
    if legend and legend_where == "right":
        right = max(right, 150)

    margin = dict(t=top, b=bottom, l=left, r=right)
    margin = apply_margin_delta(margin, global_style.get(f"{typ}_margin_delta"))
    margin = apply_margin_delta(margin, settings.get("margin_delta"))

    override = settings.get("margin_override", settings.get("margin"))
    if isinstance(override, dict):
        margin = dict(
            t=int(override.get("t", margin["t"])),
            b=int(override.get("b", margin["b"])),
            l=int(override.get("l", margin["l"])),
            r=int(override.get("r", margin["r"])),
        )

    return {k: max(0, int(v)) for k, v in margin.items()}
