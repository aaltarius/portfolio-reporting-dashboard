"""core/domain/returns.py — Calcoli rendimenti e statistiche."""
from __future__ import annotations

from typing import Any
import numpy as np
import pandas as pd

from core.series_utils import build_value_curve_frame


def business_day_deltas(index: Any) -> pd.Series:
    """Calculate business day deltas between dates."""
    idx = pd.DatetimeIndex(index)
    if len(idx) < 2:
        return pd.Series(dtype=float)
    deltas = []
    for prev, curr in zip(idx[:-1], idx[1:]):
        try:
            days = int(np.busday_count(prev.date(), curr.date()))
        except Exception:
            days = int((curr - prev).days)
        deltas.append(float(max(days, 1)))
    return pd.Series(deltas, index=idx[1:], dtype=float)


def build_analysis_returns(price_frame: pd.DataFrame, tickers: list[str]) -> pd.DataFrame:
    """Build normalized log returns for analysis."""
    returns = {}
    for tk in tickers:
        if tk not in price_frame.columns:
            continue
        p = pd.Series(price_frame[tk]).dropna().astype(float)
        p = p[p > 0]
        if len(p) < 3:
            continue
        log_returns = np.log(p / p.shift(1)).dropna()
        if log_returns.empty:
            continue
        gaps = business_day_deltas(p.index).reindex(log_returns.index).fillna(1.0).clip(lower=1.0)
        returns[tk] = log_returns / np.sqrt(gaps)
    return pd.DataFrame(returns).sort_index() if returns else pd.DataFrame()


def compute_instrument_stats(
    price_series: pd.Series,
    bench_series: pd.Series | None = None,
    start_date: "pd.Timestamp | None" = None,
) -> dict[str, Any] | None:
    """Compute comprehensive instrument statistics.

    start_date: se fornita, filtra la serie a >= start_date prima di ogni calcolo.
    Usare la data del primo acquisto per strumenti in portafoglio.
    """
    p = pd.Series(price_series).dropna().astype(float)
    p = p[p > 0]
    if start_date is not None:
        p = p.loc[p.index >= pd.Timestamp(start_date)]
    if len(p) < 3:
        return None
    first_date = pd.to_datetime(p.index[0])
    last_date = pd.to_datetime(p.index[-1])
    elapsed_days = max((last_date - first_date).days, 1)
    total_return = (p.iloc[-1] / p.iloc[0]) - 1 if p.iloc[0] > 0 else np.nan
    cagr = (p.iloc[-1] / p.iloc[0]) ** (365.25 / elapsed_days) - 1 if p.iloc[0] > 0 and elapsed_days > 0 else np.nan
    log_returns = np.log(p / p.shift(1)).dropna()
    gaps = business_day_deltas(p.index).reindex(log_returns.index).fillna(1.0).clip(lower=1.0)
    normalized_daily_log_returns = log_returns / np.sqrt(gaps)
    vol_ann = normalized_daily_log_returns.std(ddof=1) * np.sqrt(252) if len(normalized_daily_log_returns) > 1 else np.nan
    sharpe = cagr / vol_ann if pd.notna(cagr) and pd.notna(vol_ann) and vol_ann > 0 else np.nan
    dd = ((p / p.cummax()) - 1).min()

    # VaR 95% e CVaR 95%
    var_95 = np.nan
    cvar_95 = np.nan
    if len(normalized_daily_log_returns) >= 20:
        var_95 = float(np.percentile(normalized_daily_log_returns, 5))
        cvar_data = normalized_daily_log_returns[normalized_daily_log_returns <= var_95]
        cvar_95 = float(cvar_data.mean()) if len(cvar_data) > 0 else np.nan

    # Sortino Ratio (downside deviation)
    downside_dev = np.nan
    sortino = np.nan
    if len(normalized_daily_log_returns) >= 2:
        negative_returns = normalized_daily_log_returns[normalized_daily_log_returns < 0]
        if len(negative_returns) >= 2:
            downside_dev = float(negative_returns.std(ddof=1) * np.sqrt(252))
            if pd.notna(cagr) and downside_dev > 1e-9:
                sortino = float(cagr / downside_dev)

    # Calmar Ratio
    calmar = np.nan
    if pd.notna(cagr) and abs(dd) > 1e-9:
        calmar = float(cagr / abs(dd))

    # Beta vs benchmark
    beta = np.nan
    if bench_series is not None:
        b_series = pd.Series(bench_series).dropna().astype(float)
        b_aligned = b_series.reindex(p.index).dropna()
        p_aligned = p.reindex(b_aligned.index).dropna()
        if len(p_aligned) >= 10 and len(b_aligned) >= 10:
            r_instr = np.diff(np.log(p_aligned.values))
            r_bench = np.diff(np.log(b_aligned.values))
            if len(r_instr) >= 2 and np.var(r_bench) > 1e-12:
                beta = float(np.cov(r_instr, r_bench)[0, 1] / np.var(r_bench))

    return {
        "Osservazioni": int(len(p)),
        "Giorni coperti": int(elapsed_days),
        "Rend. Tot.": total_return,
        "CAGR": cagr,
        "Volatilità Ann.": vol_ann,
        "Sharpe (rf 0%)": sharpe,
        "Max Drawdown": dd,
        "VaR 95%": var_95,
        "CVaR 95%": cvar_95,
        "Sortino": sortino,
        "Calmar": calmar,
        "Beta": beta,
        "Downside Dev.": downside_dev,
    }


def _build_summary_return_curve(dfh: pd.DataFrame | None) -> pd.DataFrame:
    """
    Build cumulative return curve from history dataframe.

    Constructs a NAV/TWR proxy robust to external flows.

    Uses only columns already available in portfolio history:
    - Valore = portfolio value at date;
    - Capitale = cumulative net external capital.

    Daily return is estimated as:
        r_t = (Valore_t - External_Flow_t) / Valore_{t-1} - 1
    where External_Flow_t = Capitale_t - Capitale_{t-1}.
    """
    if dfh is None or dfh.empty:
        return pd.DataFrame(columns=["date_dt", "indice", "ret"])
    needed = {"Data", "Valore", "Capitale"}
    if not needed.issubset(set(dfh.columns)):
        return pd.DataFrame(columns=["date_dt", "indice", "ret"])

    curve = build_value_curve_frame(dfh, extra_columns={"capital": "Capitale"})
    if len(curve) < 2:
        return pd.DataFrame(columns=["date_dt", "indice", "ret"])

    curve["capital"] = curve["capital"].ffill().fillna(0.0)
    curve["external_flow"] = curve["capital"].diff().fillna(0.0)
    curve["prev_value"] = curve["value"].shift(1)
    curve["ret"] = np.where(
        curve["prev_value"].abs() > 1e-9,
        (curve["value"] - curve["external_flow"]) / curve["prev_value"] - 1.0,
        np.nan,
    )
    curve.loc[curve.index[0], "ret"] = 0.0
    curve["ret"] = pd.to_numeric(curve["ret"], errors="coerce").replace([np.inf, -np.inf], np.nan)
    curve["ret"] = curve["ret"].fillna(0.0).clip(lower=-0.95, upper=5.0)
    curve["indice"] = 100.0 * (1.0 + curve["ret"]).cumprod()
    return curve[["date_dt", "indice", "ret", "value", "capital", "external_flow"]]


def simple_period_return(first: float, last: float) -> float | None:
    """Rendimento semplice (last/first - 1) fra due valori di un indice/NAV.

    Ritorna None se first è 0/NaN/None (divisione non definita) — stesso
    guard già presente in core/services/benchmark.py::_series_return.
    """
    if first is None or last is None:
        return None
    try:
        first_f = float(first)
        last_f = float(last)
    except (TypeError, ValueError):
        return None
    if pd.isna(first_f) or pd.isna(last_f) or first_f == 0:
        return None
    return last_f / first_f - 1.0


def trailing_period_return(index_series: pd.Series, periods: int) -> pd.Series:
    """Rendimento trailing su una finestra di `periods` osservazioni di
    una serie di indice/NAV (non di rendimenti). Il punto i-esimo con
    i < periods_effettivi resta NaN (non c'è abbastanza storia)."""
    vals = index_series.values
    n = len(vals)
    if n == 0:
        return pd.Series(dtype=float, index=index_series.index)
    w = min(periods, max(n - 1, 0))
    out = [
        (vals[i] / vals[max(0, i - w)] - 1.0) if (i >= w and w > 0) else np.nan
        for i in range(n)
    ]
    return pd.Series(out, index=index_series.index)


def _period_returns_from_curve(curve: pd.DataFrame, freq: str) -> list[dict[str, Any]]:
    """Extract period returns from cumulative return curve."""
    if curve is None or curve.empty or "ret" not in curve.columns:
        return []
    work = curve.dropna(subset=["date_dt", "ret"]).copy()
    if work.empty:
        return []
    work["year"] = work["date_dt"].dt.year
    if freq == "Q":
        work["quarter"] = work["date_dt"].dt.quarter
        keys = ["year", "quarter"]
    else:
        work["month"] = work["date_dt"].dt.month
        keys = ["year", "month"]
    rows: list[dict[str, Any]] = []
    for group_key, grp in work.groupby(keys):
        vals = pd.to_numeric(grp["ret"], errors="coerce").dropna()
        if vals.empty:
            continue
        ret = float((1.0 + vals).prod() - 1.0)
        if freq == "Q":
            yr, quarter = group_key
            rows.append({"year": int(yr), "quarter": int(quarter), "ptf": ret})
        else:
            yr, month = group_key
            rows.append({"year": int(yr), "month": int(month), "ptf": ret})
    return rows
