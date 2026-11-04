"""core/domain/cashflows.py — Calcoli flussi e XIRR."""
from __future__ import annotations

from typing import Any
from datetime import date
import numpy as np
import pandas as pd
import logging

from persistence.storage import _safe_float, get_registro_eventi

logger = logging.getLogger("portafoglio.core.domain.cashflows")


def _strict_finite_float(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        raise ValueError("boolean value is not a financial number")
    if value in (None, ""):
        return default
    number = float(value)
    if not np.isfinite(number):
        raise ValueError("non-finite financial number")
    return float(number)


def _finite_column_sum(frame: pd.DataFrame, column: str) -> float:
    if frame is None or frame.empty or column not in frame.columns:
        return 0.0
    values = pd.to_numeric(frame.get(column), errors="coerce").replace([np.inf, -np.inf], np.nan)
    return float(values.fillna(0.0).sum())


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
    event_flows, event_dates = _build_xirr_flows_from_events(data, da_frame, tickers=tickers)
    if event_flows and event_dates:
        return event_flows, event_dates

    ops = sorted(data.get("operazioni", []), key=lambda x: str(x.get("data", "")))
    flows, dates = [], []
    for op in ops:
        tk = op.get("ticker")
        if tickers is not None and tk not in tickers:
            continue
        try:
            d = pd.to_datetime(op["data"]).date()
            q = _strict_finite_float(op.get("qty", 0))
            p = _strict_finite_float(op.get("price", 0))
            c = _strict_finite_float(op.get("comm", 0))
            tax = _strict_finite_float(op.get("imposte", op.get("tax", 0)))
        except Exception:
            logger.warning("build_xirr_flows: operazione scartata per dati malformati, ticker=%s data=%r", tk, op.get("data"), exc_info=True)
            continue
        if op.get("tipo") == "ACQUISTO":
            flows.append(-(q * p + c + tax))
        else:
            flows.append(q * p - c - tax)
        dates.append(d)
    for prov in (proventi or []):
        tk = prov.get("ticker")
        if tickers is not None and tk not in tickers:
            continue
        try:
            d = pd.to_datetime(prov["data"]).date()
            netto = _strict_finite_float(prov.get("importo_netto", 0))
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
        final_value = _finite_column_sum(work, "Controvalore")
        if final_value > 0:
            flows.append(final_value)
            dates.append(date.today())
    if not flows or not dates:
        return [], []
    paired = sorted(zip(dates, flows), key=lambda x: x[0])
    dates_s, flows_s = zip(*paired)
    return list(flows_s), list(dates_s)


def build_portfolio_external_xirr_flows(
    data: dict[str, Any],
    final_value: float,
    *,
    as_of_date: date | None = None,
) -> tuple[list[float], list[date]]:
    """Flussi XIRR del portafoglio totale dal punto di vista dell'investitore.

    A livello portafoglio, acquisti/vendite sono movimenti interni tra
    liquidita' e strumenti. Il MWR complessivo deve usare solo flussi esterni:
    versamenti (cash out dell'investitore), prelievi (cash in) e patrimonio
    finale, che include strumenti e liquidita'.
    """
    try:
        events = sorted(get_registro_eventi(data), key=lambda x: str(x.get("data", "")))
    except Exception:
        events = []

    flows: list[float] = []
    dates: list[date] = []
    for event in events:
        event_type = str(event.get("tipo_evento") or event.get("tipo") or "").upper()
        if event_type not in {"VERSAMENTO", "PRELIEVO"}:
            continue
        try:
            event_date = pd.to_datetime(event.get("data")).date()
        except Exception:
            logger.warning("build_portfolio_external_xirr_flows: evento scartato per data malformata, data=%r", event.get("data"), exc_info=True)
            continue
        net = _safe_float(event.get("importo_netto", 0))
        gross = _safe_float(event.get("importo_lordo", 0))
        amount = abs(net) if abs(net) > 1e-9 else abs(gross)
        if amount <= 1e-9:
            continue
        flows.append(-amount if event_type == "VERSAMENTO" else amount)
        dates.append(event_date)

    terminal_value = _safe_float(final_value, 0.0)
    if terminal_value > 1e-9:
        flows.append(terminal_value)
        dates.append(as_of_date or date.today())

    if not flows or not dates:
        return [], []
    paired = sorted(zip(dates, flows), key=lambda x: x[0])
    dates_s, flows_s = zip(*paired)
    return list(flows_s), list(dates_s)


def _build_xirr_flows_from_events(
    data: dict[str, Any],
    da_frame: pd.DataFrame,
    *,
    tickers: list[str] | None = None,
) -> tuple[list[float], list[date]]:
    """Build XIRR flows from the canonical event register.

    Legacy `operazioni` rows do not always carry taxes, so the event register
    is the safer source for money-weighted returns.
    """
    try:
        events = sorted(get_registro_eventi(data), key=lambda x: str(x.get("data", "")))
    except Exception:
        events = []
    if not events:
        return [], []

    flows: list[float] = []
    dates: list[date] = []
    ticker_filter = set(tickers) if tickers is not None else None

    for event in events:
        event_type = str(event.get("tipo_evento") or event.get("tipo") or "").upper()
        ticker = str(event.get("ticker") or "").strip()
        if ticker_filter is not None and ticker not in ticker_filter:
            continue
        if event_type not in {"ACQUISTO", "VENDITA", "RIMBORSO A SCADENZA", "CEDOLA", "DIVIDENDO"}:
            continue
        try:
            event_date = pd.to_datetime(event.get("data")).date()
        except Exception:
            logger.warning("build_xirr_flows: evento scartato per data malformata, ticker=%s data=%r", ticker, event.get("data"), exc_info=True)
            continue

        qty = _safe_float(event.get("quantita", event.get("qty", 0)))
        price = _safe_float(event.get("prezzo_unitario", event.get("price", 0)))
        fees = _safe_float(event.get("commissioni", event.get("comm", 0)))
        taxes = _safe_float(event.get("imposte", event.get("tax", 0)))
        net = _safe_float(event.get("importo_netto", 0))

        if event_type == "ACQUISTO":
            amount = -abs(net) if abs(net) > 1e-9 else -(qty * price + fees + taxes)
        elif event_type in {"VENDITA", "RIMBORSO A SCADENZA"}:
            amount = abs(net) if abs(net) > 1e-9 else (qty * price - fees - taxes)
        else:
            amount = net

        if abs(amount) <= 1e-9:
            continue
        flows.append(float(amount))
        dates.append(event_date)

    if da_frame is not None and not da_frame.empty:
        work = da_frame.copy()
        if ticker_filter is not None and "Ticker" in work.columns:
            work = work[work["Ticker"].isin(ticker_filter)]
        final_value = _finite_column_sum(work, "Controvalore")
        if final_value > 0:
            flows.append(final_value)
            dates.append(date.today())

    if not flows or not dates:
        return [], []
    paired = sorted(zip(dates, flows), key=lambda x: x[0])
    dates_s, flows_s = zip(*paired)
    return list(flows_s), list(dates_s)
