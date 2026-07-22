"""core/domain/cashflows.py — Calcoli flussi e XIRR."""
from __future__ import annotations

from typing import Any
from datetime import date
import numpy as np
import pandas as pd
import logging

from persistence.storage import _safe_float, get_registro_eventi

logger = logging.getLogger("portafoglio.core.domain.cashflows")


def compute_xirr(flows: list[float], dates: list[Any]) -> float | None:
    """
    Calcola XIRR (IRR con flussi irregolari) via bisection.
    flows: lista di float (negativo = uscita, positivo = entrata)
    dates: lista di date o datetime corrispondenti
    Restituisce IRR annualizzato o None se non calcolabile.
    """
    if len(flows) < 2 or len(flows) != len(dates):
        return None
    if not (any(f < 0 for f in flows) and any(f > 0 for f in flows)):
        return None
    d0 = pd.to_datetime(dates[0])
    years = [(pd.to_datetime(d) - d0).days / 365.25 for d in dates]

    def npv(rate: float) -> float:
        try:
            return sum(f / (1.0 + rate) ** y for f, y in zip(flows, years))
        except (ZeroDivisionError, OverflowError):
            return float("nan")

    lo, hi = -0.9999, 10.0
    if not (np.isfinite(npv(lo)) and np.isfinite(npv(hi))):
        return None
    if npv(lo) * npv(hi) > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if abs(hi - lo) < 1e-8:
            break
        val_mid = npv(mid)
        if not np.isfinite(val_mid):
            return None
        if npv(lo) * val_mid < 0:
            hi = mid
        else:
            lo = mid
    result = (lo + hi) / 2.0
    if not np.isfinite(result) or result < -0.99 or result > 3.0:
        return None
    return result


def build_xirr_flows(
    data: dict[str, Any],
    da_frame: pd.DataFrame,
    proventi: list[dict[str, Any]],
    tickers: list[str] | None = None,
) -> tuple[list[float], list[date]]:
    """
    Costruisce liste (flows, dates) per il calcolo XIRR.
    tickers=None → tutti gli strumenti (livello portafoglio).
    tickers=[...] → solo gli strumenti indicati (livello categoria).
    """
    ops = sorted(data.get("operazioni", []), key=lambda x: str(x.get("data", "")))
    flows, dates = [], []
    for op in ops:
        tk = op.get("ticker")
        if tickers is not None and tk not in tickers:
            continue
        try:
            d = pd.to_datetime(op["data"]).date()
            q = float(op.get("qty", 0))
            p = float(op.get("price", 0))
            c = float(op.get("comm", 0))
        except Exception:
            logger.warning("build_xirr_flows: operazione scartata per dati malformati, ticker=%s data=%r", tk, op.get("data"), exc_info=True)
            continue
        if op.get("tipo") == "ACQUISTO":
            flows.append(-(q * p + c))
        else:
            flows.append(q * p - c)
        dates.append(d)
    for prov in (proventi or []):
        tk = prov.get("ticker")
        if tickers is not None and tk not in tickers:
            continue
        try:
            d = pd.to_datetime(prov["data"]).date()
            netto = float(prov.get("importo_netto", 0))
        except Exception:
            logger.warning("build_xirr_flows: provento scartato per dati malformati, ticker=%s data=%r", tk, prov.get("data"), exc_info=True)
            continue
        if netto > 0:
            flows.append(netto)
            dates.append(d)
    if da_frame is not None and not da_frame.empty:
        work = da_frame.copy()
        if tickers is not None:
            work = work[work["Ticker"].isin(tickers)]
        final_value = float(pd.to_numeric(work["Controvalore"], errors="coerce").fillna(0).sum())
        if final_value > 0:
            flows.append(final_value)
            dates.append(date.today())
    if not flows or not dates:
        return [], []
    paired = sorted(zip(dates, flows), key=lambda x: x[0])
    dates_s, flows_s = zip(*paired)
    return list(flows_s), list(dates_s)
