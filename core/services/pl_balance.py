"""Bilancia del P/L (TM-03): guadagni contro perdite, per strumento, delle posizioni aperte.

Funzione pura. Nessuna formula nuova: il P/L di ogni strumento è quello già calcolato nella tabella delle posizioni
(colonna «P/L €»); qui si dividono solo i positivi dai negativi e si ordinano dal più grande."""
from __future__ import annotations

from typing import Any

import pandas as pd


def _pl_column(table: pd.DataFrame) -> str | None:
    return next((c for c in table.columns if str(c).startswith("P/L") and "%" not in str(c) and "Realizz" not in str(c)), None)


def build_pl_balance(table: pd.DataFrame | None, *, eps: float = 0.005) -> dict[str, Any] | None:
    """{gains: [{ticker, eur}] dal maggiore, losses: [{ticker, eur}] dalla maggiore perdita, gain_total, loss_total, net}, o None."""
    if table is None or table.empty or "Ticker" not in table.columns:
        return None
    col = _pl_column(table)
    if col is None:
        return None
    pl = pd.to_numeric(table[col], errors="coerce")
    rows = [(str(t), float(v)) for t, v in zip(table["Ticker"], pl) if pd.notna(v)]
    gains = sorted(((t, v) for t, v in rows if v > eps), key=lambda r: -r[1])
    losses = sorted(((t, v) for t, v in rows if v < -eps), key=lambda r: r[1])
    if not gains and not losses:
        return None
    return {
        "gains": [{"ticker": t, "eur": v} for t, v in gains],
        "losses": [{"ticker": t, "eur": v} for t, v in losses],
        "gain_total": sum(v for _, v in gains),
        "loss_total": sum(v for _, v in losses),
        "net": sum(v for _, v in rows),
    }
