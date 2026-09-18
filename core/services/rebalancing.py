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

_BUCKETS = ("Core", "Difensivo", "Satellite")


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
