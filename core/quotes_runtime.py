from __future__ import annotations

from typing import Any, Iterable

import pandas as pd


def build_quotes_refresh_df(
    quotes_log: dict[str, Any] | None,
    allowed_tickers: Iterable[str] | None = None,
) -> pd.DataFrame:
    q = quotes_log or {}
    items = q.get("items", []) or []
    if not items:
        return pd.DataFrame()
    allowed = {
        str(ticker or "").strip()
        for ticker in (allowed_tickers or [])
        if str(ticker or "").strip()
    }

    latest_by_ticker: dict[str, dict[str, Any]] = {}
    for item in items:
        ticker = str(item.get("ticker") or "").strip()
        if not ticker:
            continue
        if allowed and ticker not in allowed:
            continue
        ts = str(item.get("timestamp") or "")
        previous = latest_by_ticker.get(ticker)
        if previous is None or ts >= str(previous.get("timestamp") or ""):
            latest_by_ticker[ticker] = item

    rows = []
    for item in latest_by_ticker.values():
        status = item.get("status", "")
        if status == "ok":
            esito = "OK"
        elif status == "warning":
            esito = "WARNING"
        else:
            esito = "ERRORE"
        delta = item.get("delta_pct")
        rows.append(
            {
                "Strumento": item.get("instrument_name") or item.get("ticker") or "",
                "Ticker": item.get("ticker") or "",
                "Prezzo letto": item.get("price"),
                "Prezzo precedente": item.get("previous_price"),
                "Var. vs prec.": delta,
                "Fonte": item.get("source") or "",
                "Esito": esito,
                "Fallback": "Sì" if item.get("fallback_used") else "No",
                "Nota": item.get("warning") or "",
                "Timestamp": item.get("timestamp") or "",
            }
        )
    return pd.DataFrame(rows).sort_values(["Strumento", "Ticker"], kind="stable").reset_index(drop=True)
