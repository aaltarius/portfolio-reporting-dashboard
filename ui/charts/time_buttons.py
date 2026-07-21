from __future__ import annotations

from datetime import timedelta
from typing import Any, Callable


def iter_xaxis_names(fig) -> list[str]:
    names = []
    try:
        for key in fig.layout:
            if str(key).startswith("xaxis"):
                names.append(str(key))
    except Exception:
        pass
    return sorted(set(names), key=lambda s: (len(s), s)) or ["xaxis"]


def clear_all_range_controls(fig) -> None:
    for axis_name in iter_xaxis_names(fig):
        try:
            fig.update_layout({axis_name: dict(rangeselector=dict(visible=False), rangeslider=dict(visible=False))})
        except Exception:
            pass


def time_extent(fig):
    """Estremi temporali (min, max) su tutte le tracce della figura.

    Conversione a datetime vettorizzata per traccia (era uno dei punti
    profilati come costosi in apply_buttons: pd.to_datetime chiamato punto
    per punto in loop Python). errors="coerce" + dropna riproduce esattamente
    il filtro originale "if d == d" (che escludeva i NaT, cioè i valori non
    parsabili o None/NaN).
    """
    try:
        import pandas as pd

        dates = []
        for trace in fig.data:
            x = getattr(trace, "x", None)
            if x is None:
                continue
            try:
                x_list = list(x)
                if not x_list:
                    continue
                parsed = pd.to_datetime(pd.Index(x_list), errors="coerce").dropna()
                dates.extend(parsed.tolist())
            except Exception:
                continue
        if not dates:
            return None, None
        return min(dates), max(dates)
    except Exception:
        return None, None


def start_from_default(max_date, key: str, *, use_calendar: bool):
    try:
        import pandas as pd

        if key == "1M":
            return max_date - (pd.DateOffset(months=1) if use_calendar else timedelta(days=30))
        if key == "3M":
            return max_date - (pd.DateOffset(months=3) if use_calendar else timedelta(days=90))
        if key == "6M":
            return max_date - (pd.DateOffset(months=6) if use_calendar else timedelta(days=180))
        if key == "1Y":
            return max_date - (pd.DateOffset(years=1) if use_calendar else timedelta(days=365))
        if key == "YTD":
            return pd.Timestamp(year=max_date.year, month=1, day=1)
    except Exception:
        return None
    return None


def as_timedelta(value):
    try:
        import pandas as pd

        if value is None:
            return pd.Timedelta(days=0)
        if isinstance(value, pd.Timedelta):
            return value
        return pd.Timedelta(days=float(value))
    except Exception:
        try:
            import pandas as pd

            return pd.Timedelta(days=0)
        except Exception:
            return 0


def button_range(min_date, max_date, key: str, left_pad=None, right_pad=None, *, use_calendar: bool):
    if min_date is None or max_date is None:
        return None
    try:
        import pandas as pd

        min_date = pd.to_datetime(min_date)
        max_date = pd.to_datetime(max_date)
    except Exception:
        return None
    left_pad = as_timedelta(left_pad)
    right_pad = as_timedelta(right_pad)
    min_visible = min_date - left_pad
    max_visible = max_date + right_pad
    if key == "ALL":
        return [min_visible, max_visible]
    start = start_from_default(max_date, key, use_calendar=use_calendar)
    if start is None:
        return [min_visible, max_visible]
    if start < min_date:
        start = min_date
    return [start, max_visible]


def plotly_date(value):
    try:
        import pandas as pd

        v = pd.to_datetime(value)
        if getattr(v, "hour", 0) == 0 and getattr(v, "minute", 0) == 0 and getattr(v, "second", 0) == 0:
            return v.strftime("%Y-%m-%d")
        return v.isoformat()
    except Exception:
        return value


def plotly_range(rng):
    if rng is None:
        return None
    try:
        return [plotly_date(rng[0]), plotly_date(rng[1])]
    except Exception:
        return rng


def apply_buttons(
    fig,
    settings: dict[str, Any],
    global_style: dict[str, Any],
    *,
    show_buttons: Callable[[dict[str, Any]], bool],
    time_edge_padding: Callable,
    visible_y_ranges_for_x_range: Callable,
    range_buttons: dict[str, dict[str, Any]],
    range_button_order: list[str],
    button_range_fn: Callable,
    plotly_range_fn: Callable,
    plotly_date_fn: Callable,
) -> None:
    clear_all_range_controls(fig)

    if bool(settings.get("time_reset_uirevision", global_style.get("time_reset_uirevision_on_render", True))):
        try:
            fig.update_layout(uirevision=None)
        except Exception:
            pass

    if not show_buttons(settings):
        try:
            fig.update_layout(updatemenus=[])
        except Exception:
            pass
        return

    min_date, max_date = time_extent(fig)
    left_pad, right_pad = time_edge_padding(fig, settings)
    left_pad = as_timedelta(left_pad)
    right_pad = as_timedelta(right_pad)
    min_visible = min_date - left_pad if min_date is not None else None
    max_visible = max_date + right_pad if max_date is not None else None
    default_key = str(settings.get("default_button") or "ALL")
    if default_key not in range_buttons:
        default_key = "ALL"
    axis_names = iter_xaxis_names(fig)

    initial_range = plotly_range_fn(button_range_fn(min_date, max_date, default_key, left_pad, right_pad))
    for axis_name in axis_names:
        axis_update = dict(rangeslider=dict(visible=False), type="date", autorange=False)
        if initial_range is not None:
            axis_update["range"] = initial_range
        if max_visible is not None and bool(global_style.get("time_set_maxallowed", True)):
            axis_update["maxallowed"] = plotly_date_fn(max_visible)
        if min_visible is not None and bool(global_style.get("time_set_minallowed", True)):
            axis_update["minallowed"] = plotly_date_fn(min_visible)
        try:
            fig.update_layout({axis_name: axis_update})
        except Exception:
            pass

    engine = str(global_style.get("time_button_engine", "relayout")).lower()
    if engine == "rangeselector":
        buttons = []
        for k in range_button_order:
            b = dict(range_buttons[k])
            if bool(global_style.get("button_label_brackets", False)):
                b["label"] = f"[{b.get('label', k)}]"
            buttons.append(b)
        fig.update_layout(
            xaxis=dict(
                rangeselector=dict(
                    visible=True,
                    buttons=buttons,
                    bgcolor=global_style["button_bg"],
                    activecolor=global_style["button_active"],
                    borderwidth=int(global_style["button_border_width"]),
                    bordercolor=global_style["button_border_color"],
                    font=dict(size=int(global_style["button_font_size"])),
                    x=float(global_style["button_x"]),
                    xanchor="left",
                    y=float(global_style["button_y"]),
                    yanchor="top",
                ),
                rangeslider=dict(visible=False),
                type="date",
            )
        )
        return

    buttons = []
    for key in range_button_order:
        rng = plotly_range_fn(button_range_fn(min_date, max_date, key, left_pad, right_pad))
        updates = {}
        if rng is not None:
            for axis_name in axis_names:
                updates[f"{axis_name}.autorange"] = False
                updates[f"{axis_name}.range[0]"] = rng[0]
                updates[f"{axis_name}.range[1]"] = rng[1]
                updates[f"{axis_name}.rangeslider.visible"] = False
            if bool(settings.get("dynamic_y_by_button", False)):
                for y_axis_name, yr in visible_y_ranges_for_x_range(fig, rng, settings).items():
                    updates[f"{y_axis_name}.autorange"] = False
                    updates[f"{y_axis_name}.range[0]"] = yr[0]
                    updates[f"{y_axis_name}.range[1]"] = yr[1]
        raw_label = range_buttons[key].get("label", key)
        label = f"[{raw_label}]" if bool(global_style.get("button_label_brackets", False)) else raw_label
        buttons.append(dict(label=label, method="relayout", args=[updates]))

    try:
        active_idx = range_button_order.index(default_key)
    except ValueError:
        active_idx = len(range_button_order) - 1

    fig.update_layout(
        updatemenus=[dict(
            type="buttons",
            direction="right",
            showactive=bool(global_style.get("button_showactive", False)),
            active=active_idx,
            buttons=buttons,
            x=float(global_style["button_x"]),
            xanchor="left",
            y=float(global_style["button_y"]),
            yanchor="top",
            bgcolor=global_style["button_bg"],
            borderwidth=int(global_style["button_border_width"]),
            bordercolor=global_style["button_border_color"],
            font=dict(size=int(global_style["button_font_size"])),
            pad=dict(
                t=int(global_style.get("button_pad_t", 0)),
                b=int(global_style.get("button_pad_b", 0)),
                l=int(global_style.get("button_pad_l", 0)),
                r=int(global_style.get("button_pad_r", 0)),
            ),
        )]
    )
