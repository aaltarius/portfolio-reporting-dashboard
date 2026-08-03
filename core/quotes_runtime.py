from __future__ import annotations

from typing import Any, Iterable

import pandas as pd

from persistence.storage import macro_cat


QUOTE_REFRESH_COLUMNS = [
    "Strumento",
    "Ticker",
    "Prezzo letto",
    "Prezzo precedente",
    "Var. vs prec.",
    "Fonte",
    "Esito",
    "Fallback",
    "Nota",
    "Timestamp",
]


def build_quotes_refresh_df(
    quotes_log: dict[str, Any] | None,
    allowed_tickers: Iterable[str] | None = None,
) -> pd.DataFrame:
    q = quotes_log or {}
    items = q.get("items", []) or []
    if not items:
        return pd.DataFrame(columns=QUOTE_REFRESH_COLUMNS)
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
    if not rows:
        return pd.DataFrame(columns=QUOTE_REFRESH_COLUMNS)
    return pd.DataFrame(rows, columns=QUOTE_REFRESH_COLUMNS).sort_values(["Strumento", "Ticker"], kind="stable").reset_index(drop=True)


def build_quotes_diagnostic_table(
    *,
    data: dict[str, Any],
    quotes_log: dict[str, Any] | None,
    quotes_refresh_df: pd.DataFrame | None = None,
    closed_tickers: Iterable[str] | None = None,
) -> pd.DataFrame:
    """Tabella diagnostica quotazioni pronta per la UI.

    Centralizza la logica usata dalla pagina Quotazioni: strumenti attivi,
    righe mancanti nel log e categoria compatta. La pagina Streamlit deve solo
    renderizzare il risultato.
    """

    closed = {
        str(ticker or "").strip()
        for ticker in (closed_tickers or [])
        if str(ticker or "").strip()
    }
    strumenti_attivi = [
        item for item in (data.get("strumenti", []) or [])
        if str(item.get("ticker") or "").strip()
        and str(item.get("ticker") or "").strip() not in closed
    ]
    active_tickers = [str(item.get("ticker") or "").strip() for item in strumenti_attivi]
    if quotes_refresh_df is None:
        qdf = build_quotes_refresh_df(quotes_log, active_tickers)
    else:
        qdf = quotes_refresh_df.copy()

    present_tickers = {
        str(tk or "").strip()
        for tk in (qdf["Ticker"].tolist() if "Ticker" in qdf.columns else [])
        if str(tk or "").strip()
    }
    missing_rows: list[dict[str, Any]] = []
    for item in strumenti_attivi:
        ticker = str(item.get("ticker") or "").strip()
        if not ticker or ticker in present_tickers:
            continue
        missing_rows.append(
            {
                "Strumento": item.get("nome") or ticker,
                "Ticker": ticker,
                "Prezzo letto": None,
                "Prezzo precedente": None,
                "Var. vs prec.": None,
                "Fonte": item.get("fonte") or "",
                "Esito": "ASSENTE",
                "Fallback": "No",
                "Nota": "Nessuna lettura disponibile nel log quotazioni",
                "Timestamp": "",
            }
        )
    if missing_rows:
        qdf = pd.concat([qdf, pd.DataFrame(missing_rows)], ignore_index=True)
        qdf = qdf.sort_values(["Strumento", "Ticker"], kind="stable").reset_index(drop=True)

    if not qdf.empty and "Tipologia" not in qdf.columns:
        tipo_map = {
            str(s.get("ticker") or ""): macro_cat(s.get("tipo", ""))
            for s in data.get("strumenti", [])
        }
        qdf.insert(2, "Tipologia", qdf["Ticker"].map(lambda tk: tipo_map.get(str(tk or ""), "")))
    return qdf
