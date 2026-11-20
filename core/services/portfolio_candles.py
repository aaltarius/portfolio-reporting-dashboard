"""Candele giornaliere del P/L delle posizioni aperte dalle letture di prezzo (TM-05).

Funzione pura: nessuna dipendenza da Streamlit né dall'archivio (le letture si passano). Nessuna formula nuova:
le quantità di ogni giorno si ricostruiscono con la stessa funzione di replay degli eventi usata dallo storico del
portafoglio (`core.finance._apply_event_to_pos`), quindi una compravendita a metà periodo non sporca la candela
(la quantità cambia fra un giorno e l'altro, mai dentro il giorno: nel giorno dell'operazione vale la quantità di fine
giornata, come nello storico).

Il valore tracciato è il P/L non realizzato (valore di mercato − costo di carico delle posizioni aperte): un acquisto o
una vendita cambia insieme quantità e costo, quindi non sposta la serie; si muove solo con i prezzi.

Per ogni giorno con almeno una lettura:
- apertura = P/L delle posizioni ai prezzi dell'ultima chiusura nota prima di quel giorno (storico prezzi), come in
  un grafico giornaliero senza «buchi»; per uno strumento mai quotato prima vale la sua prima lettura del giorno;
- a ogni istante in cui arriva una lettura il P/L si ricalcola con l'ultimo prezzo noto di ogni strumento;
- chiusura = valore all'ultimo istante; massimo e minimo comprendono apertura, chiusura e tutti gli istanti.
Contano solo gli strumenti posseduti quel giorno; liquidità e P/L realizzato sono esclusi (il grafico mostra il mercato).
Gli strumenti con un solo valore al giorno (fondi a NAV) restano costanti: non producono movimento intraday.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from typing import Any, Iterable

from core.finance import _apply_event_to_pos
from persistence.storage import _event_sort_key, get_registro_eventi

_QTY_EPS = 1e-9


def _price_before(storico: dict[str, dict[str, Any]], days_sorted: list[str], ticker: str, day: str,
                  *, inclusive: bool = False) -> float | None:
    """Ultimo prezzo valido nello storico prima di `day` (con `inclusive`, anche in quel giorno)."""
    pos = (bisect_right(days_sorted, day) if inclusive else bisect_left(days_sorted, day)) - 1
    while pos >= 0:
        raw = (storico.get(days_sorted[pos]) or {}).get(ticker)
        try:
            value = float(raw)
        except (TypeError, ValueError):
            value = 0.0
        if value > 0:
            return value
        pos -= 1
    return None


def build_portfolio_candles(
    readings: Iterable[tuple[str, str, float]],
    data: dict[str, Any] | None,
    *,
    max_days: int = 30,
) -> list[dict[str, Any]]:
    """Candele (dict con day, open, high, low, close, n) per i soli giorni con letture, dalle più vecchie."""
    data = data or {}
    by_day: dict[str, list[tuple[str, str, float]]] = {}
    for ticker, ts, price in readings:
        by_day.setdefault(str(ts)[:10], []).append((str(ticker), str(ts), float(price)))
    if not by_day:
        return []
    days = sorted(by_day)[-max(1, int(max_days)):]
    first_day = days[0]

    storico = data.get("storico_prezzi") or {}
    days_sorted = sorted(d for d in storico if isinstance(d, str) and len(d) == 10)
    events = sorted(get_registro_eventi(data), key=_event_sort_key)

    pos: dict[str, dict[str, float]] = {}
    cash, rg, rn, tx = 0.0, 0.0, 0.0, 0.0
    idx = 0
    # Gli eventi precedenti al primo giorno entrano nello stato prima di cominciare: stesso replay dello storico.
    candles: list[dict[str, Any]] = []
    for day in days:
        while idx < len(events) and str(events[idx].get("data", "")) <= day:
            cash, rg, rn, tx = _apply_event_to_pos(events[idx], pos, cash, rg, rn, tx)
            idx += 1
        qty = {tk: float(st.get("qty", 0.0) or 0.0) for tk, st in pos.items()}
        held = {tk for tk, q in qty.items() if q > _QTY_EPS}
        day_readings = sorted((r for r in by_day[day] if r[0] in held), key=lambda r: (r[1], r[0]))
        if not held or not day_readings:
            continue

        cur: dict[str, float] = {}
        for tk in held:
            base = _price_before(storico, days_sorted, tk, day)
            if base is not None:
                cur[tk] = base
        for tk, _, price in day_readings:       # strumento mai quotato prima: parte dalla prima lettura del giorno
            cur.setdefault(tk, price)
        for tk in held:                          # acquistato oggi e senza letture: prezzo dello storico del giorno, poi costo medio
            if tk not in cur:
                known = _price_before(storico, days_sorted, tk, day, inclusive=True)
                if known is None:
                    known = float(pos[tk].get("cost", 0.0) or 0.0) / qty[tk]
                cur[tk] = known

        cost_total = sum(float(pos[tk].get("cost", 0.0) or 0.0) for tk in held)

        def value() -> float:
            return sum(qty[tk] * cur[tk] for tk in held if tk in cur) - cost_total

        open_v = value()
        values = [open_v]
        instants = 0
        i = 0
        while i < len(day_readings):
            ts = day_readings[i][1]
            while i < len(day_readings) and day_readings[i][1] == ts:
                cur[day_readings[i][0]] = day_readings[i][2]
                i += 1
            values.append(value())
            instants += 1
        candles.append({"day": day, "open": open_v, "high": max(values), "low": min(values), "close": values[-1], "n": instants})
    return candles
