"""core/services/instrument_clustering.py — Mappa strumenti (rischio/rendimento
osservato) e rilevazione di ridondanza per correlazione, sull'universo SATOR
(posseduto + candidati/watchlist).

Modulo separato da core/services/sator.py: stessi dati in ingresso, scopo
diverso — "il portafoglio ha ridondanze", non "cosa comprare". Nessuna
formula nuova: riusa run_sator_analysis per l'universo e le metriche gia'
filtrate, aggiunge solo una matrice di correlazione strumento-per-strumento.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from core.services.sator import ensure_sator_settings, run_sator_analysis

REDUNDANCY_THRESHOLD = 0.85
MIN_OVERLAP_DAYS = 60
_RETURN_HORIZONS = (
    ("ret_12m", "12 mesi"),
    ("ret_6m", "6 mesi"),
    ("ret_3m", "3 mesi"),
    ("ret_1m", "1 mese"),
)


@dataclass(frozen=True)
class InstrumentMapResult:
    scatter_df: pd.DataFrame
    redundant_pairs: pd.DataFrame
    universe_count: int


def _pick_return(row: pd.Series) -> tuple[float, str] | None:
    for col, label in _RETURN_HORIZONS:
        value = row.get(col)
        if pd.notna(value):
            return float(value), label
    return None


def _build_scatter_df(ranking: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "ticker", "name", "category", "nature", "role", "in_portfolio",
        "current_weight", "vol", "return_value", "return_label", "storico_sufficiente",
    ]
    if ranking is None or ranking.empty:
        return pd.DataFrame(columns=columns)
    rows = []
    for _, r in ranking.iterrows():
        picked = _pick_return(r)
        if picked is None or pd.isna(r.get("vol")):
            continue
        return_value, return_label = picked
        rows.append({
            "ticker": r.get("ticker"),
            "name": r.get("name"),
            "category": r.get("category"),
            "nature": r.get("nature"),
            "role": r.get("role"),
            "in_portfolio": bool(r.get("in_portfolio")),
            "current_weight": float(r.get("current_weight")) if pd.notna(r.get("current_weight")) else 0.0,
            "vol": float(r.get("vol")),
            "return_value": return_value,
            "return_label": return_label,
            "storico_sufficiente": bool(r.get("storico_sufficiente")),
        })
    return pd.DataFrame(rows, columns=columns)


def _build_redundant_pairs(ranking: pd.DataFrame, returns_frame: pd.DataFrame) -> pd.DataFrame:
    columns = ["ticker_a", "ticker_b", "name_a", "name_b", "category_a", "category_b", "correlazione"]
    if ranking is None or ranking.empty or returns_frame is None or returns_frame.empty:
        return pd.DataFrame(columns=columns)
    tickers = [t for t in ranking["ticker"].tolist() if t in returns_frame.columns]
    if len(tickers) < 2:
        return pd.DataFrame(columns=columns)
    corr = returns_frame[tickers].corr(min_periods=MIN_OVERLAP_DAYS)
    meta = ranking.drop_duplicates(subset="ticker").set_index("ticker")[["name", "category"]]
    rows = []
    for i, ticker_a in enumerate(tickers):
        for ticker_b in tickers[i + 1:]:
            value = corr.loc[ticker_a, ticker_b]
            if pd.isna(value) or value < REDUNDANCY_THRESHOLD:
                continue
            rows.append({
                "ticker_a": ticker_a,
                "ticker_b": ticker_b,
                "name_a": meta.loc[ticker_a, "name"] if ticker_a in meta.index else ticker_a,
                "name_b": meta.loc[ticker_b, "name"] if ticker_b in meta.index else ticker_b,
                "category_a": meta.loc[ticker_a, "category"] if ticker_a in meta.index else "",
                "category_b": meta.loc[ticker_b, "category"] if ticker_b in meta.index else "",
                "correlazione": float(value),
            })
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows, columns=columns).sort_values("correlazione", ascending=False).reset_index(drop=True)


def build_instrument_map(
    data: dict[str, Any],
    settings: dict[str, Any] | None,
    *,
    precomputed_result: dict[str, Any] | None = None,
) -> InstrumentMapResult:
    settings = settings or {}
    if precomputed_result is not None:
        result = precomputed_result
    else:
        cfg = ensure_sator_settings(settings)
        result = run_sator_analysis(data, settings, budget=cfg["default_budget"])
    ranking = result.get("ranking", pd.DataFrame())
    returns_frame = result.get("returns_frame", pd.DataFrame())
    return InstrumentMapResult(
        scatter_df=_build_scatter_df(ranking),
        redundant_pairs=_build_redundant_pairs(ranking, returns_frame),
        universe_count=int(len(ranking)),
    )
