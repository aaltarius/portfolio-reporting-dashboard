"""Grafici diagnostici Benchmark: stessi payload e stessa cabina centrale Chart Settings.

Nessuna chiamata a rete, ai file o a SQLite. Solo trasformazioni di curve gia'
materializzate nell'analisi congelata. Le mappe non interpretano la correlazione
come una certificazione finanziaria.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from ui.charts.settings import apply_settings, get_chart_setting
from ui.theme import P


def _paired(history: pd.DataFrame | None) -> pd.DataFrame:
    if not isinstance(history,pd.DataFrame) or history.empty or not {'date','portafoglio','benchmark'}.issubset(history.columns):
        return pd.DataFrame(columns=['date','portafoglio','benchmark'])
    d=history[['date','portafoglio','benchmark']].copy()
    d['date']=pd.to_datetime(d['date'],errors='coerce')
    for c in ('portafoglio','benchmark'):
        d[c]=pd.to_numeric(d[c],errors='coerce')
    d=d.replace([np.inf,-np.inf],np.nan).dropna().drop_duplicates('date',keep='last').sort_values('date')
    return d[(d['portafoglio']>0)&(d['benchmark']>0)]


def build_monthly_advantage_chart(history:pd.DataFrame|None,months:int=18)->go.Figure:
    """Scarto tra rendimenti mensili, in punti percentuali, per mesi osservati.

    Mesi senza entrambe le osservazioni non vengono inventati. Il primo mese
    della finestra viene ricavato usando il precedente ultimo dato disponibile.
    """
    chart_id='cruscotti_benchmark_monthly_advantage'
    fig=go.Figure()
    d=_paired(history)
    if len(d)<3:return apply_settings(fig,chart_id)
    m=d.set_index('date')[['portafoglio','benchmark']].resample('ME').last().dropna()
    changes=m.pct_change(fill_method=None).dropna()
    if changes.empty:return apply_settings(fig,chart_id)
    months = int(get_chart_setting(chart_id,'monthly_visible_months',months))
    changes=changes.iloc[-max(1,months):]
    delta=(changes['portafoglio']-changes['benchmark'])*100
    labels=[dt.strftime('%m/%Y') for dt in delta.index]
    colors=[P['green'] if x>=0 else P['red'] for x in delta]
    fig.add_trace(go.Bar(x=labels,y=delta.to_numpy(),marker_color=colors,
        customdata=np.column_stack((changes['portafoglio']*100,changes['benchmark']*100)),
        hovertemplate='<b>%{x}</b><br>Scarto mensile %{y:+.2f} pp<br>'
                      'Portafoglio %{customdata[0]:+.2f}%<br>Benchmark %{customdata[1]:+.2f}%<extra></extra>',
        name='Scarto mensile'))
    fig.add_hline(y=0,line_color=get_chart_setting(chart_id,'monthly_zero_line_color','rgba(100,116,139,0.66)'),line_width=1)
    fig.update_layout(bargap=get_chart_setting(chart_id,'monthly_bargap',0.27))
    fig.update_yaxes(title_text='Differenza mensile (pp)',ticksuffix=' pp',zeroline=False,automargin=True)
    fig.update_xaxes(automargin=True)
    return apply_settings(fig,chart_id)


