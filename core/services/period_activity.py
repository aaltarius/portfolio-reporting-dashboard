"""
core/services/period_activity.py - Period activity summaries for reports and comparisons.

Pure helpers built on top of registro_eventi. They summarize what happened in a
selected time window without mixing cash movements with performance metrics.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pandas as pd

from persistence.storage import get_registro_eventi


TRADE_BUY_TYPES = {"ACQUISTO"}
TRADE_SELL_TYPES = {"VENDITA", "RIMBORSO A SCADENZA"}
INCOME_TYPES = {"CEDOLA", "DIVIDENDO"}
CASH_IN_TYPES = {"VERSAMENTO"}
CASH_OUT_TYPES = {"PRELIEVO"}
FEE_TYPES = {"COMMISSIONE"}
TAX_TYPES = {"IMPOSTA"}


def build_period_activity(
    data: dict[str, Any] | None,
    start: date | None,
    end: date | None,
    *,
    include_start: bool = True,
) -> dict[str, Any]:
    events = _events_in_period(data, start, end, include_start=include_start)
    summary = _activity_summary(events)
    by_instrument = _activity_by_instrument(events, data)
    log_df = _event_log_df(events, data)
    return {
        "events": events,
        "summary": summary,
        "by_instrument": by_instrument,
        "event_log": log_df,
    }


def _events_in_period(
    data: dict[str, Any] | None,
    start: date | None,
    end: date | None,
    *,
    include_start: bool,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in get_registro_eventi(data or {}):
        ev_dt = _coerce_date(raw.get("data"))
        if ev_dt is None:
            continue
        if start is not None:
            if include_start:
                if ev_dt < start:
                    continue
            elif ev_dt <= start:
                continue
        if end is not None and ev_dt > end:
            continue
        out.append(dict(raw))
    out.sort(key=lambda item: (str(item.get("data") or ""), str(item.get("event_id") or "")))
    return out


def _activity_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    summary = {
        "event_count": 0,
        "buy_count": 0,
        "sell_count": 0,
        "income_count": 0,
        "cash_in_count": 0,
        "cash_out_count": 0,
        "buy_gross": 0.0,
        "buy_net_outflow": 0.0,
        "sell_gross": 0.0,
        "sell_net_inflow": 0.0,
        "income_gross": 0.0,
        "income_net": 0.0,
        "cash_in": 0.0,
        "cash_out": 0.0,
        "fees": 0.0,
        "taxes": 0.0,
        "net_cash_delta": 0.0,
        "trade_cash_delta": 0.0,
        "income_cash_delta": 0.0,
    }
    for ev in events:
        summary["event_count"] += 1
        tipo = _event_type(ev)
        lordo = _float(ev.get("importo_lordo"))
        netto = _float(ev.get("importo_netto"))
        fee = max(_float(ev.get("commissioni")), 0.0)
        tax = max(_float(ev.get("imposte")), 0.0)
        summary["fees"] += fee
        summary["taxes"] += tax
        if tipo in TRADE_BUY_TYPES:
            summary["buy_count"] += 1
            summary["buy_gross"] += lordo
            buy_outflow = abs(netto) if abs(netto) > 1e-12 else lordo + fee + tax
            summary["buy_net_outflow"] += buy_outflow
            summary["trade_cash_delta"] -= buy_outflow
        elif tipo in TRADE_SELL_TYPES:
            summary["sell_count"] += 1
            summary["sell_gross"] += lordo
            sell_inflow = netto if abs(netto) > 1e-12 else max(lordo - fee - tax, 0.0)
            summary["sell_net_inflow"] += sell_inflow
            summary["trade_cash_delta"] += sell_inflow
        elif tipo in INCOME_TYPES:
            summary["income_count"] += 1
            summary["income_gross"] += lordo
            income_inflow = netto if abs(netto) > 1e-12 else max(lordo - tax, 0.0)
            summary["income_net"] += income_inflow
            summary["income_cash_delta"] += income_inflow
        elif tipo in CASH_IN_TYPES:
            summary["cash_in_count"] += 1
            summary["cash_in"] += abs(netto) if abs(netto) > 1e-12 else abs(lordo)
        elif tipo in CASH_OUT_TYPES:
            summary["cash_out_count"] += 1
            summary["cash_out"] += abs(netto) if abs(netto) > 1e-12 else abs(lordo)
    summary["net_cash_delta"] = (
        summary["cash_in"]
        - summary["cash_out"]
        - summary["buy_net_outflow"]
        + summary["sell_net_inflow"]
        + summary["income_net"]
    )
    return summary


def _activity_by_instrument(events: list[dict[str, Any]], data: dict[str, Any] | None) -> pd.DataFrame:
    info_map = _instrument_info_map(data)
    rows_by_ticker: dict[str, dict[str, Any]] = {}
    for ev in events:
        ticker = str(ev.get("ticker") or "").strip()
        if not ticker:
            continue
        tipo = _event_type(ev)
        row = rows_by_ticker.setdefault(
            ticker,
            {
                "Ticker": ticker,
                "Strumento": info_map.get(ticker, ticker),
                "Operazioni": 0,
                "Quote acquistate": 0.0,
                "Quote vendute": 0.0,
                "Delta quote": 0.0,
                "Spesa acquisti": 0.0,
                "Incasso vendite": 0.0,
                "Cedole/dividendi netti": 0.0,
                "Commissioni": 0.0,
                "Imposte": 0.0,
                "Saldo netto": 0.0,
            },
        )
        row["Operazioni"] += 1
        qty = _float(ev.get("quantita"))
        lordo = _float(ev.get("importo_lordo"))
        netto = _float(ev.get("importo_netto"))
        fee = max(_float(ev.get("commissioni")), 0.0)
        tax = max(_float(ev.get("imposte")), 0.0)
        row["Commissioni"] += fee
        row["Imposte"] += tax
        if tipo in TRADE_BUY_TYPES:
            spend = abs(netto) if abs(netto) > 1e-12 else lordo + fee + tax
            row["Quote acquistate"] += qty
            row["Delta quote"] += qty
            row["Spesa acquisti"] += spend
            row["Saldo netto"] -= spend
        elif tipo in TRADE_SELL_TYPES:
            incasso = netto if abs(netto) > 1e-12 else max(lordo - fee - tax, 0.0)
            row["Quote vendute"] += qty
            row["Delta quote"] -= qty
            row["Incasso vendite"] += incasso
            row["Saldo netto"] += incasso
        elif tipo in INCOME_TYPES:
            income = netto if abs(netto) > 1e-12 else max(lordo - tax, 0.0)
            row["Cedole/dividendi netti"] += income
            row["Saldo netto"] += income
    if not rows_by_ticker:
        return pd.DataFrame()
    frame = pd.DataFrame(rows_by_ticker.values())
    sort_key = frame["Spesa acquisti"].abs() + frame["Incasso vendite"].abs() + frame["Cedole/dividendi netti"].abs()
    return frame.assign(_sort_key=sort_key).sort_values("_sort_key", ascending=False).drop(columns="_sort_key").reset_index(drop=True)


def _event_log_df(events: list[dict[str, Any]], data: dict[str, Any] | None) -> pd.DataFrame:
    info_map = _instrument_info_map(data)
    rows = []
    for ev in events:
        tipo = _event_type(ev)
        ticker = str(ev.get("ticker") or "").strip()
        rows.append(
            {
                "Data": _display_date(ev.get("data")),
                "Ticker": ticker,
                "Strumento": info_map.get(ticker, ticker) if ticker else "",
                "Evento": tipo,
                "Quote": _float(ev.get("quantita")),
                "Prezzo": _float(ev.get("prezzo_unitario")),
                "Lordo": _float(ev.get("importo_lordo")),
                "Commissioni": _float(ev.get("commissioni")),
                "Imposte": _float(ev.get("imposte")),
                "Netto": _float(ev.get("importo_netto")),
                "Note": str(ev.get("note") or ""),
            }
        )
    return pd.DataFrame(rows)


def _instrument_info_map(data: dict[str, Any] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in (data or {}).get("strumenti", []) or []:
        ticker = str(item.get("ticker") or "").strip()
        name = str(item.get("strumento") or item.get("nome") or ticker).strip()
        if ticker:
            out[ticker] = name or ticker
    return out


def _coerce_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value)
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt).date()
        except Exception:
            continue
    parsed = pd.to_datetime(text, errors="coerce", dayfirst="/" in text)
    if pd.notna(parsed):
        return pd.Timestamp(parsed).date()
    return None


def _event_type(event: dict[str, Any]) -> str:
    return str(event.get("tipo_evento") or event.get("tipo") or "").strip().upper()


def _display_date(value: Any) -> str:
    dt = _coerce_date(value)
    return dt.strftime("%d/%m/%Y") if dt else str(value or "")


def _float(value: Any) -> float:
    try:
        if value in (None, ""):
            return 0.0
        return float(value)
    except Exception:
        return 0.0
