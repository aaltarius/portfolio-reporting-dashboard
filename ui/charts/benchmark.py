from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import numpy as np

from ui.charts.settings import apply_settings, get_chart_setting
from ui.theme import INSTRUMENT_PALETTE, P, macro_color


def build_portfolio_benchmark_comparison_chart(history:pd.DataFrame)->go.Figure:
    """Vista duale: ricchezza base 100 e vantaggio relativo composto.

    Mantiene il chart_id, la firma e il layer FigureCache esistenti. Nessuna
    richiesta dati aggiuntiva; il pannello inferiore e' lo stesso periodo
    comune del pannello superiore, non un secondo benchmark.
    """
    chart_id='cruscotti_benchmark_comparison'
    fig=make_subplots(rows=2,cols=1,shared_xaxes=True,
                      vertical_spacing=get_chart_setting(chart_id,'relative_panel_spacing',0.09),
                      row_heights=get_chart_setting(chart_id,'relative_panel_heights',[0.64,0.36]))
    if not isinstance(history,pd.DataFrame) or history.empty or 'date' not in history.columns:
        return apply_settings(fig,chart_id)
    d=history.copy()
    d['date']=pd.to_datetime(d['date'],errors='coerce')
    for col in ('portafoglio','benchmark'):
        d[col]=pd.to_numeric(d.get(col),errors='coerce')
    d=d.replace([np.inf,-np.inf],np.nan).dropna(subset=['date','portafoglio']).sort_values('date')
    if d.empty:return apply_settings(fig,chart_id)
    fig.add_trace(go.Scatter(x=d['date'],y=d['portafoglio'],mode='lines',name='Portafoglio',
        line=dict(color=P['blue'],width=get_chart_setting(chart_id,'comparison_portfolio_line_width',2.7)),
        hovertemplate='%{x|%d/%m/%Y}<br>Portafoglio base 100: %{y:.2f}<extra></extra>'),row=1,col=1)
    comparable=d.dropna(subset=['benchmark'])
    if len(comparable)>=2 and (comparable[['portafoglio','benchmark']]>0).all().all():
        fig.add_trace(go.Scatter(x=d['date'],y=d['benchmark'],mode='lines',name='Benchmark',
            line=dict(color=P['orange'],width=get_chart_setting(chart_id,'comparison_benchmark_line_width',2.5),dash='dash'),
            hovertemplate='%{x|%d/%m/%Y}<br>Benchmark base 100: %{y:.2f}<extra></extra>'),row=1,col=1)
        # La componente inferiore mostra un rapporto di crescita (P/P0)/(B/B0)-1,
        # non due cumulati semplicemente sottratti: entrambi partono da 0.
        p=comparable['portafoglio']/float(comparable['portafoglio'].iloc[0])
        bench=comparable['benchmark']/float(comparable['benchmark'].iloc[0])
        relative=(p/bench-1)*100
        for value,color,name,fill in (
            (np.where(relative>=0,relative,0),P['green'],'Vantaggio relativo',get_chart_setting(chart_id,'relative_positive_fill','rgba(34,197,94,0.20)')),
            (np.where(relative<=0,relative,0),P['red'],'Svantaggio relativo',get_chart_setting(chart_id,'relative_negative_fill','rgba(239,68,68,0.16)'))):
            fig.add_trace(go.Scatter(x=comparable['date'],y=value,mode='lines',name=name,
                line=dict(color=color,width=get_chart_setting(chart_id,'relative_line_width',1.8)),fill='tozeroy',fillcolor=fill,
                showlegend=False,hovertemplate='%{x|%d/%m/%Y}<br>Scarto composto: %{y:+.2f}%<extra></extra>'),
                row=2,col=1)
        fig.add_hline(y=0,line_dash='dot',line_width=1,line_color=get_chart_setting(chart_id,'relative_zero_line_color','rgba(100,116,139,0.72)'),row=2,col=1)
    fig.update_layout(hovermode='x unified')
    fig.update_yaxes(title_text='Base 100',zeroline=False,automargin=True,row=1,col=1)
    fig.update_yaxes(title_text='Vantaggio (%)',ticksuffix='%',zeroline=False,automargin=True,row=2,col=1)
    fig.update_xaxes(automargin=True,row=2,col=1)
    fig=apply_settings(fig,chart_id)
    # Nel layout multi-pannello l'asse 2 e' semanticamente DIVERSO: la cabina
    # globale assegna di default 'Indice base 100' a entrambi gli assi. Ristabilisci
    # qui soltanto l'unita' di misura (non un nuovo tema o stile grafico).
    fig.update_yaxes(title_text=get_chart_setting(chart_id,'secondary_y_title','Vantaggio relativo (%)'),ticksuffix='%',row=2,col=1)
    return fig


def build_instrument_benchmark_scatter(matrix: pd.DataFrame) -> go.Figure:
    """Scatter Compatibilità vs Extra-rendimento per strumenti/benchmark."""
    chart_id = "cruscotti_benchmark_instrument_scatter"
    fig = go.Figure()
    if matrix is None or matrix.empty:
        return apply_settings(fig, chart_id)
    df = matrix.copy()
    df["compatibility_score"] = pd.to_numeric(df.get("compatibility_score"), errors="coerce")
    df["extra_return"] = pd.to_numeric(df.get("extra_return"), errors="coerce")
    df["controvalore"] = pd.to_numeric(df.get("controvalore"), errors="coerce").fillna(0.0)
    df = df.dropna(subset=["compatibility_score", "extra_return"])
    if df.empty:
        return apply_settings(fig, chart_id)
    max_value = max(float(df["controvalore"].max()), 1.0)
    df["marker_size"] = 14.0 + (df["controvalore"].clip(lower=0.0) / max_value) * 24.0
    for cat, sub in df.groupby(df.get("categoria", pd.Series(["ALTRO"] * len(df))).fillna("ALTRO")):
        fig.add_trace(
            go.Scatter(
                x=sub["compatibility_score"],
                y=sub["extra_return"],
                mode="markers+text",
                text=sub["ticker"],
                textposition="top center",
                name=str(cat),
                marker=dict(
                    size=sub["marker_size"],
                    color=macro_color(str(cat)),
                    opacity=0.82,
                    line=dict(color="rgba(17,24,39,0.28)", width=1),
                ),
                customdata=sub[["benchmark_label", "compatibility_label", "correlation", "tracking_error", "controvalore"]].to_numpy(),
                hovertemplate=(
                    "<b>%{text}</b><br>"
                    "Benchmark: %{customdata[0]}<br>"
                    "Compatibilità: %{customdata[1]} (%{x:.0%})<br>"
                    "Extra-rendimento: %{y:+.2%}<br>"
                    "Correlazione: %{customdata[2]:.2f}<br>"
                    "Tracking error: %{customdata[3]:.2%}<br>"
                    "Controvalore: € %{customdata[4]:,.0f}<extra></extra>"
                ),
            )
        )
    fig.add_hline(y=0, line_dash="dash", line_color="rgba(100,116,139,0.55)", line_width=1)
    fig.add_vrect(x0=0.0, x1=0.40, fillcolor="rgba(239,68,68,0.04)", line_width=0)
    fig.add_vrect(x0=0.78, x1=1.0, fillcolor="rgba(34,197,94,0.04)", line_width=0)
    fig.update_layout(
        height=430,
        margin=dict(l=8, r=8, t=42, b=42),
        title="Compatibilità benchmark vs extra-rendimento",
        hovermode="closest",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    fig.update_xaxes(title_text="Compatibilità benchmark", tickformat=".0%", range=[-0.03, 1.03], automargin=True, zeroline=False)
    fig.update_yaxes(title_text="Extra-rendimento", tickformat="+.0%", automargin=True, zeroline=True)
    return apply_settings(fig, chart_id)
