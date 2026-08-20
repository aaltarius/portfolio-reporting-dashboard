"""
core/services/income_scadenze.py — Income and maturity analytics for Cruscotti.
"""
from __future__ import annotations

from datetime import date
import math
from typing import Any

import pandas as pd

from core.domain.bonds import calc_ytm_and_duration
from core.domain.positions import held_tickers
from persistence.storage import get_registro_eventi, macro_cat


def _finite_float(value: Any, default: float = 0.0) -> float:
    try:
        raw = default if value is None or (isinstance(value, str) and value.strip() == "") else value
        result = float(raw)
    except Exception:
        return default
    return result if math.isfinite(result) else default


def _finite_optional(value: Any) -> float | None:
    result = _finite_float(value, default=math.nan)
    return result if math.isfinite(result) else None


def _numeric_series(frame: pd.DataFrame, *column_names: str) -> pd.Series:
    if frame is None or frame.empty:
        return pd.Series(dtype="float64")
    for name in column_names:
        if name in frame.columns:
            return pd.to_numeric(frame[name], errors="coerce").map(_finite_float)
    return pd.Series(0.0, index=frame.index, dtype="float64")


def matured_unredeemed_gov(data: dict[str, Any], today: date | None = None) -> list[dict[str, Any]]:
    """Titoli GOV scaduti (scadenza < oggi) con posizione ancora aperta e
    nessun evento RIMBORSO A SCADENZA registrato: segnala un rimborso da
    inserire manualmente, senza generare alcun evento in automatico."""
    today = today or date.today()
    open_tickers = held_tickers(data)
    eventi = get_registro_eventi(data)
    rimborso_tickers = {
        str(ev.get("ticker") or "")
        for ev in eventi
        if ev.get("tipo_evento") == "RIMBORSO A SCADENZA" and str(ev.get("ticker") or "")
    }

    result: list[dict[str, Any]] = []
    for s in data.get("strumenti") or []:
        ticker = str(s.get("ticker") or "")
        if not ticker or ticker not in open_tickers or ticker in rimborso_tickers:
            continue
        if macro_cat(str(s.get("tipo") or "")) != "GOV":
            continue
        scadenza_raw = s.get("scadenza")
        if not scadenza_raw:
            continue
        try:
            scadenza = pd.to_datetime(scadenza_raw).date()
        except Exception:
            continue
        if scadenza >= today:
            continue
        quantita = sum(
            _finite_float(ev.get("quantita", 0)) if ev.get("tipo_evento") == "ACQUISTO" else -_finite_float(ev.get("quantita", 0))
            for ev in eventi
            if str(ev.get("ticker") or "") == ticker and ev.get("tipo_evento") in {"ACQUISTO", "VENDITA", "RIMBORSO A SCADENZA"}
        )
        result.append({
            "ticker": ticker,
            "nome": str(s.get("nome") or ticker),
            "scadenza": str(scadenza),
            "giorni_scaduto": (today - scadenza).days,
            "quantita": quantita,
        })
    return sorted(result, key=lambda item: item["giorni_scaduto"], reverse=True)


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
    future_df["importo"] = _numeric_series(future_df, "importo")

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
    expected_net_income_12m = float(pd.to_numeric(coupon_importo_col, errors="coerce").map(_finite_float).sum()) if not coupon_12m.empty else 0.0
    expected_redemptions_12m = float(pd.to_numeric(maturity_importo_col, errors="coerce").map(_finite_float).sum()) if not maturity_12m.empty else 0.0
    yield_on_value_12m = (expected_net_income_12m / gov_market_value) if abs(gov_market_value) > 1e-9 else 0.0

    gov_details_df = pd.DataFrame(columns=["Ticker", "Strumento", "Valore di Mercato", "Cedole 12 mesi", "Yield su valore"])
    # Mappa ticker → strumento per calcolo YTM/Duration
    strumenti_map = {
        str(s.get("ticker") or ""): s
        for s in (data.get("strumenti") or [])
        if str(s.get("ticker") or "")
    }

    if not gov_df.empty and "Ticker" in gov_df.columns:
        coupon_by_ticker = (
            coupon_12m.groupby(coupon_12m["ticker"].astype(str))["importo"].sum().to_dict()
            if not coupon_12m.empty else {}
        )
        details = []
        for _, row in gov_df.iterrows():
            ticker = str(row.get("Ticker", "") or "")
            market_value = float(
                _finite_float(row.get("Valore di Mercato", row.get("Controvalore", 0)))
            )
            coupon_value = _finite_float(coupon_by_ticker.get(ticker, 0.0))
            strumento = strumenti_map.get(ticker, {})
            ytm, dur_mod = calc_ytm_and_duration(strumento)
            details.append({
                "Ticker": ticker,
                "Strumento": row.get("Strumento", row.get("nome", ticker)),
                "Valore di Mercato": market_value,
                "Cedole 12 mesi": coupon_value,
                "Yield su valore": (coupon_value / market_value) if abs(market_value) > 1e-9 else 0.0,
                "YTM": _finite_optional(ytm),
                "Duration mod.": _finite_optional(dur_mod),
            })
        gov_details_df = pd.DataFrame(details)
        if not gov_details_df.empty:
            # Ordine cronologico di scadenza (non per cedola attesa
            # decrescente): coerente con la Timeline BTP sulla stessa
            # pagina (richiesta esplicita 2026-08-20).
            scadenza_by_ticker = {
                tk: pd.to_datetime(strumenti_map.get(tk, {}).get("scadenza"), errors="coerce")
                for tk in gov_details_df["Ticker"]
            }
            gov_details_df = (
                gov_details_df
                .assign(_scadenza=gov_details_df["Ticker"].map(scadenza_by_ticker))
                .sort_values("_scadenza", na_position="last", kind="stable")
                .drop(columns="_scadenza")
                .reset_index(drop=True)
            )

    # Duration media ponderata per valore di mercato
    duration_media_ponderata: float | None = None
    if not gov_details_df.empty and "Duration mod." in gov_details_df.columns and "Valore di Mercato" in gov_details_df.columns:
        valid = pd.DataFrame({
            "Duration mod.": pd.to_numeric(gov_details_df["Duration mod."], errors="coerce").map(lambda value: _finite_float(value, math.nan)),
            "Valore di Mercato": _numeric_series(gov_details_df, "Valore di Mercato"),
        }).dropna(subset=["Duration mod.", "Valore di Mercato"])
        valid = valid[valid["Valore di Mercato"] > 0]
        if not valid.empty:
            total_weight = _finite_float(valid["Valore di Mercato"].sum())
            if total_weight > 0:
                duration_media_ponderata = _finite_optional(
                    (valid["Duration mod."] * valid["Valore di Mercato"]).sum() / total_weight
                )

    return {
        "future_income_df": future_income_df,
        "maturity_df": maturity_df,
        "gov_details_df": gov_details_df,
        "expected_net_income_12m": expected_net_income_12m,
        "expected_redemptions_12m": expected_redemptions_12m,
        "gov_market_value": gov_market_value,
        "yield_on_value_12m": yield_on_value_12m,
        "duration_media_ponderata": duration_media_ponderata,
    }
