"""
core/validators.py - Validatori puri e riutilizzabili.

Le funzioni sollevano ValueError con messaggi adatti alla UI. Non importano
Streamlit e possono essere testate isolatamente.
"""
from __future__ import annotations

from datetime import date, datetime
from math import isfinite
from numbers import Real
from typing import Any


def _is_real_number(value: Any) -> bool:
    if not isinstance(value, Real) or isinstance(value, bool):
        return False
    try:
        return isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def validate_quantity(qty: float, op_type: str, available_qty: float = 0.0) -> None:
    """Valida la quantita' richiesta per un'operazione."""
    if not _is_real_number(qty):
        raise ValueError("La quantita' deve essere numerica.")
    if qty <= 0:
        raise ValueError("La quantita' deve essere maggiore di zero.")

    normalized_type = str(op_type or "").strip().upper()
    if normalized_type in {"VENDITA", "RIMBORSO A SCADENZA"}:
        if available_qty <= 0:
            raise ValueError("Lo strumento non risulta presente in portafoglio.")
        if qty - available_qty > 1e-9:
            raise ValueError(f"Quantita' insufficiente: disponibili {available_qty:g} quote.")


def validate_price(price: float, instrument_type: str | None = None) -> None:
    """Valida il prezzo unitario per acquisto, vendita o rimborso."""
    if not _is_real_number(price):
        raise ValueError("Il prezzo deve essere numerico.")
    if price <= 0:
        raise ValueError("Il prezzo deve essere maggiore di zero.")

    normalized_type = str(instrument_type or "").strip().lower()
    if any(token in normalized_type for token in ("btp", "titolo di stato", "obblig")) and price > 200:
        raise ValueError("Il prezzo di uno strumento obbligazionario sembra fuori scala.")


def validate_date(date_value: str | date | datetime) -> date:
    """Valida una data e restituisce un oggetto date."""
    if isinstance(date_value, datetime):
        return date_value.date()
    if isinstance(date_value, date):
        return date_value
    if not isinstance(date_value, str):
        raise ValueError(f"La data deve essere una stringa o un oggetto date, ricevuto {type(date_value).__name__}.")
    if not date_value.strip():
        raise ValueError("La data e' obbligatoria.")

    raw = date_value.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise ValueError("Formato data non valido. Usa YYYY-MM-DD o DD/MM/YYYY.")


def validate_number_input(value: float, min_val: float, max_val: float) -> None:
    """Valida un input numerico entro un range chiuso."""
    if not _is_real_number(value):
        raise ValueError(f"Valore numerico atteso, ricevuto {type(value).__name__}.")
    if value < min_val or value > max_val:
        raise ValueError(f"Valore {value:g} fuori range [{min_val:g}, {max_val:g}].")


def validate_selection(values: list[str], allowed_values: list[str], label: str = "Selezione") -> None:
    """Valida che una selezione multipla contenga solo valori ammessi."""
    if not values:
        raise ValueError(f"{label} vuota.")
    allowed = {str(v) for v in allowed_values}
    invalid = [str(v) for v in values if str(v) not in allowed]
    if invalid:
        raise ValueError(f"{label} non valida: {', '.join(invalid)}.")


def validate_alert_thresholds(
    loss_threshold_pct: float,
    concentration_threshold_pct: float,
    drawdown_threshold_pct: float,
    volatility_threshold_pct: float,
) -> None:
    """Valida le soglie degli alert di portafoglio."""
    validate_number_input(loss_threshold_pct, 0.0, 100.0)
    validate_number_input(concentration_threshold_pct, 0.0, 100.0)
    validate_number_input(drawdown_threshold_pct, 0.0, 100.0)
    validate_number_input(volatility_threshold_pct, 0.0, 100.0)


def validate_quote_import(quotes: Any) -> None:
    """Valida la struttura base di un file di quotazioni importato."""
    if not isinstance(quotes, (dict, list)):
        raise ValueError("Il file quotazioni deve contenere un oggetto o una lista JSON.")

    if isinstance(quotes, dict) and isinstance(quotes.get("prezzi"), dict):
        prezzi = quotes.get("prezzi", {})
        if not prezzi:
            raise ValueError("Il file quotazioni non contiene prezzi da importare.")
        for ticker, price in prezzi.items():
            if not str(ticker or "").strip():
                raise ValueError("Trovato un ticker vuoto nel file quotazioni.")
            try:
                numeric_price = float(price)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Ticker {ticker}: prezzo non numerico.") from exc
            if not isfinite(numeric_price) or numeric_price <= 0:
                raise ValueError(f"Ticker {ticker}: prezzo non valido.")
        return

    rows = quotes.values() if isinstance(quotes, dict) else quotes
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"Riga quotazione {index}: atteso oggetto JSON.")

        ticker = row.get("ticker") or row.get("Ticker") or row.get("symbol") or row.get("isin")
        price = row.get("prezzo") or row.get("price") or row.get("last") or row.get("close")
        if not str(ticker or "").strip():
            raise ValueError(f"Riga quotazione {index}: ticker mancante.")

        try:
            numeric_price = float(price)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Riga quotazione {index}: prezzo non numerico.") from exc
        if not isfinite(numeric_price) or numeric_price <= 0:
            raise ValueError(f"Riga quotazione {index}: prezzo non valido.")
