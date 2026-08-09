from __future__ import annotations

from typing import Any, Callable, Sequence


def data_range_for_axis(fig, data_axis: str, *, numeric_values: Callable[[Any], list[float]]) -> list[float] | None:
    vals: list[float] = []
    for tr in fig.data:
        vals.extend(numeric_values(getattr(tr, data_axis, [])))
    if not vals:
        return None
    return [min(vals), max(vals)]


def range_from_min_max(
    fig,
    data_axis: str,
    min_value,
    max_value,
    *,
    numeric_values: Callable[[Any], list[float]],
) -> list[float] | None:
    data_range = data_range_for_axis(fig, data_axis, numeric_values=numeric_values)
    if data_range is None:
        data_range = [0.0, 1.0]
    lo, hi = data_range
    if min_value is not None:
        lo = min_value
    if max_value is not None:
        hi = max_value
    try:
        if float(lo) == float(hi):
            hi = float(hi) + 1.0
    except Exception:
        pass
    return [lo, hi]


def zero_aligned_ranges(
    value_lists: Sequence[Sequence[float]],
    *,
    padding: float = 0.12,
    max_negative_fraction: float = 0.85,
) -> list[list[float] | None]:
    """Calcola range Y espliciti che allineano la linea dello zero alla stessa
    altezza percentuale in più grafici a barre indipendenti (unità diverse).

    Ogni lista di valori genera un range [y_min, y_max] tale per cui lo zero
    cade sempre alla stessa frazione verticale in tutti i grafici — la
    frazione usata è quella richiesta dal grafico più "sbilanciato" in
    negativo. Se nessuna lista contiene valori negativi, restituisce ``None``
    per ciascuna voce: i grafici restano ad autorange (nessuna modifica al
    comportamento quando tutti i valori sono positivi).
    """
    data_ranges: list[tuple[float, float]] = []
    for values in value_lists:
        nums = [float(v) for v in values if v is not None]
        lo = min([0.0, *nums])
        hi = max([0.0, *nums])
        data_ranges.append((lo, hi))

    if all(lo >= 0.0 for lo, _ in data_ranges):
        return [None for _ in data_ranges]

    fractions = []
    for lo, hi in data_ranges:
        span = hi - lo
        fractions.append((-lo) / span if span > 0 else 0.0)
    target_fraction = min(max(fractions), max_negative_fraction)
    k = target_fraction / (1.0 - target_fraction)

    ranges: list[list[float] | None] = []
    for lo, hi in data_ranges:
        y_max = hi if k <= 0 else max(hi, (-lo) / k)
        if y_max <= 0:
            y_max = 1.0
        y_max *= (1.0 + padding)
        y_min = -k * y_max
        ranges.append([y_min, y_max])
    return ranges


def apply_axis_settings(
    fig,
    settings: dict[str, Any],
    global_style: dict[str, Any],
    *,
    coerce_axis_range: Callable[[Any], list[Any] | None],
    range_from_min_max_fn: Callable[..., list[float] | None],
) -> tuple[list[Any] | None, list[Any] | None, list[Any] | None]:
    x_range = coerce_axis_range(settings.get("x_range"))
    y_range = coerce_axis_range(settings.get("y_range"))
    y2_range = coerce_axis_range(settings.get("y2_range"))

    if x_range is None and (settings.get("x_min") is not None or settings.get("x_max") is not None):
        x_range = range_from_min_max_fn(fig, "x", settings.get("x_min"), settings.get("x_max"))
    if y_range is None and (settings.get("y_min") is not None or settings.get("y_max") is not None):
        y_range = range_from_min_max_fn(fig, "y", settings.get("y_min"), settings.get("y_max"))

    if x_range is not None:
        fig.update_xaxes(range=x_range)
    if y_range is not None:
        fig.update_yaxes(range=y_range)
    if y2_range is not None:
        fig.update_layout(yaxis2=dict(range=y2_range))

    if settings.get("x_dtick") is not None:
        fig.update_xaxes(dtick=settings.get("x_dtick"))
    if settings.get("y_dtick") is not None:
        fig.update_yaxes(dtick=settings.get("y_dtick"))
    if settings.get("x_minor_dtick") is not None:
        fig.update_xaxes(minor=dict(dtick=settings.get("x_minor_dtick"), ticks="outside"))
    if settings.get("y_minor_dtick") is not None:
        fig.update_yaxes(minor=dict(dtick=settings.get("y_minor_dtick"), ticks="outside"))
    if settings.get("x_nticks") is not None:
        fig.update_xaxes(nticks=int(settings.get("x_nticks")))
    elif settings.get("type") != "time":
        fig.update_xaxes(nticks=int(global_style.get("numeric_axis_nticks", 6)))
    if settings.get("y_nticks") is not None:
        fig.update_yaxes(nticks=int(settings.get("y_nticks")))
    elif settings.get("type") != "time":
        fig.update_yaxes(nticks=int(global_style.get("numeric_axis_nticks", 6)))

    if settings.get("x_title") is not None:
        fig.update_xaxes(title_text=settings.get("x_title"))
    if settings.get("y_title") is not None:
        fig.update_yaxes(title_text=settings.get("y_title"))
    if settings.get("x_tickformat") is not None:
        fig.update_xaxes(tickformat=settings.get("x_tickformat"))
    if settings.get("y_tickformat") is not None:
        fig.update_yaxes(tickformat=settings.get("y_tickformat"))
    if settings.get("x_ticksuffix") is not None:
        fig.update_xaxes(ticksuffix=settings.get("x_ticksuffix"))
    if settings.get("y_ticksuffix") is not None:
        fig.update_yaxes(ticksuffix=settings.get("y_ticksuffix"))

    y2_update: dict[str, Any] = {}
    if settings.get("y2_title") is not None:
        y2_update["title"] = dict(text=settings.get("y2_title"))
    if settings.get("y2_tickformat") is not None:
        y2_update["tickformat"] = settings.get("y2_tickformat")
    if settings.get("y2_ticksuffix") is not None:
        y2_update["ticksuffix"] = settings.get("y2_ticksuffix")
    if settings.get("y2_nticks") is not None:
        y2_update["nticks"] = int(settings.get("y2_nticks"))
    if settings.get("y2_overlaying") is not None:
        y2_update["overlaying"] = settings.get("y2_overlaying")
    if settings.get("y2_side") is not None:
        y2_update["side"] = settings.get("y2_side")
    if settings.get("y2_showgrid") is not None:
        y2_update["showgrid"] = bool(settings.get("y2_showgrid"))
    if y2_update:
        fig.update_layout(yaxis2=y2_update)

    return x_range, y_range, y2_range
