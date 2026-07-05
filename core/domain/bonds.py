"""core/domain/bonds.py — Calcoli finanziari obbligazionari (YTM, Duration)."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def _future_cashflows(
    nominale: float,
    cedola_perc: float,
    scadenza: pd.Timestamp,
    prima_cedola: pd.Timestamp,
    freq: int,
    months_per_payment: int,
    today: pd.Timestamp,
) -> list[tuple[float, float]]:
    """Restituisce lista di (anni_da_oggi, importo) per tutti i flussi futuri."""
    coupon_per_period = cedola_perc / 100.0 * nominale / freq
    cashflows: list[tuple[float, float]] = []
    current = prima_cedola.normalize()
    while current <= scadenza:
        if current > today:
            years = (current - today).days / 365.25
            cashflows.append((years, coupon_per_period))
        current = (current + pd.DateOffset(months=months_per_payment)).normalize()
    years_to_maturity = (scadenza - today).days / 365.25
    if years_to_maturity > 0:
        cashflows.append((years_to_maturity, nominale))
    return cashflows


def calc_ytm_and_duration(
    strumento: dict[str, Any],
    today: pd.Timestamp | None = None,
) -> tuple[float | None, float | None]:
    """
    Calcola YTM lordo annualizzato e Duration Modificata (anni) per un BTP.

    Restituisce (ytm, modified_duration). Entrambi None se non calcolabili
    (scaduto, dati mancanti, bisection non converge).

    YTM convention: tasso continuo-equivalente annuo che uguaglia il PV dei
    flussi futuri (cedole + rimborso) al prezzo di mercato corrente.
    """
    from core.domain.calendar import CEDOLA_FREQ_MONTHS, CEDOLA_FREQ_PAYMENTS

    today = pd.Timestamp.today().normalize() if today is None else pd.Timestamp(today).normalize()

    try:
        prezzo = float(strumento.get("prezzo") or 0)
        nominale = float(strumento.get("nominale") or 100)
        cedola_perc = float(strumento.get("cedola_perc") or 0)
        from core.domain.calendar import _to_ts
        scadenza_ts = _to_ts(strumento["scadenza"])
        if scadenza_ts is None:
            return None, None
        scadenza = scadenza_ts.normalize()
        prima_cedola_raw = (
            strumento.get("prima_cedola")
            or strumento.get("data_origine")
            or strumento.get("data_acquisto")
        )
        prima_cedola_ts = _to_ts(prima_cedola_raw) if prima_cedola_raw else None
        prima_cedola = prima_cedola_ts.normalize() if prima_cedola_ts is not None else today
        cedola_freq_str = str(strumento.get("cedola_frequenza") or "annuale").strip().lower()
    except Exception:
        return None, None

    if prezzo <= 0 or nominale <= 0 or cedola_perc <= 0:
        return None, None
    if scadenza <= today:
        return None, None

    freq = CEDOLA_FREQ_PAYMENTS.get(cedola_freq_str, 1)
    months = CEDOLA_FREQ_MONTHS.get(cedola_freq_str, 12)
    cashflows = _future_cashflows(nominale, cedola_perc, scadenza, prima_cedola, freq, months, today)
    if not cashflows:
        return None, None

    def npv(rate: float) -> float:
        try:
            return sum(cf / (1.0 + rate) ** t for t, cf in cashflows) - prezzo
        except (ZeroDivisionError, OverflowError):
            return float("nan")

    lo, hi = -0.9999, 5.0
    npv_lo, npv_hi = npv(lo), npv(hi)
    if not (np.isfinite(npv_lo) and np.isfinite(npv_hi)):
        return None, None
    if npv_lo * npv_hi > 0:
        return None, None

    for _ in range(200):
        mid = (lo + hi) / 2.0
        if abs(hi - lo) < 1e-9:
            break
        val = npv(mid)
        if not np.isfinite(val):
            return None, None
        if npv(lo) * val < 0:
            hi = mid
        else:
            lo = mid

    ytm = (lo + hi) / 2.0
    if not np.isfinite(ytm) or ytm < -0.99:
        return None, None

    # Macaulay Duration = Σ(t × PV_t) / Prezzo
    total_pv = 0.0
    weighted_pv = 0.0
    for t, cf in cashflows:
        pv = cf / (1.0 + ytm) ** t
        total_pv += pv
        weighted_pv += t * pv

    if total_pv <= 0:
        return ytm, None

    macaulay = weighted_pv / total_pv
    # Modified Duration = Macaulay / (1 + YTM/freq)
    modified = macaulay / (1.0 + ytm / freq)
    return ytm, modified
