"""
core/services/alerts.py — Portfolio alerts services.

Functions for building portfolio alert lists based on configured thresholds.
Pure functions - no Streamlit dependencies, no side effects.
"""
from typing import Any
import numpy as np
import pandas as pd


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
    work["Controvalore"] = pd.to_numeric(work.get("Controvalore"), errors="coerce").fillna(0.0)
    work["Costo"] = pd.to_numeric(work.get("Costo"), errors="coerce").fillna(0.0)
    work["P/L €"] = pd.to_numeric(work.get("P/L €"), errors="coerce").fillna(0.0)
    total_value = float(work["Controvalore"].sum())
    if total_value <= 0:
        return []

    work["Peso %"] = work["Controvalore"] / total_value
    if "P/L %" in work.columns:
        work["P/L %"] = pd.to_numeric(work["P/L %"], errors="coerce")
    else:
        denom = work["Costo"].abs().replace(0, np.nan)
        work["P/L %"] = work["P/L €"] / denom

    concentration_threshold = alerts_settings.get("concentration_threshold_pct")
    loss_threshold = alerts_settings.get("loss_threshold_pct")
    drawdown_threshold = alerts_settings.get("drawdown_threshold_pct")
    volatility_threshold = alerts_settings.get("volatility_threshold_pct")
    calculations = (settings or {}).get("calculations_metrics", {}) if isinstance(settings, dict) else {}
    risk_thresholds = calculations.get("risk_traffic_light_thresholds", {}) if isinstance(calculations, dict) else {}
    green_max = float(risk_thresholds.get("green_max", 1.0) or 1.0)
    yellow_max = float(risk_thresholds.get("yellow_max", 1.2) or 1.2)

    severity_rank = {"high": 3, "medium": 2, "low": 1}
    items: list[dict[str, Any]] = []

    if concentration_threshold is not None:
        threshold_ratio = float(concentration_threshold) / 100.0
        for _, row in work.iterrows():
            weight = float(row.get("Peso %", 0.0) or 0.0)
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
                "message": f"{ticker} pesa {weight * 100.0:.1f}% del portafoglio, oltre la soglia del {float(concentration_threshold):.1f}%.",
                "value": weight * 100.0,
                "threshold": float(concentration_threshold),
            })

    if loss_threshold is not None:
        threshold_ratio = float(loss_threshold) / 100.0
        for _, row in work.iterrows():
            loss_pct = float(row.get("P/L %", 0.0) or 0.0)
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
                "message": f"{ticker} segna {loss_pct * 100.0:.1f}% rispetto al costo, oltre la soglia del -{float(loss_threshold):.1f}%.",
                "value": loss_pct * 100.0,
                "threshold": -float(loss_threshold),
            })

    if bool(alerts_settings.get("risk_weight_monitoring", True)) and risk_df is not None and not risk_df.empty:
        ratio_series = pd.to_numeric(risk_df.get("Rapporto rischio/peso"), errors="coerce").fillna(0.0)
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
            drawdowns = pd.to_numeric(stats_work["Max Drawdown"], errors="coerce")
            for _, row in stats_work.assign(_drawdown=drawdowns).dropna(subset=["_drawdown"]).iterrows():
                dd_value = float(row["_drawdown"])
                threshold_ratio = float(drawdown_threshold) / 100.0
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
                    "message": f"{ticker} ha registrato un max drawdown del {dd_value * 100.0:.1f}%, oltre la soglia del -{float(drawdown_threshold):.1f}%.",
                    "value": dd_value * 100.0,
                    "threshold": -float(drawdown_threshold),
                })

        if volatility_threshold is not None and "Volatilità Ann." in stats_work.columns:
            vols = pd.to_numeric(stats_work["Volatilità Ann."], errors="coerce")
            for _, row in stats_work.assign(_vol=vols).dropna(subset=["_vol"]).iterrows():
                vol_value = float(row["_vol"])
                threshold_ratio = float(volatility_threshold) / 100.0
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
                    "message": f"{ticker} mostra volatilità annua del {vol_value * 100.0:.1f}%, oltre la soglia del {float(volatility_threshold):.1f}%.",
                    "value": vol_value * 100.0,
                    "threshold": float(volatility_threshold),
                })

    items.sort(key=lambda item: (-int(item["severity_rank"]), -abs(float(item.get("value", 0.0))), str(item.get("ticker", ""))))
    return items
