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


def build_simple_returns(price_frame: pd.DataFrame, tickers: list[str]) -> pd.DataFrame:
    """Rendimenti semplici giorno-per-giorno, per comporre un percorso di valore.

    A differenza di build_analysis_returns (log-rendimenti normalizzati per
    la radice del gap tra osservazioni, un trucco di annualizzazione), qui
    il rendimento resta quello effettivamente realizzato in ciascun giorno
    di storico disponibile — l'unico adatto a un bootstrap che deve comporre
    un percorso di valore (Monte Carlo, core/services/portfolio_simulation.py).
    """
    returns = {}
    for tk in tickers:
        if tk not in price_frame.columns:
            continue
        p = pd.Series(price_frame[tk]).dropna().astype(float)
        p = p[p > 0]
        if len(p) < 3:
            continue
        simple = p.pct_change().dropna()
        if simple.empty:
            continue
        returns[tk] = simple
    return pd.DataFrame(returns).sort_index() if returns else pd.DataFrame()


def combine_weighted_returns(returns_df: pd.DataFrame, weights: pd.Series) -> pd.Series:
    """Combina i rendimenti multi-strumento in un'unica serie di portafoglio.

    I pesi vengono rinormalizzati a somma 1 sugli strumenti effettivamente
    presenti in returns_df con peso positivo; un giorno senza rendimento per
    uno strumento conta zero per quel giorno (fillna, non drop: evita di
    perdere l'intera riga per un solo strumento mancante).

    Definizione canonica unica: usata sia da SATOR
    (core/services/sator.py::_build_portfolio_return_series) sia dal Monte
    Carlo del portafoglio — non duplicare questa formula altrove.
    """
    if returns_df is None or returns_df.empty or weights is None or weights.empty:
        return pd.Series(dtype=float)
    cols = [t for t in weights.index if t in returns_df.columns and weights[t] > 0]
    if not cols:
        return pd.Series(dtype=float)
    total = float(weights[cols].sum())
    if total <= 0:
        return pd.Series(dtype=float)
    w = weights[cols] / total
    return returns_df[cols].fillna(0.0).mul(w, axis=1).sum(axis=1)


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


def _empty_return_curve_metrics() -> dict[str, float | None]:
    return {
        "twr": None,
        "cagr": None,
        "cagr_real": None,
        "volatility_ann": None,
        "max_drawdown": None,
        "benchmark_return": None,
        "excess_vs_benchmark": None,
        "sortino": None,
        "calmar": None,
        "information_ratio": None,
        "tracking_error": None,
    }


def _coerce_curve_frame(curve: pd.DataFrame | None) -> pd.DataFrame:
    if curve is None or curve.empty:
        return pd.DataFrame(columns=["date_dt", "indice"])
    work = curve.copy()
    if "date_dt" not in work.columns or "indice" not in work.columns:
        return pd.DataFrame(columns=["date_dt", "indice"])
    work["date_dt"] = pd.to_datetime(work["date_dt"], errors="coerce")
    work["indice"] = pd.to_numeric(work["indice"], errors="coerce")
    if "ret" in work.columns:
        work["ret"] = pd.to_numeric(work["ret"], errors="coerce")
    return work.dropna(subset=["date_dt", "indice"]).sort_values("date_dt").reset_index(drop=True)


def _coerce_benchmark_series(benchmark_curve: pd.DataFrame | pd.Series | None) -> pd.Series:
    if benchmark_curve is None:
        return pd.Series(dtype=float)
    if isinstance(benchmark_curve, pd.Series):
        series = pd.to_numeric(benchmark_curve, errors="coerce")
        series.index = pd.to_datetime(series.index, errors="coerce")
        return series.dropna().sort_index()
    if isinstance(benchmark_curve, pd.DataFrame):
        bench = _coerce_curve_frame(benchmark_curve)
        if bench.empty:
            return pd.Series(dtype=float)
        return pd.Series(bench["indice"].values, index=bench["date_dt"]).dropna().sort_index()
    return pd.Series(dtype=float)


def compute_return_curve_metrics(
    curve: pd.DataFrame | None,
    *,
    benchmark_curve: pd.DataFrame | pd.Series | None = None,
    inflation_rate: float | None = None,
    max_accepted_benchmark_return: float | None = 0.50,
) -> dict[str, float | None]:
    """Metriche canoniche da una curva indice/NAV flow-adjusted.

    Usata sia dal payload Summary sia dal report filtrato, cosi' TWR, CAGR,
    drawdown e ratio restano coerenti tra dashboard ed export.
    """
    metrics = _empty_return_curve_metrics()
    work = _coerce_curve_frame(curve)
    if len(work) < 2:
        return metrics

    idx = pd.Series(work["indice"].values, index=work["date_dt"]).dropna()
    if len(idx) < 2 or not np.isfinite(float(idx.iloc[0])) or float(idx.iloc[0]) <= 0:
        return metrics

    twr = float(idx.iloc[-1] / idx.iloc[0] - 1.0)
    elapsed_days = max(int((idx.index[-1] - idx.index[0]).days), 1)
    cagr = float((1.0 + twr) ** (365.25 / elapsed_days) - 1.0) if twr > -1.0 else None
    try:
        inflation = float(inflation_rate or 0.0)
    except Exception:
        inflation = 0.0
    cagr_real = (
        float((1.0 + cagr) / (1.0 + inflation) - 1.0)
        if cagr is not None and inflation and abs(1.0 + inflation) > 1e-12
        else None
    )

    if "ret" in work.columns:
        ret_series = pd.Series(work["ret"].values, index=work["date_dt"])
        actual_returns = pd.to_numeric(ret_series.iloc[1:], errors="coerce").dropna()
    else:
        actual_returns = idx.pct_change().dropna()

    volatility_ann = float(actual_returns.std(ddof=1) * np.sqrt(252)) if len(actual_returns) >= 2 else None
    running_max = idx.cummax()
    max_drawdown = float((idx / running_max - 1.0).min()) if len(idx) >= 2 else None

    sortino = None
    calmar = None
    if len(actual_returns) >= 4:
        negative_returns = actual_returns[actual_returns < 0]
        if len(negative_returns) >= 2 and cagr is not None:
            downside = float(np.sqrt((negative_returns ** 2).mean()) * np.sqrt(252))
            sortino = float(cagr / downside) if downside > 1e-9 else None
    if cagr is not None and max_drawdown is not None and abs(max_drawdown) > 1e-9:
        calmar = float(cagr / abs(max_drawdown))

    benchmark_return = None
    excess_vs_benchmark = None
    tracking_error = None
    information_ratio = None
    benchmark_series = _coerce_benchmark_series(benchmark_curve)
    if not benchmark_series.empty and len(benchmark_series) >= 2 and float(benchmark_series.iloc[0]) > 0:
        benchmark_return = float(benchmark_series.iloc[-1] / benchmark_series.iloc[0] - 1.0)
        if max_accepted_benchmark_return is not None and benchmark_return > float(max_accepted_benchmark_return):
            benchmark_return = None
            benchmark_series = pd.Series(dtype=float)
        elif twr is not None:
            excess_vs_benchmark = float(twr - benchmark_return)
    if not benchmark_series.empty:
        aligned_benchmark = benchmark_series.reindex(idx.index).ffill().bfill()
        benchmark_returns = aligned_benchmark.pct_change().dropna()
        min_len = min(len(actual_returns), len(benchmark_returns))
        if min_len >= 4:
            excess_returns = actual_returns.iloc[-min_len:].values - benchmark_returns.iloc[-min_len:].values
            te = float(np.std(excess_returns, ddof=1) * np.sqrt(252))
            tracking_error = te if te > 1e-9 else None
            if tracking_error:
                information_ratio = float(np.mean(excess_returns) * 252 / tracking_error)

    metrics.update({
        "twr": twr,
        "cagr": cagr,
        "cagr_real": cagr_real,
        "volatility_ann": volatility_ann,
        "max_drawdown": max_drawdown,
        "benchmark_return": benchmark_return,
        "excess_vs_benchmark": excess_vs_benchmark,
        "sortino": sortino,
        "calmar": calmar,
        "information_ratio": information_ratio,
        "tracking_error": tracking_error,
    })
    return metrics
