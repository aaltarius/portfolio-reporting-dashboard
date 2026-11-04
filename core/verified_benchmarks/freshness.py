"""Freshness policy condivisa da resolver e centro benchmark.

Non considera vigente una serie ferma molti giorni fa: il dato storico resta
in SQLite ma non e' autorizzato come riferimento operativo corrente.
La soglia di 10 giorni calendario tollera weekend/festivita senza proclamare
che una serie con data recente sia necessariamente di buona qualita'.
"""
from __future__ import annotations
from datetime import date
from typing import Mapping

MAX_REFERENCE_AGE_DAYS = 10


def age_days(last_date: str | None, *, as_of: date | None = None) -> int | None:
    if not last_date:
        return None
    try:
        return (as_of or date.today()).toordinal() - date.fromisoformat(str(last_date)[:10]).toordinal()
    except (TypeError, ValueError, OverflowError):
        return None


def is_current_series(series: Mapping[str, float] | None, *, as_of: date | None = None,
                      max_age_days: int = MAX_REFERENCE_AGE_DAYS) -> bool:
    if not series:
        return False
    days = age_days(max(series), as_of=as_of)
    return days is not None and 0 <= days <= max_age_days
