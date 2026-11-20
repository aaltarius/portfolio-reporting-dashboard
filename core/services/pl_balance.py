"""Bilancia del P/L (TM-03): guadagni contro perdite, per strumento, delle posizioni aperte, oggi e il giorno prima.

Funzioni pure. Nessuna formula nuova: il P/L di ogni strumento è la colonna `PL_<ticker>` dello storico del portafoglio
(P/L non realizzato = quantità × prezzo − costo, la stessa del Termometro e delle candele); qui si dividono solo i positivi
dai negativi e si ordinano dal più grande. «Oggi» è l'ultima riga reale dello storico (come la tessera «Oggi» del
Termometro) e «Ieri» quella precedente."""
from __future__ import annotations

from typing import Any

import pandas as pd


def _day(row: pd.Series, date: Any, key: str, eps: float) -> dict[str, Any] | None:
    items = [(str(col)[3:], float(v)) for col, v in row.items() if str(col).startswith("PL_") and pd.notna(v)]
    gains = sorted(((t, v) for t, v in items if v > eps), key=lambda r: -r[1])
    losses = sorted(((t, v) for t, v in items if v < -eps), key=lambda r: r[1])
    if not gains and not losses:
        return None
    return {
        "key": key,
        "date": pd.Timestamp(date).strftime("%Y-%m-%d"),
        "gains": [{"ticker": t, "eur": v} for t, v in gains],
        "losses": [{"ticker": t, "eur": v} for t, v in losses],
        "gain_total": sum(v for _, v in gains),
        "loss_total": sum(v for _, v in losses),
        "net": sum(v for _, v in items),
    }


def build_pl_balance_days(work: pd.DataFrame | None, *, eps: float = 0.005) -> dict[str, Any] | None:
    """{days: [ieri, oggi]} (ieri solo se esiste e ha posizioni); ogni giorno ha gains, losses, gain_total, loss_total, net, date. None senza dati."""
    if work is None or work.empty or "Data" not in work.columns:
        return None
    work = work.reset_index(drop=True)
    last = len(work) - 1
    today = _day(work.iloc[last], work.iloc[last]["Data"], "today", eps)
    if today is None:
        return None
    days = []
    if last >= 1:
        yesterday = _day(work.iloc[last - 1], work.iloc[last - 1]["Data"], "yesterday", eps)
        if yesterday is not None:
            days.append(yesterday)
    days.append(today)
    return {"days": days}
