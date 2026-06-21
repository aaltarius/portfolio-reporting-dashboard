"""core/services/portfolio_performance_export.py

Genera un CSV compatibile con Portfolio Performance (pp.name) a partire
dal registro_eventi interno dell'applicazione.

Formato CSV di PP (separatore ";", header obbligatorio):
  Date;Type;Value;Transaction Currency;Gross Amount;Currency Gross Amount;
  Exchange Rate;Fees;Taxes;Shares;ISIN;WKN;Ticker Symbol;Security Name;Note

Documentazione PP: https://help.portfolio-performance.info/en/reference/file/import/
"""
from __future__ import annotations

import csv
import io
from typing import Any

# ─── Mapping tipo_evento → tipo PP ──────────────────────────────────────────

_TYPE_MAP: dict[str, str] = {
    "ACQUISTO":            "Buy",
    "VENDITA":             "Sell",
    "RIMBORSO A SCADENZA": "Sell",
    "CEDOLA":              "Interest",
    "DIVIDENDO":           "Dividends",
    "VERSAMENTO":          "Deposit",
    "PRELIEVO":            "Removal",
    "COMMISSIONE":         "Fees",
    "IMPOSTA":             "Taxes",
}

# Tipi che riguardano un titolo specifico (hanno Shares, ISIN, ecc.)
_SECURITY_TYPES = {"Buy", "Sell", "Interest", "Dividends", "Fees", "Taxes"}

# Colonne nell'ordine esatto richiesto da PP
_COLUMNS = [
    "Date",
    "Type",
    "Value",
    "Transaction Currency",
    "Gross Amount",
    "Currency Gross Amount",
    "Exchange Rate",
    "Fees",
    "Taxes",
    "Shares",
    "ISIN",
    "WKN",
    "Ticker Symbol",
    "Security Name",
    "Note",
]


def _build_instrument_lookup(strumenti: list[dict]) -> dict[str, dict]:
    """Dizionario ticker → record strumento."""
    lookup: dict[str, dict] = {}
    for s in strumenti or []:
        ticker = str(s.get("ticker", "")).strip().upper()
        if ticker:
            lookup[ticker] = s
    return lookup


def _fmt(value: float | None, decimals: int = 2) -> str:
    if value is None or value != value:  # NaN check
        return ""
    return f"{value:.{decimals}f}"


def build_portfolio_performance_csv(data: dict[str, Any]) -> str:
    """
    Converte registro_eventi nel CSV di Portfolio Performance.

    Args:
        data: dizionario portafoglio caricato da persistence.storage.load_data()

    Returns:
        Stringa CSV completa (encoding UTF-8, separatore ;).
    """
    eventi: list[dict] = data.get("registro_eventi") or []
    strumenti_list: list[dict] = data.get("strumenti") or []
    lookup = _build_instrument_lookup(strumenti_list)

    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=_COLUMNS,
        delimiter=";",
        lineterminator="\r\n",
        extrasaction="ignore",
        quoting=csv.QUOTE_MINIMAL,
    )
    writer.writeheader()

    # Ordina per data per avere lo storico cronologico in PP
    sorted_eventi = sorted(
        eventi,
        key=lambda e: str(e.get("data") or ""),
    )

    for ev in sorted_eventi:
        tipo_interno = str(ev.get("tipo_evento", "")).strip().upper()
        pp_type = _TYPE_MAP.get(tipo_interno)
        if not pp_type:
            continue  # evento non mappabile (es. note interne)

        ticker = str(ev.get("ticker", "") or "").strip().upper()
        strumento = lookup.get(ticker, {})
        isin = str(strumento.get("isin", "") or "").strip()
        nome = str(strumento.get("nome", ticker) or ticker).strip()

        importo_lordo = ev.get("importo_lordo") or 0.0
        commissioni = ev.get("commissioni") or 0.0
        imposte = ev.get("imposte") or 0.0
        quantita = ev.get("quantita") or 0.0
        importo_netto = ev.get("importo_netto") or 0.0

        # PP vuole il valore netto come "Value" (positivo per entrate, negativo per uscite)
        # Per Buy/Fees/Taxes/Removal PP si aspetta il valore come uscita di cassa (positivo)
        if pp_type in {"Buy", "Fees", "Taxes", "Removal"}:
            value = abs(importo_netto)
        else:
            value = abs(importo_netto)

        row: dict[str, str] = {
            "Date":                    str(ev.get("data", "") or ""),
            "Type":                    pp_type,
            "Value":                   _fmt(value),
            "Transaction Currency":    "EUR",
            "Gross Amount":            _fmt(abs(importo_lordo)) if pp_type in _SECURITY_TYPES else "",
            "Currency Gross Amount":   "EUR" if pp_type in _SECURITY_TYPES and importo_lordo else "",
            "Exchange Rate":           "",
            "Fees":                    _fmt(abs(commissioni)) if commissioni else "",
            "Taxes":                   _fmt(abs(imposte)) if imposte else "",
            "Shares":                  _fmt(abs(quantita), 6) if pp_type in _SECURITY_TYPES and quantita else "",
            "ISIN":                    isin if pp_type in _SECURITY_TYPES else "",
            "WKN":                     "",
            "Ticker Symbol":           ticker if pp_type in _SECURITY_TYPES else "",
            "Security Name":           nome if pp_type in _SECURITY_TYPES else "",
            "Note":                    str(ev.get("note", "") or ""),
        }
        writer.writerow(row)

    return output.getvalue()
