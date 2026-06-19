"""
core/services/income_scadenze.py — Income and maturity analytics for Cruscotti.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd


def _numeric_series(frame: pd.DataFrame, *column_names: str) -> pd.Series:
    if frame is None or frame.empty:
        return pd.Series(dtype="float64")
    for name in column_names:
        if name in frame.columns:
            return pd.to_numeric(frame[name], errors="coerce").fillna(0.0)
    return pd.Series(dtype="float64")


def build_income_scadenze_summary(data: dict[str, Any], da: pd.DataFrame, calendar_df: pd.DataFrame | None) -> dict[str, Any]:
    if calendar_df is None or calendar_df.empty:
        return {
            "future_income_df": pd.DataFrame(),
            "maturity_df": pd.DataFrame(),
            "gov_details_df": pd.DataFrame(),
            "expected_net_income_12m": 0.0,
            "expected_redemptions_12m": 0.0,
            "gov_market_value": 0.0,
            "yield_on_value_12m": 0.0,
        }
    today = pd.Timestamp(date.today()).normalize()
    next_12m = today + pd.DateOffset(months=12)
    future_df = calendar_df.copy()
    future_df["data"] = pd.to_datetime(future_df.get("data"), errors="coerce")
    future_df = future_df.dropna(subset=["data"])
    future_df = future_df[future_df["data"] >= today].copy()

    coupon_df = future_df[future_df.get("tipo_evento", "").astype(str).str.lower().eq("cedola")].copy()
    coupon_df["Anno"] = coupon_df["data"].dt.year
    future_income_df = (
        coupon_df.groupby("Anno", dropna=False)["importo"]
        .sum()
        .reset_index()
        .rename(columns={"importo": "Cedole nette attese"})
    ) if not coupon_df.empty else pd.DataFrame(columns=["Anno", "Cedole nette attese"])

    maturity_df = future_df[future_df.get("tipo_evento", "").astype(str).str.lower().eq("scadenza")].copy()
    maturity_df["Anno"] = maturity_df["data"].dt.year
    maturity_df = (
        maturity_df.groupby("Anno", dropna=False)["importo"]
        .sum()
        .reset_index()
        .rename(columns={"importo": "Capitale a rimborso"})
    ) if not maturity_df.empty else pd.DataFrame(columns=["Anno", "Capitale a rimborso"])

    gov_df = da.copy() if da is not None else pd.DataFrame()
    if gov_df is None or gov_df.empty:
        try:
            from core.finance import build_ptf_df
            gov_df = build_ptf_df(data)
        except Exception:
            gov_df = pd.DataFrame()
    if not gov_df.empty and "Categoria" in gov_df.columns:
        gov_df = gov_df[gov_df["Categoria"].astype(str).eq("GOV")].copy()
    elif not gov_df.empty and "Tipo" in gov_df.columns:
        gov_df = gov_df[gov_df["Tipo"].astype(str).str.lower().isin({"btp", "titolo di stato"})].copy()
    else:
        gov_df = pd.DataFrame()
    gov_market_col = _numeric_series(gov_df, "Valore di Mercato", "Controvalore")
    gov_market_value = float(gov_market_col.sum()) if not gov_df.empty else 0.0

    coupon_12m = coupon_df[coupon_df["data"] <= next_12m].copy()
    maturity_12m = future_df[
        future_df.get("tipo_evento", "").astype(str).str.lower().eq("scadenza") & (future_df["data"] <= next_12m)
    ].copy()
    coupon_importo_col = coupon_12m["importo"] if (not coupon_12m.empty and "importo" in coupon_12m.columns) else pd.Series(dtype="float64")
    maturity_importo_col = maturity_12m["importo"] if (not maturity_12m.empty and "importo" in maturity_12m.columns) else pd.Series(dtype="float64")
    expected_net_income_12m = float(pd.to_numeric(coupon_importo_col, errors="coerce").fillna(0.0).sum()) if not coupon_12m.empty else 0.0
    expected_redemptions_12m = float(pd.to_numeric(maturity_importo_col, errors="coerce").fillna(0.0).sum()) if not maturity_12m.empty else 0.0
    yield_on_value_12m = (expected_net_income_12m / gov_market_value) if abs(gov_market_value) > 1e-9 else 0.0

    gov_details_df = pd.DataFrame(columns=["Ticker", "Strumento", "Valore di Mercato", "Cedole 12 mesi", "Yield su valore"])
    if not gov_df.empty and "Ticker" in gov_df.columns:
        coupon_by_ticker = (
            coupon_12m.groupby(coupon_12m["ticker"].astype(str))["importo"].sum().to_dict()
            if not coupon_12m.empty else {}
        )
        details = []
        for _, row in gov_df.iterrows():
            ticker = str(row.get("Ticker", "") or "")
            market_value = float(
                pd.to_numeric(
                    row.get("Valore di Mercato", row.get("Controvalore", 0)),
                    errors="coerce",
                ) or 0.0
            )
            coupon_value = float(coupon_by_ticker.get(ticker, 0.0) or 0.0)
            details.append({
                "Ticker": ticker,
                "Strumento": row.get("Strumento", row.get("nome", ticker)),
                "Valore di Mercato": market_value,
                "Cedole 12 mesi": coupon_value,
                "Yield su valore": (coupon_value / market_value) if abs(market_value) > 1e-9 else 0.0,
            })
        gov_details_df = pd.DataFrame(details)
        if not gov_details_df.empty:
            gov_details_df = gov_details_df.sort_values("Cedole 12 mesi", ascending=False).reset_index(drop=True)

    return {
        "future_income_df": future_income_df,
        "maturity_df": maturity_df,
        "gov_details_df": gov_details_df,
        "expected_net_income_12m": expected_net_income_12m,
        "expected_redemptions_12m": expected_redemptions_12m,
        "gov_market_value": gov_market_value,
        "yield_on_value_12m": yield_on_value_12m,
    }
