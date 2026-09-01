"""Normalizzazione di serie storiche: base 100, allineamento date comuni.
Nessuna dipendenza da pandas per restare leggero — dict[str_date, float]
ordinabile per chiave e' sufficiente per queste operazioni."""
from __future__ import annotations


def rebase_to_100(history: dict[str, float]) -> dict[str, float]:
    if not history:
        return {}
    ordered_dates = sorted(history.keys())
    base_value = history[ordered_dates[0]]
    if not base_value:
        return {}
    return {date: (history[date] / base_value) * 100.0 for date in ordered_dates}


def align_series(a: dict[str, float], b: dict[str, float]) -> tuple[dict[str, float], dict[str, float]]:
    common_dates = set(a.keys()) & set(b.keys())
    aligned_a = {date: a[date] for date in common_dates}
    aligned_b = {date: b[date] for date in common_dates}
    return aligned_a, aligned_b
