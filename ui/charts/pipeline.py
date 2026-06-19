from __future__ import annotations

from typing import Any, Callable


def apply_settings_pipeline(
    fig,
    settings: dict[str, Any],
    *,
    clear_all_range_controls: Callable[[Any], None],
    computed_margin: Callable[[Any, dict[str, Any]], dict[str, int]],
    apply_chart_chrome: Callable[[Any, dict[str, Any], dict[str, int]], None],
    apply_axis_settings: Callable[[Any, dict[str, Any]], tuple[Any, Any, Any]],
    apply_buttons: Callable[[Any, dict[str, Any]], None],
    bar_protection: Callable[[Any, dict[str, Any]], None],
    normalise_bar_text: Callable[[Any, dict[str, Any]], None],
    force_all_y_categories: Callable[[Any, dict[str, Any]], None],
    force_all_x_categories: Callable[[Any, dict[str, Any]], None],
    force_heatmap_labels_and_square: Callable[[Any, dict[str, Any]], None],
    apply_horizontal_bar_axis_spacing: Callable[[Any, dict[str, Any]], None],
    reapply_forced_ranges: Callable[[Any, Any, Any, Any], None],
    compact_money_axes: Callable[[Any, dict[str, Any]], None],
    reapply_y2_after_money: Callable[[Any, dict[str, Any]], None],
    force_time_default_range: Callable[[Any, dict[str, Any]], None],
    apply_initial_visible_y_range: Callable[[Any, dict[str, Any]], None],
    normalise_baseline_lines: Callable[[Any, dict[str, Any]], None],
    normalise_baseline_axis_titles: Callable[[Any, dict[str, Any]], None],
    normalise_annotations: Callable[[Any, dict[str, Any]], None],
):
    """Orchestra il pipeline finale di apply_settings senza conoscere Plotly-specific internals."""
    clear_all_range_controls(fig)
    margin = computed_margin(fig, settings)
    apply_chart_chrome(fig, settings, margin)

    x_range, y_range, y2_range = apply_axis_settings(fig, settings)
    apply_buttons(fig, settings)
    bar_protection(fig, settings)
    normalise_bar_text(fig, settings)
    force_all_y_categories(fig, settings)
    force_all_x_categories(fig, settings)
    force_heatmap_labels_and_square(fig, settings)
    apply_horizontal_bar_axis_spacing(fig, settings)
    reapply_forced_ranges(fig, x_range, y_range, y2_range)

    compact_money_axes(fig, settings)
    reapply_y2_after_money(fig, settings)

    force_time_default_range(fig, settings)
    apply_initial_visible_y_range(fig, settings)
    normalise_baseline_lines(fig, settings)
    normalise_baseline_axis_titles(fig, settings)
    normalise_annotations(fig, settings)
    return fig


__all__ = ["apply_settings_pipeline"]
