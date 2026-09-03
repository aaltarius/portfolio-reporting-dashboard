"""Costruzione della curva total-return sintetica duration-matched per
obbligazioni sovrane singole (BTP) — Task R, 2026-09-03, handoff sezione I
"BOND/BTP" ("mai usare ETF proxy... costruire curve duration-specific con
fonti ufficiali"). Porta il PRINCIPIO di `synthetic_tr` dal riferimento
validato (`poc17_4_engine_VALIDATED_REFERENCE.py`, riga 2086): carry meno
duration*variazione di rendimento, piu' un termine di convessita' — la
stessa approssimazione standard usata per stimare il rendimento totale di
un'obbligazione a partire dalla sola curva dei rendimenti, senza serie
storica del prezzo. Nessuna chiamata di rete qui: puro calcolo su
osservazioni gia' scaricate (`reference_data/rates.py`)."""
from __future__ import annotations


def synthetic_total_return(yield_observations: dict[str, float], duration_years: float) -> dict[str, float]:
    """`yield_observations`: date ISO -> rendimento in percentuale (es. 3.01
    per 3,01%). Ritorna un indice total-return sintetico ribasato a 100
    sulla prima osservazione. Richiede almeno 2 osservazioni ordinabili per
    data; ritorna {} altrimenti (mai una curva a un solo punto)."""
    dates = sorted(yield_observations)
    if len(dates) < 2:
        return {}

    from datetime import date as _date

    duration = max(0.0, float(duration_years))
    convexity_term = 0.70 * duration * duration

    index: dict[str, float] = {}
    level = 100.0
    prev_date = None
    prev_yield = None
    for iso_date in dates:
        current_yield = float(yield_observations[iso_date])
        if prev_date is None:
            index[iso_date] = level
            prev_date, prev_yield = iso_date, current_yield
            continue
        days = max(1, (_date.fromisoformat(iso_date) - _date.fromisoformat(prev_date)).days)
        carry = (prev_yield / 100.0) * days / 365.0
        delta_yield = (current_yield - prev_yield) / 100.0
        period_return = carry - duration * delta_yield + 0.5 * convexity_term * (delta_yield ** 2)
        level *= (1.0 + period_return)
        index[iso_date] = level
        prev_date, prev_yield = iso_date, current_yield
    return index
