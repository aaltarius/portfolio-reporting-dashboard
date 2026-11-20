"""Calendario del P/L giornaliero (TM-07): una cella per giorno di Borsa, con la variazione di P/L dovuta al mercato.

Funzioni pure. La variazione del giorno è la somma, strumento per strumento, delle variazioni della colonna `PL_<ticker>`
(P/L non realizzato = quantità × prezzo − costo) fra due giorni consecutivi **in cui lo strumento è posseduto**: uno
strumento che entra o esce dal portafoglio non produce un salto finto (stessa regola del Termometro e di
`core.services.analysis.build_pl_delta_series`). Nessuna formula nuova."""
from __future__ import annotations

from typing import Any

import pandas as pd


def daily_market_change(dfh: pd.DataFrame | None) -> pd.Series:
    """Serie (indice = data) della variazione di P/L del giorno dovuta al mercato; vuota se non ci sono colonne `PL_`."""
    if dfh is None or dfh.empty or "Data" not in dfh.columns:
        return pd.Series(dtype=float)
    cols = [c for c in dfh.columns if str(c).startswith("PL_")]
    if not cols:
        return pd.Series(dtype=float)
    pl = dfh.set_index(pd.to_datetime(dfh["Data"], errors="coerce"))[cols].apply(pd.to_numeric, errors="coerce")
    pl = pl[~pl.index.isna()]
    step = pl.diff().where(pl.notna() & pl.shift().notna())
    return step.sum(axis=1, min_count=1).dropna()


def build_pl_calendar(dfh: pd.DataFrame | None, *, weeks: int = 13) -> dict[str, Any] | None:
    """{weeks: [lunedì AAAA-MM-GG], cells: [{day, week, weekday (0=lun), eur}], max_abs, total, up_days, down_days}; None senza dati."""
    daily = daily_market_change(dfh)
    daily = daily[[d.weekday() < 5 for d in daily.index]]
    if daily.empty:
        return None
    starts = sorted({d - pd.Timedelta(days=d.weekday()) for d in daily.index})[-max(1, int(weeks)):]
    first = starts[0]
    cells = [{"day": d.strftime("%Y-%m-%d"), "week": starts.index(d - pd.Timedelta(days=d.weekday())), "weekday": d.weekday(), "eur": float(v)}
             for d, v in daily.items() if d - pd.Timedelta(days=d.weekday()) >= first]
    if not cells:
        return None
    return {
        "weeks": [s.strftime("%Y-%m-%d") for s in starts],
        "cells": cells,
        "max_abs": max(abs(c["eur"]) for c in cells) or 1.0,
        "total": sum(c["eur"] for c in cells),
        "up_days": sum(1 for c in cells if c["eur"] > 0.005),
        "down_days": sum(1 for c in cells if c["eur"] < -0.005),
    }
