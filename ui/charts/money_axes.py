from __future__ import annotations

from typing import Any, Callable


def axis_title(fig, axis_name: str) -> str:
    try:
        axis = getattr(fig.layout, axis_name)
        return str(getattr(getattr(axis, "title", None), "text", "") or "")
    except Exception:
        return ""


def looks_money(text: str) -> bool:
    t = str(text or "").lower()
    return any(
        s in t
        for s in ["€", "eur", "p/l", "valore", "costo", "capitale", "controvalore", "patrimonio", "spesa", "cumulato"]
    )


def axis_has_large_values(
    fig,
    data_axis: str,
    *,
    threshold: float,
    numeric_values: Callable[[Any], list[float]],
) -> bool:
    vals: list[float] = []
    for tr in fig.data:
        vals.extend(numeric_values(getattr(tr, data_axis, [])))
    return bool(vals) and max(abs(v) for v in vals) >= threshold


def compact_money_axes(
    fig,
    settings: dict[str, Any],
    global_style: dict[str, Any],
    *,
    numeric_values: Callable[[Any], list[float]],
) -> None:
    if not global_style.get("compact_money_ticks", True):
        return
    fmt = str(settings.get("money_format", global_style["compact_money_format"]))
    money_axis = str(settings.get("money_axis", "auto")).lower()
    if money_axis == "off":
        return
    force = bool(settings.get("force_k", global_style.get("force_k_for_money_axes", False)))
    threshold = float(global_style["compact_money_threshold"])
    try:
        apply_x = money_axis in {"x", "both"} or (money_axis == "auto" and looks_money(axis_title(fig, "xaxis")))
        apply_y = money_axis in {"y", "both"} or (money_axis == "auto" and looks_money(axis_title(fig, "yaxis")))
        apply_y2 = money_axis in {"y2", "both"}
        if apply_x and (force or axis_has_large_values(fig, "x", threshold=threshold, numeric_values=numeric_values)):
            fig.update_xaxes(tickformat=fmt)
        if apply_y and (force or axis_has_large_values(fig, "y", threshold=threshold, numeric_values=numeric_values)):
            fig.update_yaxes(tickformat=fmt)
        if apply_y2:
            fig.update_layout(yaxis2=dict(tickformat=fmt))
    except Exception:
        pass
