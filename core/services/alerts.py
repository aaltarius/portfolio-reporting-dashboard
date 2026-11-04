"""
core/services/alerts.py — Portfolio alerts services.

Functions for building portfolio alert lists based on configured thresholds.
Pure functions - no Streamlit dependencies, no side effects.
"""
from typing import Any
import math
import numpy as np
import pandas as pd


def _finite_float(value: Any, default: float = 0.0) -> float:
    try:
        raw = default if value is None or (isinstance(value, str) and value.strip() == "") else value
        result = float(raw)
    except Exception:
        return default
    return result if math.isfinite(result) else default


def _finite_series(values: Any, default: float = 0.0) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    if not isinstance(numeric, pd.Series):
        numeric = pd.Series(numeric)
    return numeric.map(lambda value: _finite_float(value, default))


def build_portfolio_alerts(
    da_frame: pd.DataFrame,
    settings: dict[str, Any] | None,
    risk_df: pd.DataFrame | None = None,
    dfstats: pd.DataFrame | None = None,
) -> list[dict[str, Any]]:
    """
    Valuta gli alert configurati sul portafoglio.

    Restituisce una lista ordinata di alert con severita', messaggio, ticker e soglia.
    """
    alerts_settings = (settings or {}).get("alerts", {}) if isinstance(settings, dict) else {}
    if not bool(alerts_settings.get("enabled", False)):
        return []
    if da_frame is None or da_frame.empty:
        return []

    work = da_frame.copy()
    work["Controvalore"] = _finite_series(work.get("Controvalore"))
    work["Costo"] = _finite_series(work.get("Costo"))
    work["P/L €"] = _finite_series(work.get("P/L €"))
    total_value = _finite_float(work["Controvalore"].sum())
    if total_value <= 0:
        return []

    work["Peso %"] = work["Controvalore"] / total_value
    denom = work["Costo"].abs().replace(0, np.nan)
    computed_pl_pct = (work["P/L €"] / denom).map(lambda value: _finite_float(value, np.nan))
    if "P/L %" in work.columns:
        work["P/L %"] = _finite_series(work["P/L %"], default=np.nan)
        work["P/L %"] = work["P/L %"].where(work["P/L %"].notna(), computed_pl_pct)
    else:
        work["P/L %"] = computed_pl_pct

    concentration_threshold = alerts_settings.get("concentration_threshold_pct")
    loss_threshold = alerts_settings.get("loss_threshold_pct")
    drawdown_threshold = alerts_settings.get("drawdown_threshold_pct")
    volatility_threshold = alerts_settings.get("volatility_threshold_pct")
    calculations = (settings or {}).get("calculations_metrics", {}) if isinstance(settings, dict) else {}
    risk_thresholds = calculations.get("risk_traffic_light_thresholds", {}) if isinstance(calculations, dict) else {}
    green_max = _finite_float(risk_thresholds.get("green_max", 1.0), 1.0)
    yellow_max = _finite_float(risk_thresholds.get("yellow_max", 1.2), 1.2)

    severity_rank = {"high": 3, "medium": 2, "low": 1}
    items: list[dict[str, Any]] = []

    if concentration_threshold is not None:
        concentration_threshold = _finite_float(concentration_threshold, default=np.nan)
        threshold_ratio = concentration_threshold / 100.0
        if not np.isfinite(threshold_ratio) or threshold_ratio <= 0:
            concentration_threshold = None
    if concentration_threshold is not None:
        for _, row in work.iterrows():
            weight = _finite_float(row.get("Peso %", 0.0))
            if weight < threshold_ratio:
                continue
            severity = "high" if weight >= threshold_ratio * 1.25 else "medium"
            ticker = str(row.get("Ticker") or "n/d")
            items.append({
                "kind": "concentration",
                "severity": severity,
                "severity_rank": severity_rank[severity],
                "ticker": ticker,
                "title": f"Concentrazione elevata su {ticker}",
                "message": f"{ticker} pesa {weight * 100.0:.1f}% del portafoglio, oltre la soglia del {concentration_threshold:.1f}%.",
                "value": weight * 100.0,
                "threshold": concentration_threshold,
            })

    if loss_threshold is not None:
        loss_threshold = _finite_float(loss_threshold, default=np.nan)
        threshold_ratio = loss_threshold / 100.0
        if not np.isfinite(threshold_ratio) or threshold_ratio <= 0:
            loss_threshold = None
    if loss_threshold is not None:
        for _, row in work.iterrows():
            loss_pct = _finite_float(row.get("P/L %", 0.0), default=np.nan)
            if not np.isfinite(loss_pct) or loss_pct > -threshold_ratio:
                continue
            severity = "high" if loss_pct <= -(threshold_ratio * 1.5) else "medium"
            ticker = str(row.get("Ticker") or "n/d")
            items.append({
                "kind": "loss",
                "severity": severity,
                "severity_rank": severity_rank[severity],
                "ticker": ticker,
                "title": f"Perdita rilevante su {ticker}",
                "message": f"{ticker} segna {loss_pct * 100.0:.1f}% rispetto al costo, oltre la soglia del -{loss_threshold:.1f}%.",
                "value": loss_pct * 100.0,
                "threshold": -loss_threshold,
            })

    if bool(alerts_settings.get("risk_weight_monitoring", True)) and risk_df is not None and not risk_df.empty:
        ratio_series = _finite_series(risk_df.get("Rapporto rischio/peso"), default=0.0)
        tickers = risk_df.get("Ticker", pd.Series(dtype=str)).astype(str)
        for ticker, ratio in zip(tickers, ratio_series):
            if ratio <= green_max:
                continue
            severity = "high" if ratio > yellow_max else "medium"
            threshold = yellow_max if ratio > yellow_max else green_max
            items.append({
                "kind": "risk_weight",
                "severity": severity,
                "severity_rank": severity_rank[severity],
                "ticker": ticker,
                "title": f"Rischio/peso sbilanciato su {ticker}",
                "message": f"{ticker} ha un rapporto rischio/peso pari a {ratio:.2f}, oltre la soglia di {threshold:.2f}.",
                "value": float(ratio),
                "threshold": float(threshold),
            })

    if dfstats is not None and not dfstats.empty:
        stats_work = dfstats.copy()
        if drawdown_threshold is not None and "Max Drawdown" in stats_work.columns:
            drawdown_threshold = _finite_float(drawdown_threshold, default=np.nan)
            threshold_ratio = drawdown_threshold / 100.0
            drawdowns = _finite_series(stats_work["Max Drawdown"], default=np.nan)
            for _, row in stats_work.assign(_drawdown=drawdowns).dropna(subset=["_drawdown"]).iterrows():
                dd_value = _finite_float(row["_drawdown"], default=np.nan)
                if not np.isfinite(dd_value) or not np.isfinite(threshold_ratio) or threshold_ratio <= 0:
                    continue
                if dd_value > -threshold_ratio:
                    continue
                severity = "high" if dd_value <= -(threshold_ratio * 1.4) else "medium"
                ticker = str(row.get("Ticker") or "n/d")
                items.append({
                    "kind": "drawdown",
                    "severity": severity,
                    "severity_rank": severity_rank[severity],
                    "ticker": ticker,
                    "title": f"Drawdown elevato su {ticker}",
                    "message": f"{ticker} ha registrato un max drawdown del {dd_value * 100.0:.1f}%, oltre la soglia del -{drawdown_threshold:.1f}%.",
                    "value": dd_value * 100.0,
                    "threshold": -drawdown_threshold,
                })

        if volatility_threshold is not None and "Volatilità Ann." in stats_work.columns:
            volatility_threshold = _finite_float(volatility_threshold, default=np.nan)
            threshold_ratio = volatility_threshold / 100.0
            vols = _finite_series(stats_work["Volatilità Ann."], default=np.nan)
            for _, row in stats_work.assign(_vol=vols).dropna(subset=["_vol"]).iterrows():
                vol_value = _finite_float(row["_vol"], default=np.nan)
                if not np.isfinite(vol_value) or not np.isfinite(threshold_ratio) or threshold_ratio <= 0:
                    continue
                if vol_value < threshold_ratio:
                    continue
                severity = "high" if vol_value >= threshold_ratio * 1.35 else "medium"
                ticker = str(row.get("Ticker") or "n/d")
                items.append({
                    "kind": "volatility",
                    "severity": severity,
                    "severity_rank": severity_rank[severity],
                    "ticker": ticker,
                    "title": f"Volatilità elevata su {ticker}",
                    "message": f"{ticker} mostra volatilità annua del {vol_value * 100.0:.1f}%, oltre la soglia del {volatility_threshold:.1f}%.",
                    "value": vol_value * 100.0,
                    "threshold": volatility_threshold,
                })

    items.sort(key=lambda item: (-int(item["severity_rank"]), -abs(_finite_float(item.get("value", 0.0))), str(item.get("ticker", ""))))
    return items
