"""Costruzione della curva composita per strumenti multi-asset. Max 2
gambe, pesi arrotondati a step 5% (spec sezione H/handoff)."""
from __future__ import annotations

from core.instrument_analysis.contracts import BenchmarkComponent, OperationalKind


def _round_to_step(value: float, step: float = 5.0) -> float:
    return round(value / step) * step


def build_composite(legs: list[tuple[str, str, float]]) -> list[BenchmarkComponent]:
    if len(legs) > 2:
        raise ValueError(f"Composite benchmark supports at most 2 legs, got {len(legs)}")
    if not legs:
        return []

    total_weight = sum(weight for _, _, weight in legs)
    if total_weight <= 0:
        raise ValueError("Composite legs must have a positive total weight")

    raw_percentages = [(series_id, label, (weight / total_weight) * 100.0) for series_id, label, weight in legs]

    if len(raw_percentages) == 1:
        series_id, label, _ = raw_percentages[0]
        return [BenchmarkComponent(series_id=series_id, label=label, weight_pct=100.0,
                                    kind=OperationalKind.DIRECT_UNDERLYING)]

    (id_a, label_a, pct_a), (id_b, label_b, pct_b) = raw_percentages
    rounded_a = _round_to_step(pct_a)
    rounded_b = 100.0 - rounded_a  # garantisce somma esatta a 100

    return [
        BenchmarkComponent(series_id=id_a, label=label_a, weight_pct=rounded_a, kind=OperationalKind.COMPOSITE),
        BenchmarkComponent(series_id=id_b, label=label_b, weight_pct=rounded_b, kind=OperationalKind.COMPOSITE),
    ]
