"""Freshness policy condivisa da resolver e centro benchmark.

Non considera vigente una serie ferma molti giorni fa: il dato storico resta
in SQLite ma non e' autorizzato come riferimento operativo corrente.
La soglia di 10 giorni calendario tollera weekend/festivita senza proclamare
che una serie con data recente sia necessariamente di buona qualita'.

La soglia segnala, non nasconde (BM-14): una serie ferma da piu' di 10 giorni resta utilizzabile e viene
mostrata con la data dell'ultimo dato; sparisce soltanto se manca, e' troppo corta o non e' in euro.
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


def staleness(series: Mapping[str, float] | None, *, as_of: date | None = None,
              max_age_days: int = MAX_REFERENCE_AGE_DAYS) -> dict:
    """Ultimo giorno di dati, eta' in giorni e se supera la soglia (serie vuota: nessuna data, non stale)."""
    if not series:
        return {"last_date": "", "age_days": None, "stale": False}
    last = max(series)
    age = age_days(last, as_of=as_of)
    return {"last_date": str(last)[:10], "age_days": age, "stale": age is None or age > max_age_days}


def is_current_series(series: Mapping[str, float] | None, *, as_of: date | None = None,
                      max_age_days: int = MAX_REFERENCE_AGE_DAYS) -> bool:
    if not series:
        return False
    days = age_days(max(series), as_of=as_of)
    return days is not None and 0 <= days <= max_age_days
