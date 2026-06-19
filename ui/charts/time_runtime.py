from __future__ import annotations

from typing import Any, Callable


def current_x_range_for_axis(fig, axis_name: str = "xaxis"):
    """Legge il range X corrente di un asse Plotly, se disponibile."""
    try:
        axis = getattr(fig.layout, axis_name)
        rng = getattr(axis, "range", None)
        if rng is not None and len(rng) == 2:
            return [rng[0], rng[1]]
    except Exception:
        pass
    return None


def apply_initial_visible_y_range(
    fig,
    settings: dict[str, Any],
    *,
    time_extent: Callable,
    time_edge_padding: Callable,
    button_range: Callable,
    plotly_range: Callable,
    visible_y_ranges_for_x_range: Callable,
) -> None:
    if settings.get("type") != "time":
        return
    if not bool(settings.get("dynamic_y_to_initial_range", False)):
        return
    if settings.get("y_range") is not None or settings.get("y_min") is not None or settings.get("y_max") is not None:
        return

    rng = current_x_range_for_axis(fig, "xaxis")
    if rng is None:
        min_date, max_date = time_extent(fig)
        left_pad, right_pad = time_edge_padding(fig, settings)
        default_key = str(settings.get("default_button") or "ALL")
        rng = plotly_range(button_range(min_date, max_date, default_key, left_pad, right_pad))
    if rng is None:
        return

    for y_axis_name, yr in visible_y_ranges_for_x_range(fig, rng, settings).items():
        if y_axis_name == "yaxis2" and settings.get("y2_range") is not None:
            continue
        try:
            fig.update_layout({y_axis_name: dict(autorange=False, range=yr)})
        except Exception:
            pass


def force_time_default_range(
    fig,
    settings: dict[str, Any],
    global_style: dict[str, Any],
    *,
    show_buttons: Callable[[dict[str, Any]], bool],
    time_extent: Callable,
    time_edge_padding: Callable,
    as_timedelta: Callable,
    button_range: Callable,
    plotly_range: Callable,
    iter_xaxis_names: Callable,
    range_buttons: dict[str, Any],
    range_button_order: list[str],
) -> None:
    if settings.get("type") != "time":
        return
    if not show_buttons(settings):
        return
    if not bool(settings.get("time_force_default_range_after_render", global_style.get("time_force_default_range_after_render", True))):
        return
    min_date, max_date = time_extent(fig)
    if min_date is None or max_date is None:
        return
    left_pad, right_pad = time_edge_padding(fig, settings)
    left_pad = as_timedelta(left_pad)
    right_pad = as_timedelta(right_pad)
    default_key = str(settings.get("default_button") or "ALL")
    if default_key not in range_buttons:
        default_key = "ALL"
    rng = plotly_range(button_range(min_date, max_date, default_key, left_pad, right_pad))
    if rng is None:
        return
    axis_names = iter_xaxis_names(fig)
    for axis_name in axis_names:
        try:
            fig.update_layout({axis_name: dict(autorange=False, range=rng, rangeslider=dict(visible=False))})
        except Exception:
            pass
    try:
        active_idx = range_button_order.index(default_key)
        menus = list(getattr(fig.layout, "updatemenus", []) or [])
        if menus:
            menus[0].active = active_idx
            fig.update_layout(updatemenus=menus)
    except Exception:
        pass
