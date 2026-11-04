"""Compositi multi-asset basati su LIVELLI di veri indici.

Allineamento senza look-ahead, ffill solo dall'effettiva prima quotazione,
ribilanciamento all'inizio del mese sul valore di chiusura precedente.
"""
from __future__ import annotations
from datetime import date
from bisect import bisect_right
import math


def build_monthly_blend(components: list[tuple[dict[str,float],float]],
                        *,min_observations:int=10) -> dict[str,float]:
    components=[(s,float(w)) for s,w in components if s and float(w)>0]
    if not components:return {}
    total=sum(w for _,w in components)
    if total<=0:return {}
    weights=[w/total for _,w in components]
    start=max(min(s) for s,_ in components)
    end=min(max(s) for s,_ in components)
    dates=sorted({d for s,_ in components for d in s if start<=d<=end})
    last=[None]*len(components)
    last_day=[None]*len(components)
    rows=[]
    for day in dates:
        for i,(s,_) in enumerate(components):
            if day in s and math.isfinite(float(s[day])) and float(s[day])>0:
                last[i]=float(s[day]);last_day[i]=day
        if all(v is not None for v in last) and all(
            (date.fromisoformat(day)-date.fromisoformat(d)).days<=7
            for d in last_day if d is not None
        ): rows.append((day,list(last)))
    if len(rows)<min_observations:return {}
    base=rows[0][1]; holdings=[100*weights[i]/base[i] for i in range(len(weights))]
    out={rows[0][0]:100.0}
    month=rows[0][0][:7]
    rows_prev_day,prev_prices=rows[0]
    for day,prices in rows[1:]:
        if day[:7]!=month:
            prior_value=out[rows_prev_day]
            holdings=[prior_value*weights[i]/prev_prices[i] for i in range(len(weights))]
            month=day[:7]
        out[day]=sum(q*p for q,p in zip(holdings,prices))
        rows_prev_day=day
        prev_prices=prices
    return out


def in_eur(levels: dict[str,float], currency: str, fx_series:dict[str,float]) -> tuple[dict[str,float],str]:
    """Livelli in EUR, utilizzando il solo cambio passato al massimo 5 giorni.

    La convenzione dei ticker EURXXX=X e': 1 EUR = rate XXX.
    Non usare cambi futuri, ne' forward-fill indiscriminato su mesi interi.
    """
    if currency.upper() == 'EUR':return dict(levels),'EUR'
    if not fx_series:return {},f'{currency} (FX non disponibile)'
    fx_days=sorted(fx_series)
    output={}
    for day, level in sorted(levels.items()):
        idx=bisect_right(fx_days,day)-1
        if idx<0:continue
        last_day=fx_days[idx]
        if (date.fromisoformat(day)-date.fromisoformat(last_day)).days>5:continue
        rate=float(fx_series[last_day])
        if rate>0 and math.isfinite(rate) and math.isfinite(float(level)):
            output[day]=float(level)/rate
    return output, ('EUR' if output else f'{currency} (FX non disponibile)')
