"""«P/L del periodo» (PL-01): serie giornaliere per strumento da cui la pagina ricava il P/L tra due date qualunque.

Motore puro (nessuna dipendenza da Streamlit, nessuna scrittura). Per ogni strumento con almeno un evento e per ogni
giorno di Borsa, dal primo evento in poi, restituisce tre serie cumulative:

- `total`  = P/L totale dall'inizio = valore di mercato − costo di carico + P/L realizzato netto + proventi netti
             (cedole e dividendi). Una differenza fra due date è il P/L di quel periodo: acquisti e vendite non lo
             sporcano perché spostano insieme quantità e costo.
- `value`  = valore di mercato delle quote possedute a fine giornata.
- `bought` = acquisti lordi cumulati (quantità × prezzo + commissioni + imposte).
- `realized` e `income` = le due parti realizzate di `total` (il resto è la variazione dei prezzi sulle quote in portafoglio).
La percentuale del periodo si calcola nella pagina come P/L / (valore a inizio periodo + acquisti del periodo).

Stesso replay degli eventi del resto dell'app (`core.finance._apply_event_to_pos`); prezzi dallo storico con ultima
chiusura nota (la valorizzazione di portafoglio usa la stessa convenzione), costo medio per le quote senza prezzo.
"""
from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from datetime import date
from typing import Any

_QTY_EPS = 1e-9


@dataclass(frozen=True)
class PLSeries:
    ticker: str
    name: str
    tipo: str
    category: str
    status: str            # "posseduto" | "chiuso"
    total: list[float]
    value: list[float]
    bought: list[float]
    realized: list[float]   # P/L realizzato netto cumulato (vendite e rimborsi)
    income: list[float]     # proventi netti cumulati (cedole e dividendi)
    # operazioni (indice del giorno, tipo, quantità, importo): "A" acquisto, "V" vendita, "R" rimborso, "C" cedola/dividendo
    operations: list[tuple[int, str, float, float]] = field(default_factory=list)


@dataclass(frozen=True)
class PLPeriodData:
    dates: list[str]
    series: list[PLSeries]
    # versamenti netti cumulati (VERSAMENTO − PRELIEVO), per giorno: denominatore del total return come nel resto dell'app
    deposits: list[float] = field(default_factory=list)


def _valid_price(raw: Any) -> float | None:
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) and v > 0 else None


def _is_weekday(day: str) -> bool:
    try:
        return date.fromisoformat(day).weekday() < 5
    except ValueError:
        return False


def _f(value: Any) -> float:
    try:
        v = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return v if math.isfinite(v) else 0.0


def build_pl_periodo(data: dict[str, Any]) -> PLPeriodData:
    from core.finance import _apply_event_to_pos
    from persistence.storage import get_registro_eventi, macro_cat

    events = [e for e in get_registro_eventi(data) if str(e.get("data") or "")[:10]]
    traded = {str(e.get("ticker")) for e in events if e.get("ticker")
              and e.get("tipo_evento") in {"ACQUISTO", "VENDITA", "RIMBORSO A SCADENZA", "CEDOLA", "DIVIDENDO"}}
    if not events or not traded:
        return PLPeriodData([], [])
    first_day = min(str(e["data"])[:10] for e in events if str(e.get("ticker")) in traded)

    storico = data.get("storico_prezzi") or {}
    dates = sorted(d for d in {str(k)[:10] for k in storico} if d >= first_day and _is_weekday(d))
    if not dates:
        return PLPeriodData([], [])

    prices: dict[str, tuple[list[str], list[float]]] = {}
    for tk in traded:
        pts = sorted((str(k)[:10], _valid_price((v or {}).get(tk))) for k, v in storico.items())
        pts = [(d, p) for d, p in pts if p is not None]
        prices[tk] = ([d for d, _ in pts], [p for _, p in pts])

    info = {str(s.get("ticker")): s for s in (data.get("strumenti") or []) if s.get("ticker")}
    pos: dict[str, dict[str, float]] = {}
    income: dict[str, float] = {tk: 0.0 for tk in traded}
    bought_cum: dict[str, float] = {tk: 0.0 for tk in traded}
    cash = rg = rn = tx = 0.0
    out = {tk: ([], [], [], [], []) for tk in sorted(traded)}
    ops: dict[str, list[tuple[int, str, float, float]]] = {tk: [] for tk in out}
    kinds = {"ACQUISTO": "A", "VENDITA": "V", "RIMBORSO A SCADENZA": "R", "CEDOLA": "C", "DIVIDENDO": "C"}
    for ev in events:
        tk, kind = str(ev.get("ticker") or ""), kinds.get(str(ev.get("tipo_evento")))
        if tk not in ops or kind is None:
            continue
        gi = bisect_left(dates, str(ev["data"])[:10])
        if gi >= len(dates):
            continue
        qty = _f(ev.get("quantita"))
        amount = _f(ev.get("importo_netto")) if kind == "C" else (qty * _f(ev.get("prezzo_unitario")) or _f(ev.get("importo_netto")))
        ops[tk].append((gi, kind, round(qty, 4) if kind != "C" else 0.0, round(abs(amount), 2)))
    dep_events = sorted((str(e["data"])[:10], (abs(_f(e.get("importo_netto")) or _f(e.get("importo_lordo")))
                                               * (1 if e.get("tipo_evento") == "VERSAMENTO" else -1)))
                        for e in events if e.get("tipo_evento") in {"VERSAMENTO", "PRELIEVO"})
    deposits: list[float] = []
    dep_idx, dep_cum = 0, 0.0
    idx = 0
    for day in dates:
        while dep_idx < len(dep_events) and dep_events[dep_idx][0] <= day:
            dep_cum += dep_events[dep_idx][1]
            dep_idx += 1
        deposits.append(round(dep_cum, 2))
        while idx < len(events) and str(events[idx].get("data"))[:10] <= day:
            ev = events[idx]
            tk = str(ev.get("ticker") or "")
            if tk in traded:
                cash, rg, rn, tx = _apply_event_to_pos(ev, pos, cash, rg, rn, tx)
                if ev.get("tipo_evento") == "ACQUISTO":
                    bought_cum[tk] += (_f(ev.get("quantita")) * _f(ev.get("prezzo_unitario"))
                                       + _f(ev.get("commissioni")) + _f(ev.get("imposte")))
                elif ev.get("tipo_evento") in {"CEDOLA", "DIVIDENDO"}:
                    income[tk] += _f(ev.get("importo_netto"))
            idx += 1
        for tk in out:
            st = pos.get(tk) or {}
            qty, cost, realized = _f(st.get("qty")), _f(st.get("cost")), _f(st.get("realized_net"))
            held = qty > _QTY_EPS
            if held:
                ds, ps = prices[tk]
                i = bisect_right(ds, day) - 1
                price = ps[i] if i >= 0 else cost / qty
                value = qty * price
            else:
                value, cost = 0.0, 0.0
            total = value - cost + realized + income[tk]
            out[tk][0].append(round(total, 2))
            out[tk][1].append(round(value, 2))
            out[tk][2].append(round(bought_cum[tk], 2))
            out[tk][3].append(round(realized, 2))
            out[tk][4].append(round(income[tk], 2))

    series = []
    for tk, (total, value, bought, real, inc) in out.items():
        meta = info.get(tk, {})
        qty_end = _f((pos.get(tk) or {}).get("qty"))
        tipo = str(meta.get("tipo") or "")
        series.append(PLSeries(ticker=tk, name=str(meta.get("nome") or tk), tipo=tipo,
                               category=macro_cat(tipo), status="posseduto" if qty_end > _QTY_EPS else "chiuso",
                               total=total, value=value, bought=bought, realized=real, income=inc,
                               operations=ops[tk]))
    return PLPeriodData(dates, series, deposits)
