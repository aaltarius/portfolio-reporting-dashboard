"""«A parità di investimento» (PA-01): confronto, a parità di capitale e tra due date, degli strumenti del portafoglio.

Motore puro: nessuna dipendenza da Streamlit, nessuna scrittura, nessuna rete. Legge solo `data["storico_prezzi"]`
grezzo (mai il frame con `ffill`): per ogni estremo usa l'ultima chiusura entro la data richiesta, con uno scarto
massimo `MAX_GAP_DAYS`. Tutto in EUR, lordo fiscale e senza costi. Specifica:
docs/superpowers/specs/2026-11-22-parita-di-investimento-design.md.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

#: Scarto massimo, in giorni, fra la data richiesta e l'ultima chiusura utilizzabile.
MAX_GAP_DAYS: int = 7


def _to_date(value: Any) -> date | None:
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _valid_price(raw: Any) -> float | None:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value > 0 else None


def price_on_or_before(
    storico: dict[str, dict], ticker: str, day: str, max_gap_days: int = MAX_GAP_DAYS
) -> tuple[str, float] | None:
    """Ultima chiusura valida di `ticker` entro `day` (data effettiva, prezzo), oppure None.

    Ignora prezzi non positivi o non numerici; non usa mai date successive a `day`; oltre `max_gap_days`
    di scarto restituisce None (lo strumento va tra gli esclusi, non si inventa un rendimento)."""
    target = _to_date(day)
    if target is None:
        return None
    for key in sorted((k for k in storico if str(k)[:10] <= str(day)[:10]), reverse=True):
        price = _valid_price((storico.get(key) or {}).get(ticker))
        if price is None:
            continue
        found = _to_date(key)
        if found is None or (target - found).days > max_gap_days:
            return None
        return str(key)[:10], price
    return None


@dataclass(frozen=True)
class Simulation:
    qty: float
    invested: float
    residual: float
    final_value: float
    pl: float
    ret: float


def simulate(
    capital: float,
    start_price: float,
    end_price: float,
    *,
    whole_units: bool,
    decimals: int | None = None,
) -> Simulation | None:
    """Un solo acquisto di `capital` al prezzo iniziale, valorizzato al prezzo finale.

    `whole_units`: quote intere (ETF/ETC). Altrimenti frazionarie, arrotondate per difetto a `decimals`
    decimali se indicati (fondi) o senza arrotondamento (modalità teorica). None se il capitale non basta."""
    if not (math.isfinite(capital) and capital > 0 and start_price > 0 and end_price > 0):
        return None
    raw_qty = capital / start_price
    if whole_units:
        qty = float(math.floor(raw_qty + 1e-12))
    elif decimals is not None:
        factor = 10 ** decimals
        qty = math.floor(raw_qty * factor + 1e-9) / factor
    else:
        qty = raw_qty
    if qty <= 0:
        return None
    invested = qty * start_price
    residual = capital - invested
    final_value = qty * end_price + residual
    pl = final_value - capital
    return Simulation(qty=qty, invested=invested, residual=residual, final_value=final_value,
                      pl=pl, ret=pl / capital)


# ---------------- Capitale ----------------

@dataclass(frozen=True)
class ResolvedCapital:
    amount: float
    origin: str
    carry_cost: float | None
    usable: bool
    message: str


def _eur(value: float) -> str:
    return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " €"


def _replay(data: dict[str, Any], ticker: str, until_day: str) -> dict[str, float]:
    """Posizione di `ticker` dopo tutti gli eventi con data (solo giorno) ≤ `until_day`, con lo stesso replay del
    resto dell'app (`core.finance._apply_event_to_pos`): quote e costo di carico."""
    from core.finance import _apply_event_to_pos
    from persistence.storage import get_registro_eventi

    pos: dict[str, dict[str, float]] = {}
    cash = rg = rn = tx = 0.0
    for ev in get_registro_eventi(data):
        if str(ev.get("ticker") or "") != ticker or str(ev.get("data") or "")[:10] > until_day[:10]:
            continue
        cash, rg, rn, tx = _apply_event_to_pos(ev, pos, cash, rg, rn, tx)
    state = pos.get(ticker) or {}
    return {"qty": float(state.get("qty", 0.0) or 0.0), "cost": float(state.get("cost", 0.0) or 0.0)}


def resolve_capital(
    data: dict[str, Any], mode: str, *, amount: float | None, ticker: str | None, start: str, end: str
) -> ResolvedCapital:
    """Capitale C del confronto.

    - «libero»: importo scritto dall'utente (positivo e finito).
    - «speso»: A = somma degli acquisti dello strumento fino a `end` (quantità × prezzo + commissioni + imposte,
      la stessa base del costo di carico); B (`carry_cost`) = costo di carico delle quote ancora possedute a `end`.
    - «controvalore»: quote possedute a `start` × ultima chiusura entro `start`."""
    from persistence.storage import get_registro_eventi

    def fail(msg: str) -> ResolvedCapital:
        return ResolvedCapital(0.0, "", None, False, msg)

    if mode == "libero":
        try:
            value = float(amount)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return fail("Inserisci un importo in euro.")
        if not math.isfinite(value) or value <= 0:
            return fail("L'importo deve essere positivo.")
        return ResolvedCapital(value, f"{_eur(value)} inseriti a mano", None, True, "")

    if not ticker:
        return fail("Scegli uno strumento.")

    if mode == "speso":
        total = 0.0
        for ev in get_registro_eventi(data):
            if (str(ev.get("ticker") or "") == ticker and ev.get("tipo_evento") == "ACQUISTO"
                    and str(ev.get("data") or "")[:10] <= end[:10]):
                total += (float(ev.get("quantita") or 0) * float(ev.get("prezzo_unitario") or 0)
                          + float(ev.get("commissioni") or 0) + float(ev.get("imposte") or 0))
        if total <= 0:
            return fail(f"Nessun acquisto di {ticker} fino al {end[:10]}: importo zero, non utilizzabile.")
        carry = _replay(data, ticker, end)["cost"]
        return ResolvedCapital(total, f"{_eur(total)} = totale acquistato su {ticker} al {end[:10]}",
                               carry, True, "")

    if mode == "controvalore":
        qty = _replay(data, ticker, start)["qty"]
        found = price_on_or_before(data.get("storico_prezzi") or {}, ticker, start)
        if qty <= 1e-9:
            return fail(f"Il {start[:10]} non possedevi {ticker}: importo zero, non utilizzabile.")
        if found is None:
            return fail(f"Nessun prezzo di {ticker} utilizzabile al {start[:10]}.")
        value = qty * found[1]
        return ResolvedCapital(value, f"{_eur(value)} = controvalore di {ticker} al {found[0]}", None, True, "")

    return fail("Modalità del capitale non riconosciuta.")


# ---------------- Confronto ----------------

FUND_DECIMALS: int = 4
PERIMETER: frozenset[str] = frozenset({"ETF", "ETC", "FND"})


def classify(pl: float, ref_pl: float, capital: float) -> str:
    """Giudizio di un'alternativa rispetto al riferimento (regole numeriche, testo da modello fisso).

    Parità se |vantaggio| < max(0,5 €, 0,05% del capitale)."""
    adv = pl - ref_pl
    if abs(adv) < max(0.5, 0.0005 * capital):
        return "parità"
    if adv < 0:
        return "inferiore"
    if ref_pl < 0:
        return "in controtendenza positiva" if pl > 0 else "ha limitato la perdita"
    return "meglio del riferimento"


@dataclass(frozen=True)
class Row:
    ticker: str
    name: str
    category: str
    status: str
    distributes: bool
    start_date: str
    end_date: str
    start_price: float
    end_price: float
    qty: float
    invested: float
    residual: float
    final_value: float
    pl: float
    ret: float
    adv_eur: float | None
    adv_pp: float | None
    verdict: str
    is_reference: bool


@dataclass(frozen=True)
class Excluded:
    ticker: str
    name: str
    reason: str


@dataclass(frozen=True)
class Comparison:
    rows: list[Row]
    excluded: list[Excluded]
    reference: str
    reference_ok: bool
    capital: float
    coverage: tuple[int, int]
    paths: dict[str, list[tuple[str, float]]]
    error: str = ""


def _empty(error: str, reference: str = "", capital: float = 0.0) -> Comparison:
    return Comparison([], [], reference, False, capital, (0, 0), {}, error)


def _missing_reason(storico: dict, ticker: str, day: str, label: str) -> str:
    older = [k for k in storico if str(k)[:10] <= day[:10] and _valid_price((storico.get(k) or {}).get(ticker))]
    if not older:
        return f"storico non copre la {label} ({day[:10]})"
    return f"ultimo prezzo troppo vecchio alla {label} (più di {MAX_GAP_DAYS} giorni)"


def _status(statuses: dict, ticker: str) -> str:
    st = statuses.get(ticker)
    if st is None:
        return "osservato"
    if st.is_open:
        return "posseduto"
    return "chiuso" if st.has_any_event else "osservato"


def compare(
    data: dict[str, Any], *, start: str, end: str, capital: float, reference: str, whole_units: bool,
    max_gap_days: int = MAX_GAP_DAYS,
) -> Comparison:
    """Simula, per ogni strumento di ETF/ETC/fondi, un unico acquisto di `capital` a `start` valorizzato a `end`."""
    from core.domain.instrument_status import compute_instrument_statuses
    from persistence.storage import macro_cat

    d_start, d_end = _to_date(start), _to_date(end)
    if d_start is None or d_end is None:
        return _empty("Date non valide.", reference)
    if d_start >= d_end:
        return _empty("La data iniziale deve precedere la data finale.", reference)
    try:
        cap = float(capital)
    except (TypeError, ValueError):
        cap = float("nan")
    if not math.isfinite(cap) or cap <= 0:
        return _empty("Il capitale deve essere positivo.", reference)
    instruments = [s for s in (data.get("strumenti") or []) if s.get("ticker")]
    if reference not in {str(s["ticker"]) for s in instruments}:
        return _empty("Strumento di riferimento non trovato.", reference, cap)

    storico = data.get("storico_prezzi") or {}
    statuses = compute_instrument_statuses(data)
    raw_rows: list[dict[str, Any]] = []
    excluded: list[Excluded] = []

    for s in instruments:
        tk, name = str(s["ticker"]), str(s.get("nome") or s["ticker"])
        cat = macro_cat(str(s.get("tipo") or ""))
        if cat == "GOV":
            excluded.append(Excluded(tk, name, "BTP: non ancora supportato"))
            continue
        if cat not in PERIMETER:
            continue
        p0 = price_on_or_before(storico, tk, start, max_gap_days)
        p1 = price_on_or_before(storico, tk, end, max_gap_days)
        if p0 is None:
            excluded.append(Excluded(tk, name, _missing_reason(storico, tk, start, "data iniziale")))
            continue
        if p1 is None:
            excluded.append(Excluded(tk, name, _missing_reason(storico, tk, end, "data finale")))
            continue
        sim = simulate(cap, p0[1], p1[1], whole_units=(cat != "FND" and whole_units),
                       decimals=FUND_DECIMALS if cat == "FND" else None)
        if sim is None:
            excluded.append(Excluded(tk, name, "Capitale insufficiente"))
            continue
        raw_rows.append({"tk": tk, "name": name, "cat": cat, "p0": p0, "p1": p1, "sim": sim,
                         "dist": str(s.get("distribuzione") or "") == "Distribuzione"})

    ref_raw = next((r for r in raw_rows if r["tk"] == reference), None)
    ref_sim = ref_raw["sim"] if ref_raw else None
    rows: list[Row] = []
    for r in raw_rows:
        sim: Simulation = r["sim"]
        is_ref = r["tk"] == reference
        if ref_sim is None:
            adv_eur = adv_pp = None
            verdict = "dato insufficiente"
        elif is_ref:
            adv_eur = adv_pp = None
            verdict = "riferimento"
        else:
            adv_eur = sim.pl - ref_sim.pl
            adv_pp = (sim.ret - ref_sim.ret) * 100.0
            verdict = classify(sim.pl, ref_sim.pl, cap)
        rows.append(Row(
            ticker=r["tk"], name=r["name"], category=r["cat"], status=_status(statuses, r["tk"]),
            distributes=r["dist"], start_date=r["p0"][0], end_date=r["p1"][0], start_price=r["p0"][1],
            end_price=r["p1"][1], qty=sim.qty, invested=sim.invested, residual=sim.residual,
            final_value=sim.final_value, pl=sim.pl, ret=sim.ret, adv_eur=adv_eur, adv_pp=adv_pp,
            verdict=verdict, is_reference=is_ref))
    rows.sort(key=lambda x: x.pl, reverse=True)

    paths: dict[str, list[tuple[str, float]]] = {}
    for row in rows:
        pts: list[tuple[str, float]] = []
        for day in sorted(k for k in storico if row.start_date <= str(k)[:10] <= row.end_date):
            price = _valid_price((storico.get(day) or {}).get(row.ticker))
            if price is not None:
                pts.append((str(day)[:10], row.qty * price + row.residual))
        paths[row.ticker] = pts

    return Comparison(rows=rows, excluded=excluded, reference=reference, reference_ok=ref_sim is not None,
                      capital=cap, coverage=(len(rows), len(rows) + len(excluded)), paths=paths)
