from __future__ import annotations

from typing import Any


def _resolve_chart_settings(charts: dict[str, dict[str, Any]], chart_id: str) -> dict[str, Any]:
    settings = dict(charts.get(chart_id, charts["_default_timeseries"]))
    typ = settings.setdefault("type", "custom")
    settings.setdefault("legend", "bottom")
    settings.setdefault("show_title", True)
    settings.setdefault("show_legend", settings.get("legend") != "off")
    settings.setdefault("show_buttons", typ == "time")
    settings.setdefault("default_button", "ALL")
    settings.setdefault("margin_delta", dict(t=0, b=0, l=0, r=0))
    return settings


def _get_chart_setting_value(
    charts: dict[str, dict[str, Any]],
    global_style: dict[str, Any],
    chart_id: str,
    key: str,
    default=None,
):
    """Risoluzione canonica di un parametro operativo del grafico."""
    try:
        settings = _resolve_chart_settings(charts, chart_id)
        if key in settings:
            return settings.get(key)
        if key == "show_extrema" and "show_extrema_default" in global_style:
            return global_style.get("show_extrema_default", default)
        if key in global_style:
            return global_style.get(key)
        fallback = charts.get("_default_timeseries", {})
        if key in fallback:
            return fallback.get(key)
    except Exception:
        pass
    return default


__all__ = ["_get_chart_setting_value", "_resolve_chart_settings"]
