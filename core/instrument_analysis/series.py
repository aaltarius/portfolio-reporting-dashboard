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


def blend_series(
    series_a: dict[str, float], weight_a: float,
    series_b: dict[str, float], weight_b: float,
) -> dict[str, float]:
    """Curva pesata a 2 gambe (Task Q — composito C/D/S, porting del
    principio di `_mixed_role_composite` in
    `poc17_4_engine_VALIDATED_REFERENCE.py`, riga 3558): allinea le date
    comuni, ribasa ciascuna gamba a 100 sulla prima data comune, somma
    pesata. `weight_a`/`weight_b` sono frazioni (non devono sommare
    esattamente a 1 — vengono normalizzate). Dict vuoto se le due serie non
    condividono nessuna data o una base e' zero."""
    aligned_a, aligned_b = align_series(series_a, series_b)
    common_dates = sorted(set(aligned_a) & set(aligned_b))
    if not common_dates:
        return {}
    base_a = aligned_a[common_dates[0]]
    base_b = aligned_b[common_dates[0]]
    if not base_a or not base_b:
        return {}
    total_weight = weight_a + weight_b
    if total_weight <= 0:
        return {}
    wa, wb = weight_a / total_weight, weight_b / total_weight
    return {
        date: wa * (aligned_a[date] / base_a * 100.0) + wb * (aligned_b[date] / base_b * 100.0)
        for date in common_dates
    }
