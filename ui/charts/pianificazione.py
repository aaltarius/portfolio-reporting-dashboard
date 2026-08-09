from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from core.config import COLORS
from ui.charts.runtime import finalize_chart
from ui.formatting import fmt_eur_it, fmt_pct_it
from ui.charts.natura_icons import get_natura_visual
from ui.theme import bucket_color, macro_color


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
        for bucket in ("Core", "Difensivo", "Satellite"):
            if bucket not in bucket_df.index:
                continue
            before = float(bucket_df.loc[bucket, "% prima"]) * 100.0
            after = float(bucket_df.loc[bucket, "% dopo"]) * 100.0
            fig.add_trace(go.Bar(
                name=bucket,
                x=["Prima", "Dopo"],
                y=[before, after],
                marker_color=bucket_color(bucket, theme),
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
    fig = go.Figure()
    for bucket in buckets:
        ob = obiettivo_pct[bucket]
        att = attuale_pct[bucket]
        fig.add_trace(go.Bar(
            name=bucket,
            x=["Obiettivo", "Attuale"],
            y=[ob, att],
            marker_color=bucket_color(bucket, theme),
            text=[fmt_pct_it(ob / 100.0, 1) if ob >= 4 else "", fmt_pct_it(att / 100.0, 1) if att >= 4 else ""],
            textposition="inside",
            hovertemplate=f"{bucket}: %{{y:.1f}}%<extra></extra>",
        ))
    return finalize_chart(fig, "pianificazione_obiettivo_mix", layout_updates={"barmode": "stack"})


def _pie_clockwise_order(items: list) -> list:
    """Contromisura per un comportamento di rendering di Plotly (verificato
    empiricamente su plotly 6.7.0, presente sia con sort=False sia col
    sort di default): anche passando le fette nell'ordine voluto, Plotly
    disegna in senso orario la prima fetta al suo posto ma TUTTE le altre
    in ordine invertito (es. [Core, Difensivo, Satellite] -> visivamente
    Core, Satellite, Difensivo). Passandogli invece [items[0]] +
    reversed(items[1:]), la sua stessa inversione a runtime restituisce
    l'ordine voluto - la doppia inversione si annulla. Senza questa
    contromisura l'anello esterno del donut Allocazione (o qualunque Pie
    con piu' di 2 fette e un ordine che deve avere un senso, es. allineato
    a un altro anello) risulta visivamente sfalsato rispetto all'ordine
    dei dati, anche se i dati stessi sono corretti."""
    if len(items) <= 2:
        return list(items)
    return [items[0]] + list(reversed(items[1:]))


def build_allocation_rings_chart(rings_df: pd.DataFrame, objective: dict, theme) -> go.Figure:
    """Donut a due anelli distanziati: interno Core/Difensivo/Satellite,
    esterno natura/esposizione (strumenti posseduti aggregati per natura
    *all'interno dello stesso bucket*, con legenda sull'anello esterno).
    Le fette esterne sono costruite nello stesso ordine di bucket
    dell'anello interno (Core, Difensivo, Satellite): l'arco di ciascun
    bucket nell'anello interno corrisponde cosi' esattamente all'arco
    delle sue natura nell'anello esterno - vedi _pie_clockwise_order per
    la contromisura al bug di rendering di Plotly che altrimenti sfalsa
    l'ordine visivo. L'hover dell'anello esterno elenca i singoli
    strumenti che compongono ciascuna fetta di natura."""
    fig = go.Figure()
    if rings_df is None or rings_df.empty:
        return finalize_chart(fig, "pianificazione_allocation_rings")
    inner_labels: list[str] = []
    inner_values: list[float] = []
    inner_colors: list[str] = []
    inner_hover: list[str] = []
    outer_labels: list[str] = []
    outer_values: list[float] = []
    outer_colors: list[str] = []
    outer_hover: list[str] = []
    natura_totals: dict[str, float] = {}
    for bucket in ("Core", "Difensivo", "Satellite"):
        sub = rings_df[rings_df["bucket"] == bucket]
        if sub.empty:
            continue
        total = float(sub["value"].sum())
        inner_labels.append(bucket)
        inner_values.append(total)
        inner_colors.append(bucket_color(bucket, theme))
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
            natura_totals[natura] = natura_totals.get(natura, 0.0) + float(group["value"])

    grand_total = sum(inner_values) or 1.0
    fig.add_trace(go.Pie(
        labels=_pie_clockwise_order(inner_labels),
        values=_pie_clockwise_order(inner_values),
        hole=0.5,
        domain=dict(x=[0.22, 0.78], y=[0.22, 0.78]),
        marker=dict(colors=_pie_clockwise_order(inner_colors), line=dict(color="rgba(255,255,255,0.6)", width=1)),
        textinfo="label",
        textposition="inside",
        insidetextorientation="horizontal",
        customdata=_pie_clockwise_order(inner_hover),
        hovertemplate="%{customdata}<extra></extra>",
        showlegend=False,
        sort=False,
    ))
    fig.add_trace(go.Pie(
        labels=_pie_clockwise_order(outer_labels),
        values=_pie_clockwise_order(outer_values),
        hole=0.60,
        domain=dict(x=[0.0, 1.0], y=[0.0, 1.0]),
        marker=dict(colors=_pie_clockwise_order(outer_colors), line=dict(color="rgba(255,255,255,0.6)", width=1)),
        textinfo="percent",
        textposition="inside",
        customdata=_pie_clockwise_order(outer_hover),
        hovertemplate="%{customdata}<extra></extra>",
        showlegend=False,
        sort=False,
    ))
    # La legenda della fetta esterna non puo' usare showlegend sulla traccia
    # Pie stessa: la sua lista di legenda segue l'ordine dati grezzo (senza
    # la contromisura di _pie_clockwise_order), quindi risulterebbe nello
    # stesso ordine sfalsato che _pie_clockwise_order corregge solo per il
    # disegno delle fette. Tracce fittizie (nessun punto reale disegnato)
    # una per natura unica, nell'ordine vero, danno una legenda leggibile e
    # indipendente dal bug di rendering.
    legend_seen: set[str] = set()
    for natura, color in zip(outer_labels, outer_colors):
        if natura in legend_seen:
            continue
        legend_seen.add(natura)
        pct = fmt_pct_it(natura_totals.get(natura, 0.0) / grand_total, 1)
        fig.add_trace(go.Scatter(
            x=[None], y=[None], mode="markers",
            marker=dict(size=10, color=color, symbol="square"),
            name=f"{natura} ({pct})", showlegend=True, hoverinfo="skip",
        ))
    for bucket, total, color in zip(inner_labels, inner_values, inner_colors):
        pct = fmt_pct_it(total / grand_total, 1)
        fig.add_trace(go.Scatter(
            x=[None], y=[None], mode="markers",
            marker=dict(size=10, color=color, symbol="square"),
            name=f"{bucket} ({pct})", showlegend=True, hoverinfo="skip",
            legend="legend2",
        ))
    fig = finalize_chart(fig, "pianificazione_allocation_rings")
    fig.update_layout(
        legend=dict(x=-0.35, y=0.5, xanchor="left", yanchor="middle"),
        legend2=dict(x=1.05, y=0.5, xanchor="left", yanchor="middle"),
    )
    fig.update_xaxes(visible=False, showgrid=False, showline=False, zeroline=False)
    fig.update_yaxes(visible=False, showgrid=False, showline=False, zeroline=False)
    return fig


_BUBBLE_QUADRANT_LABELS = (
    (0.29, 0.08, "Poco utile / non prioritario", "rgba(100,116,139,0.9)"),
    (0.79, 0.08, "Buon contributo difensivo", "rgba(21,128,61,0.9)"),
    (0.79, 0.71, "Diversifica ma aumenta volatilità", "rgba(161,98,7,0.9)"),
    (0.29, 0.71, "Satellite aggressivo / ridondante", "rgba(185,28,28,0.9)"),
)
_BUBBLE_DIV_THRESHOLD = 0.58
_BUBBLE_RISK_THRESHOLD = 0.42
_BUBBLE_AXIS_PAD = 0.10


def _bubble_axis_range(values: pd.Series, *, lower: float = 0.0, upper: float = 1.0, pad: float = _BUBBLE_AXIS_PAD) -> list[float]:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    if numeric.empty:
        return [lower - pad, upper + pad]
    min_v = min(lower, float(numeric.min()))
    max_v = max(upper, float(numeric.max()))
    span = max(max_v - min_v, upper - lower, 0.25)
    extra = max(pad, span * 0.08)
    return [min_v - extra, max_v + extra]


def _bubble_text_positions(x_values: pd.Series, y_values: pd.Series, x_range: list[float], y_range: list[float]) -> list[str]:
    x_span = max(x_range[1] - x_range[0], 1e-9)
    y_span = max(y_range[1] - y_range[0], 1e-9)
    positions: list[str] = []
    for x_raw, y_raw in zip(x_values, y_values):
        x = float(x_raw)
        y = float(y_raw)
        vertical = "bottom" if y > y_range[1] - y_span * 0.16 else "top"
        if x < x_range[0] + x_span * 0.13:
            horizontal = "right"
        elif x > x_range[1] - x_span * 0.13:
            horizontal = "left"
        else:
            horizontal = "center"
        positions.append(f"{vertical} {horizontal}")
    return positions


def build_next_purchase_bubble_chart(bubble_df: pd.DataFrame, theme) -> go.Figure:
    """Mappa a bolle dei prossimi acquisti (ultima fotografia SATOR salvata):
    X = diversificazione apportata, Y = rischio stimato (1 - risk_efficiency),
    dimensione bolla = importo proposto. Soglie 0,58/0,42 riprese da
    _build_manual_choice_feedback in ui/pages/pianificazione.py."""
    fig = go.Figure()
    if bubble_df is None or bubble_df.empty:
        return finalize_chart(fig, "pianificazione_next_purchase_bubble")
    df = bubble_df.copy()
    df["diversification_benefit"] = pd.to_numeric(df["diversification_benefit"], errors="coerce")
    df["risk_efficiency"] = pd.to_numeric(df["risk_efficiency"], errors="coerce")
    df["importo"] = pd.to_numeric(df["importo"], errors="coerce").fillna(0.0)
    df = df.dropna(subset=["diversification_benefit", "risk_efficiency"])
    if df.empty:
        return finalize_chart(fig, "pianificazione_next_purchase_bubble")
    df["rischio"] = 1.0 - df["risk_efficiency"]
    max_importo = max(float(df["importo"].max()), 1.0)
    df["marker_size"] = 16.0 + (df["importo"].clip(lower=0.0) / max_importo) * 22.0
    x_range = _bubble_axis_range(df["diversification_benefit"])
    y_range = _bubble_axis_range(df["rischio"])
    df["text_position"] = _bubble_text_positions(
        df["diversification_benefit"],
        df["rischio"],
        x_range,
        y_range,
    )
    for bucket in ("Core", "Difensivo", "Satellite"):
        sub = df[df["bucket"] == bucket]
        if sub.empty:
            continue
        fig.add_trace(go.Scatter(
            x=sub["diversification_benefit"],
            y=sub["rischio"],
            mode="markers+text",
            text=sub["ticker"],
            textposition=sub["text_position"],
            name=bucket,
            cliponaxis=False,
            marker=dict(
                size=sub["marker_size"],
                color=bucket_color(bucket, theme),
                opacity=0.82,
                line=dict(color="rgba(17,24,39,0.28)", width=1),
            ),
            customdata=sub[[
                "name", "importo", "target_improvement_pp", "post_nature_weight",
                "nature_cap", "data_quality_label",
            ]].to_numpy(),
            hovertemplate=(
                "<b>%{text}</b> — %{customdata[0]}<br>"
                "Diversificazione: %{x:.2f}<br>"
                "Rischio stimato: %{y:.2f}<br>"
                "Importo proposto: € %{customdata[1]:,.0f}<br>"
                "Impatto target: %{customdata[2]:+.1f} pp<br>"
                "Natura post-acquisto: %{customdata[3]:.1%} / cap %{customdata[4]:.1%}<br>"
                "Qualita' dati: %{customdata[5]}<extra></extra>"
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
    fig.update_xaxes(title_text="Diversificazione apportata", range=x_range, tickformat=".2f", constrain="domain")
    fig.update_yaxes(title_text="Rischio stimato", range=y_range, tickformat=".2f", scaleanchor=None)
    fig = finalize_chart(fig, "pianificazione_next_purchase_bubble")
    fig.update_layout(
        margin=dict(l=58, r=42, t=54, b=74),
        legend=dict(orientation="h", yanchor="top", y=-0.16, xanchor="center", x=0.5),
        uniformtext=dict(mode="show"),
    )
    fig.update_xaxes(range=x_range, constrain="domain")
    fig.update_yaxes(range=y_range, scaleanchor=None)
    return fig


def _declutter_text_positions(x_values, y_values) -> list[str]:
    """Assegna la posizione dell'etichetta (alto/basso/destra/sinistra) punto
    per punto per ridurre le sovrapposizioni tra bolle vicine.

    Euristica greedy in spazio normalizzato: per ogni punto, tra le 4
    posizioni candidate sceglie quella la cui etichetta cade piu' lontana da
    tutte le etichette gia' assegnate. Non elimina le sovrapposizioni quando
    tanti punti sono davvero vicini tra loro (in quel caso e' informativo:
    significa che quegli strumenti si comportano in modo simile), ma le
    riduce sensibilmente rispetto a un'unica posizione fissa per tutti."""
    positions = ["top center", "bottom center", "middle right", "middle left"]
    offsets = {"top center": (0.0, 0.05), "bottom center": (0.0, -0.05), "middle right": (0.055, 0.0), "middle left": (-0.055, 0.0)}
    xs = pd.to_numeric(pd.Series(x_values), errors="coerce").fillna(0.0).to_numpy(dtype=float)
    ys = pd.to_numeric(pd.Series(y_values), errors="coerce").fillna(0.0).to_numpy(dtype=float)
    n = len(xs)
    if n == 0:
        return []
    x_range = max(float(xs.max() - xs.min()), 1e-9)
    y_range = max(float(ys.max() - ys.min()), 1e-9)
    xn = (xs - xs.min()) / x_range
    yn = (ys - ys.min()) / y_range
    order = sorted(range(n), key=lambda i: -yn[i])
    assigned = [""] * n
    anchors: list[tuple[float, float]] = []
    for i in order:
        best_pos, best_dist, best_anchor = positions[0], -1.0, (xn[i], yn[i])
        for pos in positions:
            dx, dy = offsets[pos]
            ax, ay = xn[i] + dx, yn[i] + dy
            min_d = min((((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5 for bx, by in anchors), default=999.0)
            if min_d > best_dist:
                best_dist, best_pos, best_anchor = min_d, pos, (ax, ay)
        assigned[i] = best_pos
        anchors.append(best_anchor)
    return assigned


def build_instrument_map_chart(scatter_df: pd.DataFrame, theme) -> go.Figure:
    """Mappa strumenti rischio/rendimento storico osservato (Progetto C,
    ROADMAP_AI_FINANZA_LIBRO.md): X = volatilita' annualizzata, Y =
    rendimento storico realizzato (solo dato passato, vedi return_label per
    l'orizzonte usato), dimensione bolla = peso attuale in portafoglio (0 per
    i soli osservati). Colore per categoria (Core/Difensivo/Satellite) su
    entrambi; la proprieta' si legge dalla forma del marker (pieno =
    posseduto, cerchio vuoto = solo osservato), non da una tinta in piu' da
    distinguere dalle altre - due tentativi precedenti con un colore unico
    per "osservato" (grigio, poi viola) restavano poco leggibili accanto
    alle categorie."""
    fig = go.Figure()
    if scatter_df is None or scatter_df.empty:
        return finalize_chart(fig, "pianificazione_instrument_map")
    df = scatter_df.copy()
    df["ownership_label"] = df["in_portfolio"].map({True: "Posseduto", False: "In osservazione"})
    max_weight = max(float(df["current_weight"].max()), 1e-6)
    df["marker_size"] = 10.0 + (df["current_weight"].clip(lower=0.0) / max_weight) * 26.0
    df["text_position"] = _declutter_text_positions(df["vol"], df["return_value"])
    hover_template = (
        "<b>%{customdata[0]}</b> — %{customdata[1]}<br>"
        "Natura: %{customdata[2]}<br>"
        "Volatilita' annua: %{x:.1%}<br>"
        "Rendimento storico %{customdata[3]}: %{y:+.1%}<br>"
        "Peso in portafoglio: %{customdata[5]:.1%}<br>"
        "%{customdata[4]}<extra></extra>"
    )
    customdata_cols = ["ticker", "name", "nature", "return_label", "ownership_label", "current_weight"]
    for category in sorted(df["category"].dropna().unique()):
        cat_color = macro_color(str(category))
        owned = df[(df["category"] == category) & df["in_portfolio"]]
        if not owned.empty:
            fig.add_trace(go.Scatter(
                x=owned["vol"], y=owned["return_value"], mode="markers+text",
                name=str(category), legendgroup=str(category), text=owned["ticker"],
                textposition=owned["text_position"], textfont=dict(size=9),
                marker=dict(size=owned["marker_size"], color=cat_color, opacity=0.85, line=dict(color="rgba(17,24,39,0.55)", width=1.0)),
                customdata=owned[customdata_cols].to_numpy(),
                hovertemplate=hover_template,
            ))
        observed = df[(df["category"] == category) & ~df["in_portfolio"]]
        if not observed.empty:
            fig.add_trace(go.Scatter(
                x=observed["vol"], y=observed["return_value"], mode="markers+text",
                name=f"{category} (osservato)", legendgroup=str(category),
                text=observed["ticker"], textposition=observed["text_position"], textfont=dict(size=9),
                marker=dict(size=observed["marker_size"], symbol="circle-open", color=cat_color, line=dict(width=2.4)),
                customdata=observed[customdata_cols].to_numpy(),
                hovertemplate=hover_template,
            ))
    fig = finalize_chart(fig, "pianificazione_instrument_map")
    return fig


def build_sator_explanation_chart(explanations, theme) -> go.Figure:
    """Barre orizzontali impilate: contributo pesato di ciascun fattore al
    voto SATOR, uno strumento per riga.

    chart_id: pianificazione_sator_explain
    chiamato da: ui/pages/pianificazione.py
    """
    fig = go.Figure()
    if not explanations:
        return finalize_chart(fig, "pianificazione_sator_explain")

    factor_colors = {
        "strategic_fit": getattr(theme, "color_blue", "#5B8DEF"),
        "tactical_momentum": getattr(theme, "color_orange", "#d97706"),
        "risk_efficiency": getattr(theme, "color_red", "#dc2626"),
        "diversification_benefit": getattr(theme, "color_green", "#16803c"),
        "cost_efficiency": getattr(theme, "color_purple", "#8E44AD"),
    }
    tickers = [exp.ticker for exp in explanations]
    factor_order = [c.factor for c in explanations[0].contributions]

    # Ogni barra parte da 1.0 (il minimo del voto SATOR), non da 0: cosi'
    # l'asse X e' direttamente la scala voto 1-10 usata ovunque nell'app,
    # invece di una scala "punti su 9" (voto-1) che il lettore deve
    # convertire a mente - fonte di confusione gia' segnalata (una barra
    # che arriva a ~7 su una scala 0-9 non si legge come "voto 8"). Base
    # esplicita per ogni traccia (non barmode="stack" automatico): la somma
    # cumulativa dei segmenti arriva esattamente al voto vero, per
    # costruzione (1 + score_finale*9 == voto, la stessa formula di SATOR).
    running_base = {exp.ticker: 1.0 for exp in explanations}
    for factor in factor_order:
        label = next(c.label for c in explanations[0].contributions if c.factor == factor)
        x_values = []
        base_values = []
        raw_scores = []
        for exp in explanations:
            contrib = next(c for c in exp.contributions if c.factor == factor)
            segment = contrib.contribution * 9.0
            base_values.append(running_base[exp.ticker])
            x_values.append(segment)
            raw_scores.append(contrib.raw_score)
            running_base[exp.ticker] += segment
        fig.add_trace(go.Bar(
            y=tickers,
            x=x_values,
            base=base_values,
            orientation="h",
            name=label,
            marker_color=factor_colors.get(factor, COLORS.get("gray", "#6b7280")),
            customdata=raw_scores,
            hovertemplate=(
                f"<b>{label}</b><br>Contributo: %{{x:.2f}} punti voto<br>"
                "Punteggio fattore: %{customdata:.0%}<extra></extra>"
            ),
        ))

    # Etichetta col voto vero, ancorata alla STESSA posizione X per tutti
    # gli strumenti (non a fine barra, che varierebbe riga per riga):
    # "middle left" fa crescere il testo verso sinistra dall'ancora, quindi
    # il bordo destro di ogni etichetta risulta allineato alla stessa X -
    # una colonna di numeri, non un'accozzaglia a lunghezze diverse.
    label_anchor_x = 10.3
    fig.add_trace(go.Scatter(
        y=tickers,
        x=[label_anchor_x] * len(tickers),
        mode="text",
        text=[f"Voto {exp.voto:.1f}" for exp in explanations],
        textposition="middle left",
        textfont=dict(size=11, color=getattr(theme, "font_color", "#1f2937")),
        showlegend=False,
        hoverinfo="skip",
        cliponaxis=False,
    ))

    # barmode="overlay": ogni barra e' gia' posizionata esplicitamente da
    # base+x sopra, non serve (ne' si deve) lasciare che Plotly la
    # ristacki automaticamente da zero.
    fig.update_layout(barmode="overlay")
    fig = finalize_chart(fig, "pianificazione_sator_explain")
    # force_all_y_categories (dentro apply_settings/finalize_chart, attiva di
    # default per le barre orizzontali) sovrascrive qualunque categoryarray
    # impostato prima di questa chiamata con l'ordine di apparizione delle
    # tracce: va applicato DOPO, stesso pattern usato in
    # ui/charts/calendario_btp.py per lo stesso motivo. Su un asse Y
    # orizzontale Plotly disegna categoryarray[0] in basso, quindi l'ultimo
    # elemento deve essere il ticker col voto piu' alto (tickers[0], visto
    # che explanations e' ordinato per voto decrescente) perche' finisca in
    # cima.
    fig.update_yaxes(categoryorder="array", categoryarray=list(reversed(tickers)))
    # La legenda orizzontale, di default, elenca le tracce nell'ordine di
    # aggiunta (strategic_fit -> cost_efficiency, da sinistra a destra) -
    # coerente in teoria con l'ordine dei segmenti nella barra (che parte
    # da strategic_fit vicino alla base). Segnalato pero' come percepito al
    # contrario: "reversed" e' l'impostazione raccomandata da Plotly stesso
    # per allineare legenda e ordine di impilamento nei grafici a barre
    # impilate. Riapplicato DOPO finalize_chart per lo stesso motivo del
    # categoryarray sopra.
    fig.update_layout(legend=dict(traceorder="reversed"))
    return fig
