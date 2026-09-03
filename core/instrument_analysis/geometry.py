"""Punteggio di somiglianza di forma tra due serie storiche (0-100),
porting senza pandas di POC17.2 `_shape_similarity`/`geometry_metrics`
(righe 2367/2446 di
`HANDOFF_PROGRAMMATORE_BENCHMARK_CDS/reference/poc17_4_engine_VALIDATED_REFERENCE.py`).
Nessuna dipendenza da pandas — coerente con `series.py`, che la esclude
esplicitamente ("per restare leggero"). Omesso il tentativo di
allineamento a +/-1 giorno di lag di POC (i dati di questo progetto sono
gia' allineati per data di chiusura Borsa Italiana/Yahoo — vedi Task L2
del piano `docs/superpowers/plans/2026-09-01-instrument-analysis-cds-benchmark.md`,
da riaprire come task dedicato se il quality gate del Task L4 mostra falsi
negativi da questo)."""
from __future__ import annotations

import math

from core.instrument_analysis.series import align_series

_MAX_OBS = 252
_HORIZONS = (5, 10, 20, 60)
_SLOPE_WINDOW = 10


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _pearson_corr(a: list[float], b: list[float]) -> float | None:
    if len(a) < 8 or len(a) != len(b):
        return None
    ma, mb = _mean(a), _mean(b)
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((x - mb) ** 2 for x in b)
    if va == 0.0 or vb == 0.0:
        return None
    cov = sum((a[i] - ma) * (b[i] - mb) for i in range(len(a)))
    return cov / math.sqrt(va * vb)


def _rolling_slopes(values: list[float], window: int = _SLOPE_WINDOW) -> list[float]:
    x = list(range(window))
    xm = _mean(x)
    den = sum((xi - xm) ** 2 for xi in x)
    out: list[float] = []
    for i in range(window - 1, len(values)):
        y = values[i - window + 1: i + 1]
        ym = _mean(y)
        out.append(sum((x[j] - xm) * (y[j] - ym) for j in range(window)) / den)
    return out


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def geometry_score(instrument_series: dict[str, float], candidate_series: dict[str, float]) -> tuple[float, int]:
    """Ritorna (punteggio 0-100, n osservazioni comuni). (0.0, n) se meno
    di 5 date comuni; (0.0, 0) se le serie non condividono nessuna data."""
    if not instrument_series or not candidate_series:
        return 0.0, 0

    aligned_a, aligned_b = align_series(instrument_series, candidate_series)
    common_dates = sorted(set(aligned_a) & set(aligned_b))
    common_dates = common_dates[-_MAX_OBS:]
    n = len(common_dates)
    if n < 5:
        return 0.0, n

    a = [aligned_a[d] for d in common_dates]
    b = [aligned_b[d] for d in common_dates]
    base_a, base_b = a[0], b[0]
    if not base_a or not base_b:
        return 0.0, n
    na = [v / base_a * 100.0 for v in a]
    nb = [v / base_b * 100.0 for v in b]

    # 1) Path distance in percentage points, scalata sul movimento reale
    #    dello strumento (curve piatte/volatili giudicate su base comparabile).
    path_gap = [abs(na[i] - nb[i]) for i in range(n)]
    mae = _mean(path_gap)
    rmse = math.sqrt(_mean([g ** 2 for g in path_gap]))
    movement = max(4.0, max(na) - min(na))
    path_fit = _clamp01(1.0 - min(1.0, rmse / (0.55 * movement + 2.0)))
    mae_fit = _clamp01(1.0 - min(1.0, mae / (0.40 * movement + 1.5)))

    # 2) Scostamento terminale (rendimento cumulato finale).
    terminal_gap = abs(na[-1] - nb[-1])
    terminal_fit = _clamp01(1.0 - min(1.0, terminal_gap / (0.50 * movement + 3.0)))

    # 3) Comportamento del drawdown.
    running_max_a = running_max_b = float("-inf")
    dd_sq_sum = 0.0
    for i in range(n):
        running_max_a = max(running_max_a, na[i])
        running_max_b = max(running_max_b, nb[i])
        dda = na[i] / running_max_a - 1.0
        ddb = nb[i] / running_max_b - 1.0
        dd_sq_sum += (dda - ddb) ** 2
    dd_rmse = math.sqrt(dd_sq_sum / n)
    dd_fit = _clamp01(1.0 - min(1.0, dd_rmse / 0.10))

    # 4) Movimento/direzione multi-orizzonte (5/10/20/60 osservazioni).
    horizon_scores: list[float] = []
    direction_scores: list[float] = []
    for h in _HORIZONS:
        if n <= h + 3:
            continue
        ra = [na[i] / na[i - h] - 1.0 for i in range(h, n)]
        rb = [nb[i] / nb[i - h] - 1.0 for i in range(h, n)]
        if len(ra) < 4:
            continue
        c = _pearson_corr(ra, rb)
        horizon_scores.append(max(0.0, c or 0.0))
        direction_scores.append(_mean([1.0 if (ra[i] >= 0) == (rb[i] >= 0) else 0.0 for i in range(len(ra))]))
    horizon_fit = _mean(horizon_scores) if horizon_scores else 0.0
    direction_fit = _mean(direction_scores) if direction_scores else 0.5

    # 5) Pendenza locale dei percorsi normalizzati (scala log).
    log_na = [math.log(max(v, 1e-12)) for v in na]
    log_nb = [math.log(max(v, 1e-12)) for v in nb]
    slope_corr = _pearson_corr(_rolling_slopes(log_na), _rolling_slopes(log_nb))
    slope_fit = max(0.0, slope_corr or 0.0)

    score = 100.0 * (
        0.25 * path_fit
        + 0.15 * mae_fit
        + 0.15 * terminal_fit
        + 0.10 * dd_fit
        + 0.15 * horizon_fit
        + 0.10 * direction_fit
        + 0.10 * slope_fit
    )
    return max(0.0, min(100.0, score)), n
