"""core/domain/instrument_status.py — Stato calcolato degli strumenti:
aperto/chiuso, terminale (GOV rimborsato), osservazione prezzo.

Nessuno di questi stati va letto dal campo strumento['stato'], che non e'
mai mantenuto sincronizzato dal codice applicativo: tutto deriva sempre dal
registro eventi (vedi core/domain/positions.py::held_tickers)."""
from __future__ import annotations

from typing import Any, NamedTuple

from persistence.storage import get_registro_eventi, macro_cat
from core.domain.positions import held_tickers


class InstrumentStatus(NamedTuple):
    ticker: str
    is_open: bool
    is_terminal: bool
    closed_date: str | None
    closing_event_type: str | None
    osserva_prezzo: bool
    should_track_price: bool


def compute_instrument_statuses(data: dict[str, Any]) -> dict[str, InstrumentStatus]:
    """Calcola lo stato di ogni strumento in portafoglio (aperto/chiuso/
    terminale/osservato). Unica fonte per capire se un ticker va ancora
    tracciato per prezzo, sostituisce ogni lettura diretta di strumento['stato'].
    """
    open_tickers = held_tickers(data)
    eventi = get_registro_eventi(data)

    last_closing_event: dict[str, dict[str, Any]] = {}
    for ev in eventi:
        tk = str(ev.get("ticker") or "")
        tipo = str(ev.get("tipo_evento") or "")
        if tk and tipo in {"VENDITA", "RIMBORSO A SCADENZA"}:
            last_closing_event[tk] = ev  # eventi gia' ordinati cronologicamente da get_registro_eventi

    statuses: dict[str, InstrumentStatus] = {}
    for s in data.get("strumenti") or []:
        tk = str(s.get("ticker") or "")
        if not tk:
            continue
        is_open = tk in open_tickers
        closing_ev = last_closing_event.get(tk)
        closing_event_type = str(closing_ev.get("tipo_evento")) if closing_ev else None
        closed_date = str(closing_ev.get("data")) if closing_ev else None
        category = macro_cat(str(s.get("tipo") or ""))
        is_terminal = (not is_open) and category == "GOV" and closing_event_type == "RIMBORSO A SCADENZA"
        osserva_prezzo = bool(s.get("osserva_prezzo", False))
        should_track_price = is_open or ((not is_terminal) and osserva_prezzo)
        statuses[tk] = InstrumentStatus(
            ticker=tk,
            is_open=is_open,
            is_terminal=is_terminal,
            closed_date=closed_date if not is_open else None,
            closing_event_type=closing_event_type if not is_open else None,
            osserva_prezzo=osserva_prezzo,
            should_track_price=should_track_price,
        )
    return statuses


def active_fetch_tickers(data: dict[str, Any]) -> frozenset[str]:
    """Ticker per cui il job di aggiornamento quotazioni deve scaricare un
    prezzo: aperti, oppure chiusi non-terminali con osservazione prezzo
    attiva. I terminali (GOV rimborsati) sono sempre esclusi."""
    statuses = compute_instrument_statuses(data)
    return frozenset(tk for tk, status in statuses.items() if status.should_track_price)
