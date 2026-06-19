from __future__ import annotations

import plotly.graph_objects as go

from ui.charts.runtime import finalize_chart
from ui.formatting import fmt_eur_it, fmt_pct_it


def build_planning_allocation_chart(before_df, after_df, theme):
    """Grouped before/after allocation chart for planning simulations."""
    fig = go.Figure()
    if before_df is not None and after_df is not None and not before_df.empty and not after_df.empty:
        cats = before_df["Categoria"].tolist()
        after_map = dict(zip(after_df["Categoria"], after_df["Peso"]))
        before_vals = before_df["Peso"].tolist()
        after_vals = [after_map.get(cat, 0.0) for cat in cats]
        fig.add_bar(
            x=cats,
            y=before_vals,
            name="Prima",
            marker_color=theme.color_blue,
            text=[fmt_pct_it(v, 1) for v in before_vals],
            textposition="outside",
        )
        fig.add_bar(
            x=cats,
            y=after_vals,
            name="Dopo",
            marker_color=theme.color_orange,
            text=[fmt_pct_it(v, 1) for v in after_vals],
            textposition="outside",
        )
    return finalize_chart(
        fig,
        "pianificazione_allocation",
        layout_updates={"barmode": "group", "bargap": 0.24, "bargroupgap": 0.08},
        yaxis_updates={"tickformat": ".0%"},
    )


def build_planning_scenarios_chart(scenario_df, theme):
    """Scenario chart for hypothetical return paths."""
    fig = go.Figure()
    if scenario_df is not None and not scenario_df.empty:
        colors = [theme.color_blue, theme.color_orange, theme.color_green, theme.color_red]
        for idx, (scenario, group) in enumerate(scenario_df.groupby("Scenario")):
            fig.add_trace(
                go.Scatter(
                    x=group["Orizzonte"],
                    y=group["Valore simulato"],
                    mode="lines+markers+text",
                    name=str(scenario),
                    line=dict(width=2.5, color=colors[idx % len(colors)]),
                    text=[fmt_eur_it(v, 0) for v in group["Valore simulato"]],
                    textposition="top center",
                    hovertemplate="%{x}<br>Valore simulato: %{y:,.2f}<extra></extra>",
                )
            )
    return finalize_chart(
        fig,
        "pianificazione_scenarios",
        hovermode="x unified",
        yaxis_updates={"tickformat": ",.0f"},
    )


def build_sator_ranking_chart(ranking_df, theme):
    fig = go.Figure()
    if ranking_df is not None and not ranking_df.empty:
        top = ranking_df.head(10).copy()
        top = top.sort_values("score_finale", ascending=True)
        colors = []
        for _, row in top.iterrows():
            if str(row.get("challenger_flag") or "") == "Watchlist":
                colors.append(theme.color_green)
            elif bool(row.get("in_portfolio")):
                colors.append(theme.color_blue)
            else:
                colors.append(theme.color_orange)
        fig.add_bar(
            x=top["score_finale"],
            y=top["ticker"],
            orientation="h",
            marker_color=colors,
            text=[f"{float(v):.2f}" for v in top["score_finale"]],
            textposition="outside",
            customdata=top[["comparison_group", "challenger_flag", "selection_reason"]],
            hovertemplate="<b>%{y}</b><br>Score: %{x:.2f}<br>Stato: %{customdata[1]}<br>Gruppo: %{customdata[0]}<br>%{customdata[2]}<extra></extra>",
        )
    return finalize_chart(
        fig,
        "pianificazione_allocation",
        layout_updates={"showlegend": False},
        xaxis_updates={"range": [0, 1.05], "tickformat": ".2f"},
    )


def build_sator_scenarios_chart(scenarios_df, theme):
    fig = go.Figure()
    if scenarios_df is not None and not scenarios_df.empty:
        work = scenarios_df.copy()
        work["Utilizzo"] = work["Importo usato"] / (work["Importo usato"] + work["Residuo"]).replace(0, 1)
        work = work.sort_values("Importo usato", ascending=True)
        fig.add_bar(
            x=work["Importo usato"],
            y=work["Scenario"],
            orientation="h",
            name="Importo usato",
            marker_color=theme.color_blue,
            text=[f"{fmt_eur_it(v, 0)} | {fmt_pct_it(u, 0)}" for v, u in zip(work["Importo usato"], work["Utilizzo"])],
            textposition="outside",
        )
        fig.add_bar(
            x=work["Residuo"],
            y=work["Scenario"],
            orientation="h",
            name="Residuo",
            marker_color=theme.color_orange,
            text=[fmt_eur_it(v, 0) if float(v) > 0 else "" for v in work["Residuo"]],
            textposition="outside",
        )
    return finalize_chart(
        fig,
        "pianificazione_allocation",
        layout_updates={"barmode": "stack", "bargap": 0.28, "bargroupgap": 0.08},
        xaxis_updates={"tickformat": ",.0f"},
    )


def build_sator_challenger_chart(challenger_df, theme):
    fig = go.Figure()
    if challenger_df is not None and not challenger_df.empty:
        work = challenger_df.copy()
        work["Delta"] = work["Score challenger"].fillna(0.0) - work["Score incumbent"].fillna(0.0)
        fig.add_bar(
            x=work["Delta"],
            y=work["Gruppo"],
            orientation="h",
            marker_color=[theme.color_green if v >= 0 else theme.color_red for v in work["Delta"]],
            text=[fmt_pct_it(v, 1, signed=True) for v in work["Delta"]],
            textposition="outside",
            customdata=work[["Incumbent", "Challenger", "Decisione"]],
            hovertemplate="%{y}<br>Incumbent: %{customdata[0]}<br>Challenger: %{customdata[1]}<br>Delta score: %{x:.2f}<br>%{customdata[2]}<extra></extra>",
        )
        fig.add_vline(x=0, line_color="rgba(15,23,42,.35)", line_width=1)
    return finalize_chart(
        fig,
        "pianificazione_allocation",
        layout_updates={"showlegend": False},
        xaxis_updates={"tickformat": ".0%"},
    )


def build_sator_projection_chart(projection_df, theme):
    fig = go.Figure()
    if projection_df is not None and not projection_df.empty:
        work = projection_df.copy()
        fig.add_bar(
            x=work["Orizzonte"],
            y=work["Banda prudente"],
            name="Prudente",
            marker_color=theme.color_red,
            text=[fmt_pct_it(v, 1, signed=True) for v in work["Banda prudente"]],
            textposition="outside",
        )
        fig.add_bar(
            x=work["Orizzonte"],
            y=work["Atteso condizionale"],
            name="Atteso",
            marker_color=theme.color_blue,
            text=[fmt_pct_it(v, 1, signed=True) for v in work["Atteso condizionale"]],
            textposition="outside",
        )
        fig.add_bar(
            x=work["Orizzonte"],
            y=work["Banda favorevole"],
            name="Favorevole",
            marker_color=theme.color_green,
            text=[fmt_pct_it(v, 1, signed=True) for v in work["Banda favorevole"]],
            textposition="outside",
        )
    return finalize_chart(
        fig,
        "pianificazione_scenarios",
        hovermode="x unified",
        layout_updates={"barmode": "group", "bargap": 0.22, "bargroupgap": 0.08},
        yaxis_updates={"tickformat": ".0%"},
    )


def build_sator_factor_chart(factor_df, theme):
    fig = go.Figure()
    if factor_df is not None and not factor_df.empty:
        work = factor_df.copy().sort_values("Punteggio", ascending=True)
        colors = []
        for score in work["Punteggio"]:
            if float(score) >= 0.67:
                colors.append(theme.color_green)
            elif float(score) >= 0.45:
                colors.append(theme.color_orange)
            else:
                colors.append(theme.color_red)
        fig.add_bar(
            x=work["Punteggio"],
            y=work["Fattore"],
            orientation="h",
            marker_color=colors,
            text=[fmt_pct_it(v, 0) for v in work["Punteggio"]],
            textposition="outside",
            customdata=work[["Lettura"]],
            hovertemplate="<b>%{y}</b><br>Punteggio: %{x:.0%}<br>%{customdata[0]}<extra></extra>",
        )
    return finalize_chart(
        fig,
        "pianificazione_allocation",
        layout_updates={"showlegend": False},
        xaxis_updates={"range": [0, 1.05], "tickformat": ".0%"},
    )


def build_sator_decision_ranking_chart(ranking_df, theme):
    fig = go.Figure()
    if ranking_df is not None and not ranking_df.empty:
        work = ranking_df.copy().sort_values("score_finale", ascending=True)
        colors = []
        for score in work["score_finale"]:
            value = float(score or 0.0)
            if value >= 0.72:
                colors.append(theme.color_green)
            elif value >= 0.56:
                colors.append(theme.color_blue)
            elif value >= 0.42:
                colors.append(theme.color_orange)
            else:
                colors.append(theme.color_red)
        fig.add_bar(
            x=work["score_finale"],
            y=work["ticker"],
            orientation="h",
            marker_color=colors,
            text=[f"{float(v):.2f}" for v in work["score_finale"]],
            textposition="outside",
            customdata=work[["selection_reason"]],
            hovertemplate="<b>%{y}</b><br>Giudizio: %{x:.2f}<br>%{customdata[0]}<extra></extra>",
        )
    return finalize_chart(
        fig,
        "pianificazione_allocation",
        layout_updates={"showlegend": False},
        xaxis_updates={"range": [0, 1.05], "tickformat": ".2f"},
    )
