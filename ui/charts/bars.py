from __future__ import annotations

from typing import Any, Callable


def has_temporal_bar_trace(fig) -> bool:
    """Rileva barre con asse X temporale."""
    try:
        import pandas as pd

        for trace in fig.data:
            if getattr(trace, "type", None) != "bar":
                continue
            x = getattr(trace, "x", None)
            if x is None or len(x) == 0:
                continue
            for value in list(x)[:5]:
                try:
                    pd.to_datetime(value)
                    return True
                except Exception:
                    continue
    except Exception:
        pass
    return False


def time_edge_padding(fig, settings: dict[str, Any], global_style: dict[str, Any]):
    """Padding sx/dx del range temporale per non tagliare barre ai bordi."""
    try:
        import pandas as pd

        days = float(
            settings.get(
                "time_bar_edge_padding_days",
                global_style.get("time_bar_edge_padding_days", 0),
            )
        )
        if days <= 0 or not has_temporal_bar_trace(fig):
            return pd.Timedelta(days=0), pd.Timedelta(days=0)
        pad = pd.Timedelta(days=days)
        return pad, pad
    except Exception:
        return 0, 0


def apply_bar_protection(
    fig,
    settings: dict[str, Any],
    global_style: dict[str, Any],
    *,
    numeric_values: Callable[[Any], list[float]],
    trace_xaxis_layout_name: Callable[[Any], str],
    range_with_padding: Callable[..., list[float] | None],
    update_axis_range: Callable[..., None],
) -> None:
    """Protegge barre e waterfall da testi/estremi tagliati ai bordi."""
    typ = settings.get("type", "custom")
    if typ not in {"bar", "waterfall"}:
        return

    pad_ratio = float(settings.get("bar_padding", global_style["bar_padding"]))
    if typ == "waterfall":
        pad_ratio = float(
            settings.get("waterfall_padding", global_style["waterfall_padding"])
        )

    y_values: list[float] = []
    horizontal_by_xaxis: dict[str, list[float]] = {}
    has_horizontal = False
    has_vertical = False

    for tr in fig.data:
        tr_type = getattr(tr, "type", None)
        if tr_type not in {"bar", "waterfall"}:
            continue
        try:
            tr.update(cliponaxis=bool(global_style["bar_cliponaxis"]))
        except Exception:
            pass

        if tr_type == "waterfall":
            vals = numeric_values(getattr(tr, "y", []))
            measures = list(getattr(tr, "measure", []) or [])
            acc = 0.0
            cumulative: list[float] = []
            for i, v in enumerate(vals):
                m = measures[i] if i < len(measures) else "relative"
                if m in {"absolute", "total"}:
                    acc = v
                else:
                    acc += v
                cumulative.append(acc)
            y_values.extend(vals)
            y_values.extend(cumulative)
            has_vertical = True
            continue

        if getattr(tr, "orientation", None) == "h":
            axis_name = trace_xaxis_layout_name(tr)
            horizontal_by_xaxis.setdefault(axis_name, []).extend(
                numeric_values(getattr(tr, "x", []))
            )
            has_horizontal = True
        else:
            y_values.extend(numeric_values(getattr(tr, "y", [])))
            has_vertical = True

    if has_horizontal:
        auto_horizontal = bool(
            settings.get(
                "horizontal_bar_auto_range",
                global_style.get("horizontal_bar_auto_range", True),
            )
        )
        force_zero = bool(
            settings.get(
                "horizontal_bar_force_zero_start",
                global_style.get("horizontal_bar_force_zero_start", True),
            )
        )
        for axis_name, vals in horizontal_by_xaxis.items():
            if not vals:
                continue
            if auto_horizontal:
                if min(vals) >= 0 or max(vals) <= 0:
                    h_pad = float(
                        settings.get(
                            "horizontal_bar_padding_positive",
                            global_style.get("horizontal_bar_padding_positive", 0.12),
                        )
                    )
                else:
                    h_pad = float(
                        settings.get(
                            "horizontal_bar_padding_mixed",
                            global_style.get("horizontal_bar_padding_mixed", 0.18),
                        )
                    )
                xr = range_with_padding(vals, h_pad, keep_zero_edge=True)
            else:
                xr = range_with_padding(vals, pad_ratio, keep_zero_edge=True)

            if xr is not None and force_zero:
                if min(vals) >= 0:
                    xr[0] = 0.0
                elif max(vals) <= 0:
                    xr[1] = 0.0
            update_axis_range(fig, axis_name, xr, constrain_domain=True)

        try:
            fig.update_yaxes(
                automargin=True,
                ticks="",
                ticklen=int(
                    settings.get(
                        "horizontal_bar_ticklen",
                        global_style.get("horizontal_bar_ticklen", 0),
                    )
                ),
                ticklabelstandoff=int(
                    settings.get(
                        "horizontal_bar_ticklabelstandoff",
                        global_style.get("horizontal_bar_ticklabelstandoff", 0),
                    )
                ),
            )
        except Exception:
            fig.update_yaxes(automargin=True, ticks="")

    yr = range_with_padding(y_values, pad_ratio, keep_zero_edge=True)
    if yr is not None and has_vertical:
        fig.update_yaxes(range=yr, automargin=True)
    fig.update_xaxes(automargin=True)
    fig.update_yaxes(automargin=True)
