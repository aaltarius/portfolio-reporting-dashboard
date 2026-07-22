"""core/domain/risk.py — Calcoli rischio, drawdown, volatilità."""
from __future__ import annotations

from typing import Any
import numpy as np
import pandas as pd
from core.domain.returns import business_day_deltas


def build_drawdown_series(values: list[float]) -> list[float]:
    """
    Calculates maximum drawdown at each point in portfolio history.

    Args:
        values: List of portfolio rendimento percentuale (ad es [-2.97, -3.44, ..., +2.07])
                oppure valori assoluti (lista di numeri).
                Se i numeri sono piccoli (-10 a +10) si interpreta come percentuale decimale.

    Returns:
        List of drawdown percentages (sempre ≤ 0) at each point
    """
    if not values or len(values) == 0:
        return []

    s = pd.Series(values)
    s_clean = s.replace(0, np.nan)
    if s_clean.dropna().empty:
        return [0.0] * len(values)

    # Interpreta i valori come rendimenti percentuali decimali (-2.97 = -2,97%)
    # e converte in equity curve: eq = 1.0 + (r / 100)
    # Poi calcola drawdown normalizzato: (eq - eq_max) / eq_max
    equity_curve = 1.0 + (s / 100.0)
    eq_running_max = equity_curve.expanding().max()
    drawdown = ((equity_curve - eq_running_max) / eq_running_max) * 100

    return drawdown.fillna(0).tolist()


def rolling_volatility_annualized(index_series: pd.Series, window: int) -> pd.Series:
    """Volatilità annualizzata rolling da una serie di indice/NAV.

    window < 2: ritorna una serie vuota (nessun punto), stesso
    comportamento del branch "if window < 2: continue" nel chiamante
    originale — è compito del chiamante decidere se saltare la traccia.
    """
    if window < 2:
        return pd.Series(dtype=float, index=index_series.index)
    rets = index_series.pct_change().fillna(0)
    return rets.rolling(window).std() * np.sqrt(252)


def rolling_sharpe(index_series: pd.Series, window: int, clip: float = 5.0) -> pd.Series:
    """Sharpe rolling (rf=0) da una serie di indice/NAV, annualizzato,
    clippato a [-clip, +clip]."""
    rets = index_series.pct_change().fillna(0)
    roll_mean = rets.rolling(window).mean() * 252
    roll_std = rets.rolling(window).std() * np.sqrt(252)
    return (roll_mean / roll_std.replace(0, np.nan)).clip(-clip, clip)


def build_category_drawdown_series(dfh: pd.DataFrame, category: str, category_tickers: list[str], category_df: pd.DataFrame = None, first_op_date=None) -> list[float]:
    """Calcola il drawdown per una categoria dai rendimenti percentuali."""
    if dfh is None or dfh.empty or not category_tickers:
        return []

    # Filtra i dati da first_op_date se fornito
    dfh_work = dfh.copy()
    if first_op_date is not None:
        dates = pd.to_datetime(dfh_work.get("Data", []), errors="coerce")
        mask = dates >= pd.Timestamp(first_op_date)
        dfh_work = dfh_work[mask].copy()

    if dfh_work.empty:
        return []

    # Somma il P/L della categoria per ogni data
    pl_cols = [col for col in dfh_work.columns if col.startswith("PL_") and col[3:] in category_tickers]
    if not pl_cols:
        return []

    pl_series = pd.to_numeric(dfh_work[pl_cols].fillna(0).sum(axis=1), errors="coerce")

    # Calcola il costo totale della categoria (base per rendimento percentuale)
    category_cost = 0.0
    if category_df is not None and "Costo" in category_df.columns:
        category_cost = float(pd.to_numeric(category_df["Costo"], errors="coerce").fillna(0).sum())

    if category_cost <= 0:
        return []

    # Calcola i rendimenti percentuali: P/L / costo × 100
    pct_returns = (pl_series / category_cost) * 100

    # Calcola il drawdown dai rendimenti percentuali
    return build_drawdown_series(pct_returns.tolist())
