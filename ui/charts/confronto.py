import plotly.graph_objects as go
import pandas as pd

from ui.charts.runtime import finalize_chart
from ui.formatting import fmt_eur_it, fmt_pct_it

# Ownership reale:
# - pagina: ui/pages/confronto.py
# - chart_id principale: confronto_snapshot

# Colore riga/colonna di riferimento "zero" in tutti i grafici di questo
# file (7 occorrenze prima della centralizzazione, tutte nello stesso
# file): non corrisponde a nessun colore gia' presente in core.config.COLORS
# o ui.theme, e' una costante puramente locale a questo modulo.
_ZERO_LINE_COLOR = "rgba(15,23,42,.35)"


def build_snapshot_comparison_time_chart(cmp_df, snap_a_label, snap_b_label, theme):
    """Build grouped allocation comparison chart for two snapshots.

    chart_id: confronto_snapshot
    chiamato da: ui/pages/confronto.py
    """
    fig = go.Figure()
    fig.add_bar(
        x=cmp_df["Categoria"],
        y=cmp_df["Peso A"],
        name=snap_a_label,
        text=[fmt_pct_it(v, 1) for v in cmp_df["Peso A"]],
        textposition="outside",
        marker_color=theme.color_blue,
        marker_line_color=theme.color_blue,
        marker_line_width=1.2,
    )
    fig.add_bar(
        x=cmp_df["Categoria"],
        y=cmp_df["Peso B"],
        name=snap_b_label,
        text=[fmt_pct_it(v, 1) for v in cmp_df["Peso B"]],
        textposition="outside",
        marker_color=theme.color_orange,
        marker_line_color=theme.color_orange,
        marker_line_width=1.2,
    )
    return finalize_chart(
        fig,
        "confronto_snapshot",
        layout_updates={"barmode": "group", "bargap": 0.22, "bargroupgap": 0.08},
    )


def build_snapshot_category_delta_chart(category_df, theme):
    """Build category value delta chart for selected snapshots."""
    fig = go.Figure()
    if category_df is not None and not category_df.empty:
        colors = [theme.color_green if float(v) >= 0 else theme.color_red for v in category_df["Delta valore"]]
        fig.add_bar(
            x=category_df["Categoria"],
            y=category_df["Delta valore"],
            marker_color=colors,
            text=[fmt_eur_it(v, 0, signed=True) for v in category_df["Delta valore"]],
            textposition="outside",
            hovertemplate="%{x}<br>Delta valore: %{y:,.2f}<extra></extra>",
            showlegend=False,
        )
    fig.add_hline(y=0, line_color=_ZERO_LINE_COLOR, line_width=1)
    return finalize_chart(
        fig,
        "confronto_category_delta",
        layout_updates={"bargap": 0.28},
        yaxis_updates={"tickformat": ",.0f"},
    )


def build_snapshot_contributors_chart(contributors_df, theme, limit=8):
    """Build top positive/negative contributors chart."""
    fig = go.Figure()
    if contributors_df is not None and not contributors_df.empty:
        work = contributors_df.copy()
        top = work.head(max(1, int(limit / 2)))
        bottom = work.tail(max(1, int(limit / 2)))
        chart_df = (
            pd.concat([top, bottom], ignore_index=True)
            .drop_duplicates(subset=["Ticker"], keep="first")
            .sort_values("Delta valore", ascending=True)
        )
        colors = [theme.color_green if float(v) >= 0 else theme.color_red for v in chart_df["Delta valore"]]
        fig.add_bar(
            y=chart_df["Ticker"],
            x=chart_df["Delta valore"],
            orientation="h",
            marker_color=colors,
            text=[fmt_eur_it(v, 0, signed=True) for v in chart_df["Delta valore"]],
            textposition="outside",
            hovertemplate="%{y}<br>Delta valore: %{x:,.2f}<extra></extra>",
            showlegend=False,
        )
    fig.add_vline(x=0, line_color=_ZERO_LINE_COLOR, line_width=1)
    return finalize_chart(
        fig,
        "confronto_contributors",
        layout_updates={"bargap": 0.22},
        xaxis_updates={"tickformat": ",.0f"},
    )


def build_snapshot_metric_timeline_chart(metrics_timeline_df, metric_col, chart_id, theme):
    """Build timeline chart for a selected portfolio metric across 2-3 snapshots."""
    fig = go.Figure()
    if metrics_timeline_df is not None and not metrics_timeline_df.empty and metric_col in metrics_timeline_df.columns:
        y_values = metrics_timeline_df[metric_col]
        is_pct = metric_col == "Rendimento"
        fig.add_trace(
            go.Scatter(
                x=metrics_timeline_df["Snapshot"],
                y=y_values,
                mode="lines+markers+text",
                line=dict(color=theme.color_blue, width=3),
                marker=dict(size=9, color=theme.color_blue),
                text=[fmt_pct_it(v, 1, signed=True) if is_pct else fmt_eur_it(v, 0, signed=(metric_col == "P/L")) for v in y_values],
                textposition="top center",
                hovertemplate="%{x}<br>%{y:,.2f}<extra></extra>" if not is_pct else "%{x}<br>%{y:.2%}<extra></extra>",
                showlegend=False,
            )
        )
    y_updates = {"tickformat": ".0%"} if metric_col == "Rendimento" else {"tickformat": ",.0f"}
    return finalize_chart(fig, chart_id, hovermode="x unified", yaxis_updates=y_updates)


def build_snapshot_category_timeline_chart(category_timeline_df, value_col, chart_id, theme):
    """Build multi-snapshot category timeline for value or weight."""
    fig = go.Figure()
    if category_timeline_df is not None and not category_timeline_df.empty:
        for cat, group in category_timeline_df.groupby("Categoria"):
            fig.add_trace(
                go.Scatter(
                    x=group["Snapshot"],
                    y=group[value_col],
                    mode="lines+markers+text",
                    name=str(cat),
                    text=[fmt_pct_it(v, 1) if value_col == "Peso" else fmt_eur_it(v, 0) for v in group[value_col]],
                    textposition="top center",
                    hovertemplate="%{x}<br>%{y:.2%}<extra></extra>" if value_col == "Peso" else "%{x}<br>%{y:,.2f}<extra></extra>",
                )
            )
    y_updates = {"tickformat": ".0%"} if value_col == "Peso" else {"tickformat": ",.0f"}
    return finalize_chart(fig, chart_id, hovermode="x unified", yaxis_updates=y_updates)


def build_snapshot_pl_delta_chart(holdings_df, theme, limit=10):
    """Build top holding delta P/L chart."""
    fig = go.Figure()
    if holdings_df is not None and not holdings_df.empty:
        work = holdings_df.copy()
        work["Delta P/L"] = pd.to_numeric(work.get("Delta P/L"), errors="coerce").fillna(0.0)
        work = work.loc[work["Delta P/L"].abs() > 1e-9].sort_values("Delta P/L", ascending=False)
        if work.empty:
            fig.add_annotation(
                text="P/L per strumento non disponibile negli snapshot selezionati.",
                x=0.5,
                y=0.5,
                xref="paper",
                yref="paper",
                showarrow=False,
                font=dict(color=theme.muted_color, size=13),
            )
            return finalize_chart(fig, "confronto_pl_delta")
        top = work.head(max(1, int(limit / 2)))
        bottom = work.tail(max(1, int(limit / 2)))
        chart_df = pd.concat([top, bottom], ignore_index=True).drop_duplicates(subset=["Ticker"], keep="first").sort_values("Delta P/L", ascending=True)
        colors = [theme.color_green if float(v) >= 0 else theme.color_red for v in chart_df["Delta P/L"]]
        fig.add_bar(
            y=chart_df["Ticker"],
            x=chart_df["Delta P/L"],
            orientation="h",
            marker_color=colors,
            text=[fmt_eur_it(v, 0, signed=True) for v in chart_df["Delta P/L"]],
            textposition="outside",
            hovertemplate="%{y}<br>Delta P/L: %{x:,.2f}<extra></extra>",
            showlegend=False,
        )
    fig.add_vline(x=0, line_color=_ZERO_LINE_COLOR, line_width=1)
    return finalize_chart(
        fig,
        "confronto_pl_delta",
        layout_updates={"bargap": 0.22},
        xaxis_updates={"tickformat": ",.0f"},
    )


def build_multi_snapshot_category_grouped_chart(category_timeline_df, value_col, chart_id, theme):
    """Grouped bars by category across selected snapshots."""
    fig = go.Figure()
    if category_timeline_df is not None and not category_timeline_df.empty:
        snapshot_order = list(dict.fromkeys(category_timeline_df["Snapshot"].tolist()))
        for idx, snap_name in enumerate(snapshot_order):
            group = category_timeline_df[category_timeline_df["Snapshot"] == snap_name].copy()
            fig.add_bar(
                x=group["Categoria"],
                y=group[value_col],
                name=str(snap_name),
                text=[fmt_pct_it(v, 1) if value_col == "Peso" else fmt_eur_it(v, 0) for v in group[value_col]],
                textposition="outside",
            )
    y_updates = {"tickformat": ".0%"} if value_col == "Peso" else {"tickformat": ",.0f"}
    return finalize_chart(
        fig,
        chart_id,
        layout_updates={"barmode": "group", "bargap": 0.22, "bargroupgap": 0.08},
        yaxis_updates=y_updates,
    )


def build_multi_snapshot_holdings_grouped_chart(holdings_wide_df, metric_prefix, chart_id, theme, limit=7):
    """Grouped bars by instrument across selected snapshots for value or P/L."""
    fig = go.Figure()
    if holdings_wide_df is None or holdings_wide_df.empty:
        fig.add_annotation(
            text="Nessun dettaglio strumenti disponibile.",
            x=0.5,
            y=0.5,
            xref="paper",
            yref="paper",
            showarrow=False,
            font=dict(color=theme.muted_color, size=13),
        )
        return finalize_chart(fig, chart_id)

    delta_col = "Delta valore complessivo" if metric_prefix == "Valore" else "Delta P/L complessivo"
    working = holdings_wide_df.copy()
    if delta_col in working.columns:
        working[delta_col] = pd.to_numeric(working[delta_col], errors="coerce").fillna(0.0)
        working = working.sort_values(delta_col, ascending=False)
        top = working.head(max(1, int(limit / 2)))
        bottom = working.tail(max(1, int(limit / 2)))
        chart_df = pd.concat([top, bottom], ignore_index=True).drop_duplicates(subset=["Ticker"], keep="first")
    else:
        chart_df = working.head(limit).copy()

    metric_cols = [col for col in chart_df.columns if col.startswith(f"{metric_prefix} ")]
    if not metric_cols:
        fig.add_annotation(
            text="Dati non disponibili per il confronto strumenti selezionato.",
            x=0.5,
            y=0.5,
            xref="paper",
            yref="paper",
            showarrow=False,
            font=dict(color=theme.muted_color, size=13),
        )
        return finalize_chart(fig, chart_id)
    for metric_col in metric_cols:
        snap_name = metric_col[len(metric_prefix) + 1 :]
        y_values = pd.to_numeric(chart_df.get(metric_col), errors="coerce").fillna(0.0)
        fig.add_bar(
            x=chart_df["Ticker"],
            y=y_values,
            name=snap_name,
            text=[fmt_eur_it(v, 0, signed=(metric_prefix == "P/L")) for v in y_values],
            textposition="outside",
            cliponaxis=False,
        )
    if metric_prefix == "P/L":
        fig.add_hline(y=0, line_color=_ZERO_LINE_COLOR, line_width=1)
    return finalize_chart(
        fig,
        chart_id,
        layout_updates={"barmode": "group", "bargap": 0.22, "bargroupgap": 0.08, "height": 440},
        yaxis_updates={"tickformat": ",.0f"},
    )


def build_snapshot_value_decomposition_chart(holdings_df, theme, limit=8):
    """Explain Delta valore as change in invested capital plus change in P/L."""
    fig = go.Figure()
    if holdings_df is None or holdings_df.empty:
        return finalize_chart(fig, "confronto_value_decomposition")
    work = holdings_df.copy()
    for col in ("Delta costo", "Delta P/L", "Delta valore"):
        work[col] = pd.to_numeric(work.get(col), errors="coerce").fillna(0.0)
    work = work.loc[(work["Delta costo"].abs() + work["Delta P/L"].abs()) > 1e-9]
    if work.empty:
        fig.add_annotation(
            text="Nessuna variazione rilevante tra costo investito e P/L.",
            x=0.5,
            y=0.5,
            xref="paper",
            yref="paper",
            showarrow=False,
            font=dict(color=theme.muted_color, size=13),
        )
        return finalize_chart(fig, "confronto_value_decomposition")
    work["_impact"] = work["Delta costo"].abs() + work["Delta P/L"].abs()
    chart_df = work.sort_values("_impact", ascending=False).head(limit).sort_values("Delta valore", ascending=False)
    fig.add_bar(
        x=chart_df["Ticker"],
        y=chart_df["Delta costo"],
        name="Delta costo",
        marker_color=[theme.color_blue if float(v) >= 0 else theme.color_red for v in chart_df["Delta costo"]],
        text=[fmt_eur_it(v, 0, signed=True) for v in chart_df["Delta costo"]],
        textposition="outside",
        cliponaxis=False,
        hovertemplate="%{x}<br>Delta costo: %{y:,.2f}<extra></extra>",
    )
    fig.add_bar(
        x=chart_df["Ticker"],
        y=chart_df["Delta P/L"],
        name="Delta P/L",
        marker_color=[theme.color_green if float(v) >= 0 else theme.color_red for v in chart_df["Delta P/L"]],
        text=[fmt_eur_it(v, 0, signed=True) for v in chart_df["Delta P/L"]],
        textposition="outside",
        cliponaxis=False,
        hovertemplate="%{x}<br>Delta P/L: %{y:,.2f}<extra></extra>",
    )
    fig.add_hline(y=0, line_color=_ZERO_LINE_COLOR, line_width=1)
    return finalize_chart(
        fig,
        "confronto_value_decomposition",
        layout_updates={
            "barmode": "group",
            "bargap": 0.22,
            "bargroupgap": 0.08,
            "height": 440,
            "title": {"text": "<b>Delta valore: capitale investito vs P/L</b>"},
        },
        xaxis_updates={"type": "category"},
        yaxis_updates={"tickformat": ",.0f"},
    )


def build_snapshot_return_delta_chart(holdings_df, theme, limit=10):
    """Show how holding return changed between snapshots."""
    fig = go.Figure()
    if holdings_df is None or holdings_df.empty:
        return finalize_chart(fig, "confronto_return_delta")
    work = holdings_df.copy()
    work["Delta rendimento"] = pd.to_numeric(work.get("Delta rendimento"), errors="coerce").fillna(0.0)
    work = work.loc[work["Delta rendimento"].abs() > 1e-9]
    if work.empty:
        fig.add_annotation(
            text="Variazione rendimento per strumento non disponibile.",
            x=0.5,
            y=0.5,
            xref="paper",
            yref="paper",
            showarrow=False,
            font=dict(color=theme.muted_color, size=13),
        )
        return finalize_chart(fig, "confronto_return_delta")
    top = work.sort_values("Delta rendimento", ascending=False).head(max(1, int(limit / 2)))
    bottom = work.sort_values("Delta rendimento", ascending=True).head(max(1, int(limit / 2)))
    chart_df = pd.concat([top, bottom], ignore_index=True).drop_duplicates(subset=["Ticker"], keep="first").sort_values("Delta rendimento", ascending=True)
    colors = [theme.color_green if float(v) >= 0 else theme.color_red for v in chart_df["Delta rendimento"]]
    fig.add_bar(
        y=chart_df["Ticker"],
        x=chart_df["Delta rendimento"],
        orientation="h",
        marker_color=colors,
        text=[fmt_pct_it(v, 2, signed=True) for v in chart_df["Delta rendimento"]],
        textposition="outside",
        hovertemplate="%{y}<br>Delta rendimento: %{x:.2%}<extra></extra>",
        showlegend=False,
    )
    fig.add_vline(x=0, line_color=_ZERO_LINE_COLOR, line_width=1)
    return finalize_chart(
        fig,
        "confronto_return_delta",
        layout_updates={"bargap": 0.22},
        xaxis_updates={"tickformat": ".0%"},
    )


def build_multi_snapshot_delta_bar_chart(
    holdings_wide_df,
    metric_col,
    chart_id,
    theme,
    *,
    title=None,
    limit=10,
    percent=False,
):
    """Overall A->last delta chart for 3-snapshot comparisons."""
    fig = go.Figure()
    if holdings_wide_df is None or holdings_wide_df.empty or metric_col not in holdings_wide_df.columns:
        fig.add_annotation(
            text="Dati non disponibili per il confronto selezionato.",
            x=0.5,
            y=0.5,
            xref="paper",
            yref="paper",
            showarrow=False,
            font=dict(color=theme.muted_color, size=13),
        )
        return finalize_chart(fig, chart_id)

    work = holdings_wide_df.copy()
    work[metric_col] = pd.to_numeric(work.get(metric_col), errors="coerce").fillna(0.0)
    work = work.loc[work[metric_col].abs() > 1e-9]
    if work.empty:
        fig.add_annotation(
            text="Nessuna variazione rilevante disponibile.",
            x=0.5,
            y=0.5,
            xref="paper",
            yref="paper",
            showarrow=False,
            font=dict(color=theme.muted_color, size=13),
        )
        return finalize_chart(fig, chart_id)

    top = work.sort_values(metric_col, ascending=False).head(max(1, int(limit / 2)))
    bottom = work.sort_values(metric_col, ascending=True).head(max(1, int(limit / 2)))
    chart_df = pd.concat([top, bottom], ignore_index=True).drop_duplicates(subset=["Ticker"], keep="first").sort_values(metric_col, ascending=True)
    colors = [theme.color_green if float(v) >= 0 else theme.color_red for v in chart_df[metric_col]]
    text_fmt = (lambda v: fmt_pct_it(v, 2, signed=True)) if percent else (lambda v: fmt_eur_it(v, 0, signed=True))
    hover = "%{y}<br>%{x:.2%}<extra></extra>" if percent else "%{y}<br>%{x:,.2f}<extra></extra>"
    fig.add_bar(
        y=chart_df["Ticker"],
        x=chart_df[metric_col],
        orientation="h",
        marker_color=colors,
        text=[text_fmt(v) for v in chart_df[metric_col]],
        textposition="outside",
        cliponaxis=False,
        hovertemplate=hover,
        showlegend=False,
    )
    fig.add_vline(x=0, line_color=_ZERO_LINE_COLOR, line_width=1)
    layout_updates = {"bargap": 0.22}
    if title:
        layout_updates["title"] = {"text": title}
    return finalize_chart(
        fig,
        chart_id,
        layout_updates=layout_updates,
        xaxis_updates={"tickformat": ".0%" if percent else ",.0f"},
    )
