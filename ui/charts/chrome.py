from __future__ import annotations

from typing import Any


def _apply_chart_chrome(
    fig,
    settings: dict[str, Any],
    global_style: dict[str, Any],
    *,
    margin: dict[str, int],
    show_title: bool,
    show_legend: bool,
    effective_title: str,
    legend_layout: dict[str, Any] | None,
) -> None:
    """Applica la cornice visiva comune: layout base, title/legend, assi e radar."""
    layout: dict[str, Any] = dict(
        margin=margin,
        font=dict(
            family=global_style["font_family"],
            size=int(global_style["font_size"]),
        ),
        hovermode=getattr(fig.layout, "hovermode", None)
        or ("x unified" if settings["type"] == "time" else "closest"),
    )

    if settings.get("height") is not None:
        layout["height"] = int(settings["height"])
    if settings.get("bargap") is not None:
        layout["bargap"] = float(settings["bargap"])
    if settings.get("bargroupgap") is not None:
        layout["bargroupgap"] = float(settings["bargroupgap"])

    if global_style.get("transparent_background", True):
        layout["paper_bgcolor"] = "rgba(0,0,0,0)"
        layout["plot_bgcolor"] = "rgba(0,0,0,0)"
    else:
        layout["paper_bgcolor"] = settings.get(
            "paper_bgcolor",
            global_style.get("paper_bgcolor", "rgba(0,0,0,0)"),
        )
        layout["plot_bgcolor"] = settings.get(
            "plot_bgcolor",
            global_style.get("plot_bgcolor", "rgba(0,0,0,0)"),
        )

    if show_title:
        layout.update(
            title_text=effective_title,
            title_font=dict(
                size=int(settings.get("title_font_size", global_style["title_font_size"])),
                family=global_style["font_family"],
            ),
            title_x=float(settings.get("title_x", global_style["title_x"])),
            title_y=float(settings.get("title_y", global_style["title_y"])),
            title_xanchor=settings.get("title_xanchor", global_style["title_xanchor"]),
            title_yanchor=settings.get("title_yanchor", global_style["title_yanchor"]),
        )
    else:
        layout["title_text"] = ""

    if show_legend:
        layout["showlegend"] = True
        layout["legend"] = legend_layout
    else:
        layout["showlegend"] = False

    fig.update_layout(**layout)

    bar_width = settings.get("bar_width")
    if bar_width is not None:
        try:
            resolved_bar_width = float(bar_width)
        except (TypeError, ValueError):
            resolved_bar_width = None
        if resolved_bar_width is not None:
            for trace in getattr(fig, "data", ()):
                if getattr(trace, "type", None) == "bar":
                    trace.width = resolved_bar_width

    xstandoff = int(
        settings.get("x_title_standoff", global_style.get("axis_title_standoff", 4))
    )
    ystandoff = int(
        settings.get("y_title_standoff", global_style.get("axis_title_standoff", 4))
    )
    x_tick_font_size = int(
        settings.get(
            "x_tick_font_size",
            settings.get("axis_tick_font_size", global_style.get("axis_tick_font_size", 11)),
        )
    )
    y_tick_font_size = int(
        settings.get(
            "y_tick_font_size",
            settings.get("axis_tick_font_size", global_style.get("axis_tick_font_size", 11)),
        )
    )
    x_title_font_size = int(
        settings.get(
            "x_title_font_size",
            settings.get("axis_title_font_size", global_style.get("axis_title_font_size", 12)),
        )
    )
    y_title_font_size = int(
        settings.get(
            "y_title_font_size",
            settings.get("axis_title_font_size", global_style.get("axis_title_font_size", 12)),
        )
    )

    fig.update_xaxes(
        automargin=True,
        showgrid=bool(settings.get("x_showgrid", False)),
        title_standoff=xstandoff,
        tickfont=dict(size=x_tick_font_size, family=global_style["font_family"]),
        title_font=dict(size=x_title_font_size, family=global_style["font_family"]),
    )
    if bool(settings.get("skip_weekends", global_style.get("skip_weekends_default", False))):
        fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
    fig.update_yaxes(
        automargin=True,
        showgrid=bool(settings.get("y_showgrid", True)),
        gridcolor=settings.get("grid_color", global_style["grid_color"]),
        zerolinecolor=global_style["zero_line_color"],
        title_standoff=ystandoff,
        tickfont=dict(size=y_tick_font_size, family=global_style["font_family"]),
        title_font=dict(size=y_title_font_size, family=global_style["font_family"]),
    )
    if settings.get("type") == "radar":
        polar_cfg: dict[str, Any] = dict(
            bgcolor="rgba(0,0,0,0)",
            angularaxis=dict(
                tickfont=dict(
                    size=max(9, x_tick_font_size - 1),
                    family=global_style["font_family"],
                ),
                gridcolor=settings.get("grid_color", global_style["grid_color"]),
            ),
            radialaxis=dict(
                tickfont=dict(size=y_tick_font_size, family=global_style["font_family"]),
                gridcolor=settings.get("grid_color", global_style["grid_color"]),
                linecolor=global_style["zero_line_color"],
                showline=False,
                rangemode="tozero",
            ),
        )
        if settings.get("polar_radial_range") is not None:
            polar_cfg["radialaxis"]["range"] = settings.get("polar_radial_range")
        if settings.get("polar_radial_dtick") is not None:
            polar_cfg["radialaxis"]["dtick"] = settings.get("polar_radial_dtick")
        if settings.get("polar_ticksuffix") is not None:
            polar_cfg["radialaxis"]["ticksuffix"] = settings.get("polar_ticksuffix")
        fig.update_layout(polar=polar_cfg)
    if global_style.get("xaxis_tickangle") is not None:
        fig.update_xaxes(tickangle=global_style.get("xaxis_tickangle"))


__all__ = ["_apply_chart_chrome"]
