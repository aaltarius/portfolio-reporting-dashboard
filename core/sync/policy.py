"""Regola di scelta del prezzo: vince la data di mercato più recente tra le osservazioni valide.

Approvata dall'utente il 2026-11-08. Le osservazioni scartate non si perdono: ognuna esce con il suo
motivo (`rejected_with_reason`), così il prezzo applicato è sempre spiegabile. Soglie provvisorie
(da tarare sui dati reali): 10% per azioni/ETF, 3 punti percentuali del nominale per i titoli di Stato."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

MAX_MOVE_PCT = 0.10
MAX_MOVE_BOND_POINTS = 3.0
SOURCE_PRIORITY = {"desktop": 2, "cloud": 1}


@dataclass(frozen=True)
class Observation:
    source: str
    symbol: str
    price: float
    currency: str
    market_time: str
    fetched_at: str


@dataclass(frozen=True)
class Rejection:
    observation: Observation
    reason: str


@dataclass
class Choice:
    applied: Observation | None
    rejected_with_reason: list[Rejection] = field(default_factory=list)

    @property
    def rejected(self) -> list[Observation]:
        return [r.observation for r in self.rejected_with_reason]


def _when(text: str) -> datetime:
    try:
        d = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _key(o: Observation):
    return (_when(o.market_time), SOURCE_PRIORITY.get(o.source, 0), _when(o.fetched_at), o.price, o.source)


def choose_price(observations: list[Observation], *, expected_symbol: str, kind: str = "equity") -> Choice:
    reference = max((o for o in observations if o.source == "desktop"), key=_key, default=None)
    valid: list[Observation] = []
    rejected: list[Rejection] = []
    for o in observations:
        reason = None
        if not (isinstance(o.price, (int, float)) and math.isfinite(o.price) and o.price > 0):
            reason = "invalid_price"
        elif o.symbol != expected_symbol:
            reason = "symbol_mismatch"
        elif o.currency != "EUR":
            reason = "currency_not_eur"
        elif reference is not None and o is not reference:
            if _when(o.market_time) < _when(reference.market_time):
                reason = "older_than_desktop"
            elif kind == "bond":
                if abs(o.price - reference.price) > MAX_MOVE_BOND_POINTS:
                    reason = "anomalous_move"
            elif reference.price > 0 and abs(o.price / reference.price - 1) > MAX_MOVE_PCT:
                reason = "anomalous_move"
        if reason:
            rejected.append(Rejection(o, reason))
        else:
            valid.append(o)
    if not valid:
        return Choice(None, rejected)
    best = max(valid, key=_key)
    rejected += [Rejection(o, "superseded") for o in valid if o is not best]
    return Choice(best, rejected)
