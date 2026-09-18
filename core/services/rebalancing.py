"""
core/services/rebalancing.py — Ribilanciamento in Pianificazione.

Estende la banda di tolleranza gia' esistente in core/services/sator.py
(oggi usata solo per bloccare nuovi acquisti su un bucket sopra banda) in
modo bidirezionale: individua sia i bucket in surplus (candidati alla
riduzione) sia quelli in deficit (candidati al rinforzo, con lo stesso
motore SATOR gia' esistente). Nessuna formula finanziaria nuova: ogni
funzione qui sotto riusa dati/funzioni gia' presenti in sator.py.
Vedi docs/superpowers/specs/2026-09-18-ribilanciamento-pianificazione-design.md.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from core.services.sator import (
    compute_instrument_bucket_exposures,
    infer_sator_metadata,
    resolve_instrument_no_sell,
)

_BUCKETS = ("Core", "Difensivo", "Satellite")
_MATERIALITY_EUR = 50.0
_TIE_BREAK_EUR = 50.0


def compute_bucket_drift(
    current_mix: dict[str, float],
    bands: dict[str, dict[str, float]],
    portfolio_value: float,
) -> dict[str, dict[str, float | str]]:
    """Per ciascun bucket fuori banda, stato (surplus/deficit) e importo in
    euro necessario per rientrare al BORDO della banda (non al target
    esatto - meno turnover). I bucket in banda sono omessi dal risultato:
    nessun avviso quando non serve intervenire."""
    drift: dict[str, dict[str, float | str]] = {}
    for bucket in _BUCKETS:
        attuale = float(current_mix.get(bucket, 0.0))
        band = bands.get(bucket, {"target": 0.0, "min": 0.0, "max": 1.0})
        if attuale > band["max"]:
            drift[bucket] = {"status": "surplus", "amount_eur": (attuale - band["max"]) * portfolio_value}
        elif attuale < band["min"]:
            drift[bucket] = {"status": "deficit", "amount_eur": (band["min"] - attuale) * portfolio_value}
    return drift


def build_reduction_candidates(
    data: dict[str, Any],
    state_df: pd.DataFrame,
    bucket: str,
    surplus_eur: float,
    exclude_tickers: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Candidati alla riduzione per un bucket in surplus: ordinati per
    contributo in euro al surplus (decrescente, criterio principale - NON
    il punteggio SATOR, verificato sui dati reali dell'utente che non
    coprirebbe gli strumenti fuori dall'universo ETF/ETC di SATOR, es. BTP
    e fondi). A parita' di contributo (entro _TIE_BREAK_EUR), vince chi ha
    P/L piu' negativo (minusvalenza: nessuna imposta, perdita fiscalmente
    compensabile). Esclude sempre NO_SELL e i ticker in exclude_tickers
    (stesso insieme del toggle "Escludi BTP/GOV" gia' esistente in
    Pianificazione, se attivo). Un candidato sotto _MATERIALITY_EUR non
    viene proposto come riga separata, a meno che sia l'ultimo pezzo
    necessario a coprire il residuo."""
    if state_df is None or state_df.empty or surplus_eur <= 0:
        return {"candidates": [], "covered_eur": 0.0, "coverage_pct": 0.0}

    held = state_df[state_df["Controvalore"] > 0]
    tickers = [str(t) for t in held["Ticker"]]
    exposures = compute_instrument_bucket_exposures(data, held_tickers=set(tickers))
    rows_by_ticker = held.set_index("Ticker").to_dict(orient="index")
    items_by_ticker = {
        str(item.get("ticker") or "").strip().upper(): item
        for item in data.get("strumenti", []) or []
    }

    raw: list[dict[str, Any]] = []
    for ticker in tickers:
        if ticker in exclude_tickers:
            continue
        if resolve_instrument_no_sell(data, ticker):
            continue
        frac = float(exposures.get(ticker, {}).get(bucket, 0.0))
        if frac <= 0:
            continue
        row = rows_by_ticker[ticker]
        contributo_eur = frac * float(row.get("Controvalore", 0.0))
        if contributo_eur <= 0:
            continue
        pl_eur = float(row.get("P/L €", 0.0))
        item = items_by_ticker.get(ticker, {"ticker": ticker})
        is_gov_bond = not bool(infer_sator_metadata(item, True).get("pac_enabled", True))
        raw.append({
            "ticker": ticker,
            "name": row.get("Strumento", ticker),
            "contributo_eur": contributo_eur,
            "pl_eur": pl_eur,
            "is_minusvalenza": pl_eur < 0,
            "is_gov_bond": is_gov_bond,
        })

    raw.sort(key=lambda c: (-round(c["contributo_eur"] / _TIE_BREAK_EUR), c["pl_eur"]))

    candidates: list[dict[str, Any]] = []
    covered = 0.0
    residuo = surplus_eur
    for c in raw:
        if residuo <= 0:
            break
        quota = min(c["contributo_eur"], residuo)
        if quota < _MATERIALITY_EUR and residuo > _MATERIALITY_EUR:
            continue
        candidates.append({**c, "quota_suggerita_eur": quota})
        covered += quota
        residuo -= quota

    coverage_pct = min(1.0, covered / surplus_eur) if surplus_eur > 0 else 0.0
    return {"candidates": candidates, "covered_eur": covered, "coverage_pct": coverage_pct}
