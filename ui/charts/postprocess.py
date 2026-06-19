from __future__ import annotations

from typing import Any


def apply_horizontal_bar_axis_spacing(
    fig,
    settings: dict[str, Any],
    global_style: dict[str, Any],
    *,
    has_horizontal_bar: bool,
) -> None:
    """Riduce la distanza etichette asse Y ↔ barre nei grafici orizzontali."""
    if not has_horizontal_bar:
        return
    try:
        fig.update_yaxes(
            ticks="",
            ticklen=int(
                settings.get(
                    "y_ticklen",
                    global_style.get("horizontal_bar_ticklen", 0),
                )
            ),
            ticklabelstandoff=int(
                settings.get(
                    "y_ticklabelstandoff",
                    global_style.get("horizontal_bar_ticklabelstandoff", 0),
                )
            ),
        )
    except Exception:
        pass


def reapply_forced_ranges(
    fig,
    *,
    x_range,
    y_range,
    y2_range,
) -> None:
    """Riapplica i range espliciti dopo i passaggi che possono allargarli."""
    if x_range is not None:
        fig.update_xaxes(range=x_range)
    if y_range is not None:
        fig.update_yaxes(range=y_range)
    if y2_range is not None:
        fig.update_layout(yaxis2=dict(range=y2_range))


def reapply_y2_after_money(fig, settings: dict[str, Any]) -> None:
    """Riapplica i setting di y2 dopo la normalizzazione monetaria degli assi."""
    y2_after_money: dict[str, Any] = {}
    if settings.get("y2_title") is not None:
        y2_after_money["title"] = dict(text=settings.get("y2_title"))
    if settings.get("y2_tickformat") is not None:
        y2_after_money["tickformat"] = settings.get("y2_tickformat")
    if settings.get("y2_ticksuffix") is not None:
        y2_after_money["ticksuffix"] = settings.get("y2_ticksuffix")
    if settings.get("y2_range") is not None:
        y2_after_money["range"] = settings.get("y2_range")
    if settings.get("y2_overlaying") is not None:
        y2_after_money["overlaying"] = settings.get("y2_overlaying")
    if settings.get("y2_side") is not None:
        y2_after_money["side"] = settings.get("y2_side")
    if settings.get("y2_showgrid") is not None:
        y2_after_money["showgrid"] = bool(settings.get("y2_showgrid"))
    if settings.get("y2_nticks") is not None:
        y2_after_money["nticks"] = int(settings.get("y2_nticks"))
    if y2_after_money:
        fig.update_layout(yaxis2=y2_after_money)
