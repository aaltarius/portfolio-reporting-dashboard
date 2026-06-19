from __future__ import annotations

import numpy as np
import pandas as pd


def build_expanded_price_frame(data, dh_hist=None):
    if dh_hist is None:
        from core.finance import build_hist_df
        base = build_hist_df(data)
    else:
        base = dh_hist
    tickers = [s["ticker"] for s in data.get("strumenti", [])]
    if base is None or base.empty:
        base = pd.DataFrame(columns=tickers)
    else:
        base = base.copy()
    op_rows = []
    for op in sorted(data.get("operazioni", []), key=lambda x: str(x.get("data", ""))):
        try:
            date = pd.to_datetime(op.get("data"))
            ticker = op.get("ticker")
            price = float(op.get("price", np.nan))
        except Exception:
            continue
        op_rows.append({"Data": date, ticker: price})
    if op_rows:
        extra = pd.DataFrame(op_rows).set_index("Data")
        for ticker in tickers:
            if ticker not in extra.columns:
                extra[ticker] = np.nan
        extra = extra[tickers]
        combined = pd.concat([base, extra], axis=0)
        combined = combined.groupby(level=0).last().sort_index()
    else:
        combined = base.sort_index()
    if not combined.empty:
        for ticker in tickers:
            if ticker not in combined.columns:
                combined[ticker] = np.nan
        combined = combined[tickers].apply(pd.to_numeric, errors="coerce").sort_index().ffill()
    return combined
