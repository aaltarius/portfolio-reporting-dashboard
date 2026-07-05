from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from ui.charts.runtime import finalize_chart
from ui.formatting import fmt_eur_it, fmt_pct_it


def build_composition_donut_chart(per_funzione: pd.Series, theme) -> go.Figure:
    """Donut della composizione Core/Difensivo/Satellite (o per funzione)."""
    fig = go.Figure()
    if per_funzione is not None and not per_funzione.empty:
        values = [float(v) for v in per_funzione.values]
        total = sum(values)
        labels = [
            f"{label} - {fmt_eur_it(value, 2)} ({fmt_pct_it(value / total, 1)})" if total > 0 else str(label)
            for label, value in zip(per_funzione.index, values)
        ]
        palette = [
            getattr(theme, "color_blue", "#5B8DEF"), getattr(theme, "color_green", "#22c55e"),
            getattr(theme, "color_orange", "#E8B960"), "#B07CC6", "#6FB3B8", "#E07A5F",
            getattr(theme, "color_gray", "#94a3b8"), "#A3B18A", "#577590",
        ]
        fig.add_trace(go.Pie(
            labels=labels,
            values=values,
            hole=0.55,
            marker=dict(colors=palette[: len(per_funzione)]),
            textinfo="percent",
            hovertemplate="%{label}<extra></extra>",
        ))
        fig.update_traces(domain=dict(x=[0.0, 0.68]))
    return finalize_chart(fig, "pianificazione_composizione")


def build_ante_post_bucket_chart(bucket_df: pd.DataFrame, theme) -> go.Figure:
    """Mix Core/Difensivo/Satellite prima e dopo un ordine simulato."""
    fig = go.Figure()
    if bucket_df is not None and not bucket_df.empty:
        colors = {
            "Core": getattr(theme, "color_blue", "#5B8DEF"),
            "Difensivo": getattr(theme, "color_green", "#22c55e"),
            "Satellite": getattr(theme, "color_orange", "#E8B960"),
        }
        for bucket in ("Core", "Difensivo", "Satellite"):
            if bucket not in bucket_df.index:
                continue
            before = float(bucket_df.loc[bucket, "% prima"]) * 100.0
            after = float(bucket_df.loc[bucket, "% dopo"]) * 100.0
            fig.add_trace(go.Bar(
                name=bucket,
                x=["Prima", "Dopo"],
                y=[before, after],
                marker_color=colors.get(bucket),
                text=[fmt_pct_it(before / 100.0, 1) if before >= 4 else "", fmt_pct_it(after / 100.0, 1) if after >= 4 else ""],
                textposition="inside",
                hovertemplate=f"{bucket}: %{{y:.1f}}%<extra></extra>",
            ))
    return finalize_chart(fig, "pianificazione_ante_post", layout_updates={"barmode": "stack"})


def build_objective_mix_chart(objective: dict, current_mix: dict, theme) -> go.Figure:
    """Obiettivo di portafoglio vs mix attuale, per bucket Core/Difensivo/Satellite."""
    buckets = ("Core", "Difensivo", "Satellite")
    obiettivo_pct = {
        "Core": objective.get("core", 0.0) * 100.0,
        "Difensivo": objective.get("difensivo", 0.0) * 100.0,
        "Satellite": objective.get("satellite", 0.0) * 100.0,
    }
    attuale_pct = {b: float(current_mix.get(b, 0.0)) * 100.0 for b in buckets}
    colors = {
        "Core": getattr(theme, "color_blue", "#5B8DEF"),
        "Difensivo": getattr(theme, "color_green", "#22c55e"),
        "Satellite": getattr(theme, "color_orange", "#E8B960"),
    }
    fig = go.Figure()
    for bucket in buckets:
        ob = obiettivo_pct[bucket]
        att = attuale_pct[bucket]
        fig.add_trace(go.Bar(
            name=bucket,
            x=["Obiettivo", "Attuale"],
            y=[ob, att],
            marker_color=colors.get(bucket),
            text=[fmt_pct_it(ob / 100.0, 1) if ob >= 4 else "", fmt_pct_it(att / 100.0, 1) if att >= 4 else ""],
            textposition="inside",
            hovertemplate=f"{bucket}: %{{y:.1f}}%<extra></extra>",
        ))
    return finalize_chart(fig, "pianificazione_obiettivo_mix", layout_updates={"barmode": "stack"})
