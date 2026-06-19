from __future__ import annotations

from ui.charts.axis_refs import trace_yaxis_layout_name


def numeric_values(values) -> list[float]:
    out: list[float] = []
    try:
        for v in values:
            if v is None:
                continue
            try:
                if isinstance(v, str):
                    continue
                fv = float(v)
                if fv == fv:
                    out.append(fv)
            except Exception:
                continue
    except Exception:
        pass
    return out


def range_with_padding(values: list[float], pad_ratio: float, *, keep_zero_edge: bool = False) -> list[float] | None:
    """Calcola un range aderente ai valori reali, con solo il padding richiesto."""
    if not values:
        return None

    raw_min = min(values)
    raw_max = max(values)
    vmin = raw_min
    vmax = raw_max

    if vmin >= 0:
        vmin = 0.0
    if vmax <= 0:
        vmax = 0.0

    span = max(vmax - vmin, abs(vmax), abs(vmin))
    if span <= 0:
        span = 1.0

    pad = span * pad_ratio
    if keep_zero_edge and raw_min >= 0:
        return [0.0, vmax + pad]
    if keep_zero_edge and raw_max <= 0:
        return [vmin - pad, 0.0]
    return [vmin - pad, vmax + pad]


def range_from_visible_values(values, pad_ratio: float) -> list[float] | None:
    """Calcola il range Y sui soli valori visibili nella finestra temporale."""
    vals = numeric_values(values)
    if not vals:
        return None
    vmin = min(vals)
    vmax = max(vals)

    if vmin == vmax:
        span = max(abs(vmin), 1.0)
        delta = span * max(pad_ratio, 0.02)
        return [vmin - delta, vmax + delta]

    span = vmax - vmin
    delta = span * max(pad_ratio, 0.0)
    return [vmin - delta, vmax + delta]


def trace_visible_y_values_for_x_range(trace, x_range) -> list[float]:
    """Estrae i valori Y della traccia compresi nel range X indicato."""
    try:
        import pandas as pd

        if x_range is None or len(x_range) != 2:
            return []
        start = pd.to_datetime(x_range[0])
        end = pd.to_datetime(x_range[1])

        raw_x = getattr(trace, "x", None)
        raw_y = getattr(trace, "y", None)
        if raw_x is None or raw_y is None:
            return []

        try:
            x_vals = list(raw_x)
            y_vals = list(raw_y)
        except Exception:
            return []

        if len(x_vals) == 0 or len(y_vals) == 0:
            return []

        out: list[float] = []
        for x, y in zip(x_vals, y_vals):
            try:
                dx = pd.to_datetime(x)
                if dx < start or dx > end:
                    continue
                if y is None or isinstance(y, str):
                    continue
                fy = float(y)
                if fy == fy:
                    out.append(fy)
            except Exception:
                continue
        return out
    except Exception:
        return []


def visible_y_ranges_for_x_range(fig, x_range, pad_ratio: float) -> dict[str, list[float]]:
    """Restituisce i range Y dinamici per ogni asse Y della figura."""
    grouped: dict[str, list[float]] = {}
    try:
        for trace in fig.data:
            vals = trace_visible_y_values_for_x_range(trace, x_range)
            if not vals:
                continue
            axis_name = trace_yaxis_layout_name(trace)
            grouped.setdefault(axis_name, []).extend(vals)
    except Exception:
        return {}

    ranges: dict[str, list[float]] = {}
    for axis_name, values in grouped.items():
        yr = range_from_visible_values(values, pad_ratio)
        if yr is not None:
            ranges[axis_name] = yr
    return ranges


def update_axis_range(fig, axis_name: str, range_values: list[float] | None, *, constrain_domain: bool = False) -> None:
    """Aggiorna il range di un asse layout Plotly in modo sicuro."""
    if range_values is None:
        return
    update = {"range": range_values, "automargin": True}
    if constrain_domain:
        update["constrain"] = "domain"
    try:
        fig.update_layout({axis_name: update})
    except Exception:
        pass
