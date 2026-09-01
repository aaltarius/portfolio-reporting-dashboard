"""Punteggi quantitativi. benchmark_score() e' l'UNICA implementazione
della formula 55/35/10 nel repo (spec sezione 10) — l'harness di test
(Fase E) la importa da qui, non la ridefinisce."""
from __future__ import annotations


def coverage_score(observations: int, expected: int = 252) -> float:
    if expected <= 0:
        return 0.0
    return min(100.0, 100.0 * observations / expected)


def benchmark_score(semantic: float, geometry: float, coverage: float) -> float:
    return 0.55 * semantic + 0.35 * geometry + 0.10 * coverage
