"""
core/services/integrity.py — Portfolio integrity checks for Data Management.
"""
from __future__ import annotations

from datetime import date
import math
from typing import Any

import pandas as pd

from persistence.storage import (
    EVENTI_CON_IMPORTO,
    EVENTI_CON_PREZZO,
    EVENTI_CON_QUANTITA,
    get_registro_eventi,
)


def _coerce_finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _is_positive_finite(value: Any) -> bool:
    number = _coerce_finite_float(value)
    return number is not None and number > 0


def _is_nonzero_finite(value: Any) -> bool:
    number = _coerce_finite_float(value)
    return number is not None and abs(number) > 1e-12


def _is_valid_price(value: Any) -> bool:
    return _is_positive_finite(value)


def build_integrity_checks(data: dict[str, Any], btp_calendar_df: pd.DataFrame | None = None) -> list[dict[str, Any]]:
    instruments = list(data.get("strumenti", []) or [])
    events = list(get_registro_eventi(data) or [])
    info_map = {
        str(item.get("ticker", "") or "").strip(): item
        for item in instruments
        if str(item.get("ticker", "") or "").strip()
    }
    today = pd.Timestamp(date.today())
    checks: list[dict[str, Any]] = []

    def add(scope: str, severity: str, item: str, detail: str, count: int = 0) -> None:
        checks.append({
            "Ambito": scope,
            "Severita": severity,
            "Elemento": item,
            "Dettaglio": detail,
            "Conteggio": int(count),
        })

    orphan_event_tickers = sorted({
        str(ev.get("ticker", "") or "").strip()
        for ev in events
        if str(ev.get("ticker", "") or "").strip() and str(ev.get("ticker", "") or "").strip() not in info_map
    })
    if orphan_event_tickers:
        add("Anagrafica/Eventi", "Errore", "Ticker presenti negli eventi ma assenti in anagrafica", ", ".join(orphan_event_tickers[:12]), len(orphan_event_tickers))

    never_moved = sorted(
        tk for tk in info_map
        if not any(str(ev.get("ticker", "") or "").strip() == tk for ev in events)
    )
    if never_moved:
        add("Anagrafica/Eventi", "Warning", "Strumenti mai movimentati", ", ".join(never_moved[:12]), len(never_moved))

    missing_prices = sorted(
        tk for tk, item in info_map.items()
        if not _is_valid_price(item.get("prezzo"))
    )
    if missing_prices:
        add("Prezzi", "Warning", "Strumenti senza prezzo corrente", ", ".join(missing_prices[:12]), len(missing_prices))

    storici = data.get("storico_prezzi", {}) or {}
    history_per_ticker: dict[str, int] = {}
    invalid_history_prices: list[str] = []
    for day, values in storici.items():
        if not isinstance(values, dict):
            continue
        for tk, px in values.items():
            if not _is_valid_price(px):
                invalid_history_prices.append(f"{day}:{tk}")
                continue
            history_per_ticker[str(tk)] = history_per_ticker.get(str(tk), 0) + 1
    if invalid_history_prices:
        add("Prezzi", "Warning", "Prezzi storici non validi", ", ".join(invalid_history_prices[:12]), len(invalid_history_prices))
    short_history = sorted(
        tk for tk in info_map
        if history_per_ticker.get(tk, 0) < 3
    )
    if short_history:
        add("Prezzi", "Info", "Storico molto corto (< 3 date)", ", ".join(short_history[:12]), len(short_history))

    suspicious_cash = [
        ev for ev in events
        if str(ev.get("tipo_evento", "") or "") in {"COMMISSIONE", "IMPOSTA"}
        and not str(ev.get("ticker", "") or "").strip()
    ]
    if suspicious_cash:
        add("Liquidita", "Info", "Commissioni/imposte senza ticker", "Verifica se sono costi generali o eventi orfani.", len(suspicious_cash))

    invalid_trade_qty = [
        ev for ev in events
        if str(ev.get("tipo_evento", "") or "") in EVENTI_CON_QUANTITA
        and not _is_positive_finite(ev.get("quantita"))
    ]
    if invalid_trade_qty:
        add("Eventi", "Errore", "Operazioni con quantita non valida", "Sono presenti operazioni con quantita mancante, non numerica, non finita o <= 0.", len(invalid_trade_qty))

    invalid_trade_price = [
        ev for ev in events
        if str(ev.get("tipo_evento", "") or "") in EVENTI_CON_PREZZO
        and not _is_positive_finite(ev.get("prezzo_unitario"))
    ]
    if invalid_trade_price:
        add("Eventi", "Errore", "Operazioni con prezzo non valido", "Sono presenti operazioni con prezzo unitario mancante, non numerico, non finito o <= 0.", len(invalid_trade_price))

    invalid_amount = [
        ev for ev in events
        if str(ev.get("tipo_evento", "") or "") in EVENTI_CON_IMPORTO
        and not (_is_nonzero_finite(ev.get("importo_lordo")) or _is_nonzero_finite(ev.get("importo_netto")))
    ]
    if invalid_amount:
        add("Eventi", "Errore", "Eventi con importo non valido", "Sono presenti eventi con importo lordo/netto mancante, non numerico, non finito o pari a zero.", len(invalid_amount))

    btp_instruments = [
        item for item in instruments
        if str(item.get("tipo", "") or "").strip().lower() in {"btp", "titolo di stato"}
    ]
    btp_missing_meta = []
    for item in btp_instruments:
        missing = [
            label for label, key in [
                ("scadenza", "scadenza"),
                ("prima cedola", "prima_cedola"),
                ("cedola %", "cedola_perc"),
            ]
            if item.get(key) in (None, "")
        ]
        if missing:
            btp_missing_meta.append(f"{item.get('ticker', '—')} ({', '.join(missing)})")
    if btp_missing_meta:
        add("GOV/BTP", "Warning", "Metadati cedole/scadenza incompleti", "; ".join(btp_missing_meta[:10]), len(btp_missing_meta))

    if btp_calendar_df is not None and not btp_calendar_df.empty:
        if "data" not in btp_calendar_df.columns:
            add("GOV/BTP", "Warning", "Timeline BTP senza colonna data", "Il calendario cedole non e' leggibile: rigenera la timeline BTP.", len(btp_calendar_df))
        else:
            parsed_dates = pd.to_datetime(btp_calendar_df.get("data"), errors="coerce")
            if parsed_dates.isna().all():
                add("GOV/BTP", "Warning", "Timeline BTP senza date valide", "Il calendario cedole non contiene date utilizzabili: rigenera la timeline BTP.", len(btp_calendar_df))
            else:
                future_rows = btp_calendar_df[parsed_dates >= today].copy()
                if future_rows.empty:
                    add("GOV/BTP", "Info", "Nessun flusso futuro nella timeline BTP", "Verifica scadenze e prime cedole dei titoli governativi.")

    if not checks:
        add("Sistema", "OK", "Nessuna anomalia evidente", "I controlli principali non hanno segnalato problemi.", 0)
    return checks
