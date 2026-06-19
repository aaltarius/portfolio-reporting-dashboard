"""
core/services/integrity.py — Portfolio integrity checks for Data Management.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from persistence.storage import get_registro_eventi


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
        if item.get("prezzo") in (None, "", 0)
    )
    if missing_prices:
        add("Prezzi", "Warning", "Strumenti senza prezzo corrente", ", ".join(missing_prices[:12]), len(missing_prices))

    storici = data.get("storico_prezzi", {}) or {}
    history_per_ticker: dict[str, int] = {}
    for _day, values in storici.items():
        if not isinstance(values, dict):
            continue
        for tk, px in values.items():
            if px in (None, ""):
                continue
            history_per_ticker[str(tk)] = history_per_ticker.get(str(tk), 0) + 1
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
        if str(ev.get("tipo_evento", "") or "") in {"ACQUISTO", "VENDITA", "RIMBORSO A SCADENZA"}
        and float(ev.get("quantita", 0) or 0) <= 0
    ]
    if invalid_trade_qty:
        add("Eventi", "Errore", "Operazioni con quantita non valida", "Sono presenti operazioni con quantita <= 0.", len(invalid_trade_qty))

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
        future_rows = btp_calendar_df[
            pd.to_datetime(btp_calendar_df.get("data"), errors="coerce") >= today
        ].copy()
        if future_rows.empty:
            add("GOV/BTP", "Info", "Nessun flusso futuro nella timeline BTP", "Verifica scadenze e prime cedole dei titoli governativi.")

    if not checks:
        add("Sistema", "OK", "Nessuna anomalia evidente", "I controlli principali non hanno segnalato problemi.", 0)
    return checks
