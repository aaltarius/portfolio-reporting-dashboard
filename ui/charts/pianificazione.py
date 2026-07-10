from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from ui.charts.runtime import finalize_chart
from ui.formatting import fmt_eur_it, fmt_pct_it
from ui.charts.natura_icons import get_natura_visual


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


def build_allocation_rings_chart(rings_df: pd.DataFrame, objective: dict, theme) -> go.Figure:
    """Donut a due anelli distanziati: interno Core/Difensivo/Satellite,
    esterno natura/esposizione (strumenti posseduti aggregati per natura
    *all'interno dello stesso bucket*, con legenda sull'anello esterno).
    Le fette esterne sono costruite nello stesso ordine di bucket
    dell'anello interno (Core, Difensivo, Satellite) e sort=False su
    entrambe le tracce: l'arco di ciascun bucket nell'anello interno
    corrisponde cosi' esattamente all'arco delle sue natura nell'anello
    esterno. L'hover dell'anello esterno elenca i singoli strumenti che
    compongono ciascuna fetta di natura."""
    fig = go.Figure()
    if rings_df is None or rings_df.empty:
        return finalize_chart(fig, "pianificazione_allocation_rings")
    bucket_colors = {
        "Core": getattr(theme, "color_blue", "#5B8DEF"),
        "Difensivo": getattr(theme, "color_green", "#22c55e"),
        "Satellite": getattr(theme, "color_orange", "#E8B960"),
    }
    inner_labels: list[str] = []
    inner_values: list[float] = []
    inner_colors: list[str] = []
    inner_hover: list[str] = []
    outer_labels: list[str] = []
    outer_values: list[float] = []
    outer_colors: list[str] = []
    outer_hover: list[str] = []
    for bucket in ("Core", "Difensivo", "Satellite"):
        sub = rings_df[rings_df["bucket"] == bucket]
        if sub.empty:
            continue
        total = float(sub["value"].sum())
        inner_labels.append(bucket)
        inner_values.append(total)
        inner_colors.append(bucket_colors[bucket])
        inner_hover.append(f"{bucket}<br>{fmt_eur_it(total, 2)}")

        natura_groups: dict[str, dict[str, object]] = {}
        for _, row in sub.iterrows():
            natura = str(row["natura"])
            group = natura_groups.setdefault(natura, {"value": 0.0, "items": []})
            group["value"] = float(group["value"]) + float(row["value"])
            group["items"].append((str(row["ticker"]), float(row["value"])))
        for natura, group in natura_groups.items():
            outer_labels.append(natura)
            outer_values.append(float(group["value"]))
            outer_colors.append(get_natura_visual(natura)[0])
            outer_hover.append(
                "<br>".join(
                    [f"<b>{natura}</b>"] + [f"{tk}: {fmt_eur_it(v, 2)}" for tk, v in group["items"]]
                )
            )

    fig.add_trace(go.Pie(
        labels=inner_labels,
        values=inner_values,
        hole=0.5,
        domain=dict(x=[0.22, 0.78], y=[0.22, 0.78]),
        marker=dict(colors=inner_colors, line=dict(color="rgba(255,255,255,0.6)", width=1)),
        textinfo="label",
        customdata=inner_hover,
        hovertemplate="%{customdata}<extra></extra>",
        showlegend=False,
        sort=False,
    ))
    fig.add_trace(go.Pie(
        labels=outer_labels,
        values=outer_values,
        hole=0.60,
        domain=dict(x=[0.0, 1.0], y=[0.0, 1.0]),
        marker=dict(colors=outer_colors, line=dict(color="rgba(255,255,255,0.6)", width=1)),
        textinfo="percent",
        customdata=outer_hover,
        hovertemplate="%{customdata}<extra></extra>",
        showlegend=True,
        sort=False,
    ))
    return finalize_chart(fig, "pianificazione_allocation_rings")


def _format_matrix_cell(value: float) -> str:
    """Formatta il punteggio della matrice di copertura: interi senza
    decimali (es. 4, 2), frazioni arrotondate a 2 decimali senza zeri
    superflui (es. 1.33, 0.5) - il punteggio si divide tra gli strumenti
    che condividono la stessa area (vedi build_coverage_matrix_frame)."""
    if value == 0:
        return "0"
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def build_coverage_matrix_chart(matrix_df: pd.DataFrame, theme) -> go.Figure:
    """Heatmap: copertura e sovrapposizione per natura/area di mercato tra
    gli strumenti posseduti (righe) e le natura di posseduti + candidati SATOR
    (colonne). Il punteggio 4 di un'area si divide equamente tra gli
    strumenti posseduti che la condividono (vedi build_coverage_matrix_frame
    in core/services/sator.py)."""
    fig = go.Figure()
    if matrix_df is None or matrix_df.empty:
        return finalize_chart(fig, "pianificazione_coverage_matrix")
    z = matrix_df.to_numpy(dtype=float)
    text = [[_format_matrix_cell(v) for v in row] for row in z]
    accent = getattr(theme, "color_blue", "#5B8DEF")
    fig.add_trace(go.Heatmap(
        z=z,
        x=list(matrix_df.columns),
        y=list(matrix_df.index),
        zmin=0,
        zmax=4,
        colorscale=[[0.0, "rgba(91,141,239,0.06)"], [1.0, accent]],
        text=text,
        texttemplate="%{text}",
        textfont=dict(size=11),
        hovertemplate="%{y} · %{x}<br>Punteggio: %{text}<extra></extra>",
        showscale=False,
        xgap=2,
        ygap=2,
    ))
    rows = len(matrix_df.index)
    fig.update_layout(height=max(320, min(760, 170 + rows * 30)))
    return finalize_chart(fig, "pianificazione_coverage_matrix")


_BUBBLE_QUADRANT_LABELS = (
    (0.29, 0.08, "Poco utile / non prioritario", "rgba(100,116,139,0.9)"),
    (0.79, 0.08, "Buon contributo difensivo", "rgba(21,128,61,0.9)"),
    (0.79, 0.71, "Diversifica ma aumenta volatilità", "rgba(161,98,7,0.9)"),
    (0.29, 0.71, "Satellite aggressivo / ridondante", "rgba(185,28,28,0.9)"),
)
_BUBBLE_DIV_THRESHOLD = 0.58
_BUBBLE_RISK_THRESHOLD = 0.42


def build_next_purchase_bubble_chart(bubble_df: pd.DataFrame, theme) -> go.Figure:
    """Mappa a bolle dei prossimi acquisti (ultima fotografia SATOR salvata):
    X = diversificazione apportata, Y = rischio stimato (1 - risk_efficiency),
    dimensione bolla = importo proposto. Soglie 0,58/0,42 riprese da
    _build_manual_choice_feedback in ui/pages/pianificazione.py."""
    fig = go.Figure()
    if bubble_df is None or bubble_df.empty:
        return finalize_chart(fig, "pianificazione_next_purchase_bubble")
    df = bubble_df.copy()
    df["rischio"] = 1.0 - df["risk_efficiency"]
    max_importo = max(float(df["importo"].max()), 1.0)
    df["marker_size"] = 14.0 + (df["importo"].clip(lower=0.0) / max_importo) * 26.0
    bucket_colors = {
        "Core": getattr(theme, "color_blue", "#5B8DEF"),
        "Difensivo": getattr(theme, "color_green", "#22c55e"),
        "Satellite": getattr(theme, "color_orange", "#E8B960"),
    }
    for bucket in ("Core", "Difensivo", "Satellite"):
        sub = df[df["bucket"] == bucket]
        if sub.empty:
            continue
        fig.add_trace(go.Scatter(
            x=sub["diversification_benefit"],
            y=sub["rischio"],
            mode="markers+text",
            text=sub["ticker"],
            textposition="top center",
            name=bucket,
            marker=dict(
                size=sub["marker_size"],
                color=bucket_colors[bucket],
                opacity=0.82,
                line=dict(color="rgba(17,24,39,0.28)", width=1),
            ),
            customdata=sub[["name", "importo"]].to_numpy(),
            hovertemplate=(
                "<b>%{text}</b> — %{customdata[0]}<br>"
                "Diversificazione: %{x:.2f}<br>"
                "Rischio stimato: %{y:.2f}<br>"
                "Importo proposto: € %{customdata[1]:,.0f}<extra></extra>"
            ),
        ))
    quadrants = (
        (0.0, _BUBBLE_DIV_THRESHOLD, 0.0, _BUBBLE_RISK_THRESHOLD, "rgba(100,116,139,0.05)"),
        (_BUBBLE_DIV_THRESHOLD, 1.0, 0.0, _BUBBLE_RISK_THRESHOLD, "rgba(34,197,94,0.06)"),
        (_BUBBLE_DIV_THRESHOLD, 1.0, _BUBBLE_RISK_THRESHOLD, 1.0, "rgba(234,179,8,0.06)"),
        (0.0, _BUBBLE_DIV_THRESHOLD, _BUBBLE_RISK_THRESHOLD, 1.0, "rgba(239,68,68,0.05)"),
    )
    for x0, x1, y0, y1, color in quadrants:
        fig.add_shape(type="rect", x0=x0, x1=x1, y0=y0, y1=y1, fillcolor=color, line_width=0, layer="below")
    fig.add_vline(x=_BUBBLE_DIV_THRESHOLD, line_dash="dash", line_color="rgba(100,116,139,0.55)", line_width=1)
    fig.add_hline(y=_BUBBLE_RISK_THRESHOLD, line_dash="dash", line_color="rgba(100,116,139,0.55)", line_width=1)
    for x, y, text, color in _BUBBLE_QUADRANT_LABELS:
        fig.add_annotation(x=x, y=y, text=text, showarrow=False, font=dict(size=10, color=color))
    fig.update_xaxes(title_text="Diversificazione apportata", range=[0.0, 1.0], tickformat=".2f")
    fig.update_yaxes(title_text="Rischio stimato", range=[0.0, 1.0], tickformat=".2f")
    return finalize_chart(fig, "pianificazione_next_purchase_bubble")
