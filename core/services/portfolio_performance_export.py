"""core/services/portfolio_performance_export.py

Genera un CSV compatibile con Portfolio Performance (pp.name) a partire
dal registro_eventi interno dell'applicazione.

Formato CSV di PP (separatore ";", decimale ","):
  Date;Type;Value;Transaction Currency;Gross Amount;Currency Gross Amount;
  Exchange Rate;Fees;Taxes;Shares;ISIN;WKN;Ticker Symbol;Security Name;Note

Nomi e tipi ricavati direttamente dai sorgenti Java di PP:
  - CSVExporter.java     → ordine e nomi colonne
  - labels.properties   → stringhe esatte dei tipi transazione
  - TextUtil.java        → separatore ";" se decimale = "," (locale europeo)
"""
from __future__ import annotations

import io
from typing import Any

# ─── Mapping tipo_evento → stringa esatta di PP (locale italiano) ────────────
# Stringhe ricavate dall'errore di parsing di PP:
# {Deposito, Prelievo, Interessi, Interessi passivi, Dividendo, Commissioni,
#  Rimborso commissioni, Tasse, Rimborso tasse, Compra, Vendi,
#  Trasferimento (in entrata), Trasferimento (in uscita)}

_TYPE_MAP: dict[str, str] = {
    "ACQUISTO":            "Compra",
    "VENDITA":             "Vendi",
    "RIMBORSO A SCADENZA": "Vendi",       # rimborso obbligazione = vendita a valore nominale
    "CEDOLA":              "Interessi",   # cedola obbligazionaria
    "DIVIDENDO":           "Dividendo",   # dividendo azionario
    "VERSAMENTO":          "Deposito",
    "PRELIEVO":            "Prelievo",
    "COMMISSIONE":         "Commissioni",
    "IMPOSTA":             "Tasse",
}

# Tipi che si riferiscono a un titolo (portano ISIN, Shares, ecc.)
_SECURITY_TYPES = {"Compra", "Vendi", "Interessi", "Dividendo", "Commissioni", "Tasse"}

# Colonne nell'ordine esatto del CSVExporter.java di PP
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

# Separatore colonne: ";" perché PP su locale europeo (decimale = ",") usa ";"
_SEP = ";"


def _build_instrument_lookup(strumenti: list[dict]) -> dict[str, dict]:
    lookup: dict[str, dict] = {}
    for s in strumenti or []:
        ticker = str(s.get("ticker", "")).strip().upper()
        if ticker:
            lookup[ticker] = s
    return lookup


def _fmt_amount(value: float | None, decimals: int = 2) -> str:
    """Formatta un importo con virgola decimale (formato europeo atteso da PP)."""
    if value is None or value != value:  # NaN check
        return ""
    formatted = f"{value:.{decimals}f}"
    # Sostituisce il punto decimale con la virgola (locale europeo/italiano)
    return formatted.replace(".", ",")


def build_portfolio_performance_csv(data: dict[str, Any]) -> str:
    """
    Converte registro_eventi nel CSV di Portfolio Performance.

    Args:
        data: dizionario portafoglio da persistence.storage.load_data()

    Returns:
        Stringa CSV (UTF-8, separatore ";", decimale ",") pronta per il download.
    """
    eventi: list[dict] = data.get("registro_eventi") or []
    strumenti_list: list[dict] = data.get("strumenti") or []
    lookup = _build_instrument_lookup(strumenti_list)

    output = io.StringIO()

    # Header
    output.write(_SEP.join(_COLUMNS) + "\r\n")

    # Ordina cronologicamente
    sorted_eventi = sorted(eventi, key=lambda e: str(e.get("data") or ""))

    for ev in sorted_eventi:
        tipo_interno = str(ev.get("tipo_evento", "")).strip().upper()
        pp_type = _TYPE_MAP.get(tipo_interno)
        if not pp_type:
            continue

        ticker = str(ev.get("ticker", "") or "").strip().upper()
        strumento = lookup.get(ticker, {})
        isin = str(strumento.get("isin", "") or "").strip()
        nome = str(strumento.get("nome", ticker) or ticker).strip()

        importo_lordo = float(ev.get("importo_lordo") or 0.0)
        commissioni   = float(ev.get("commissioni")   or 0.0)
        imposte       = float(ev.get("imposte")       or 0.0)
        quantita      = float(ev.get("quantita")      or 0.0)
        importo_netto = float(ev.get("importo_netto") or 0.0)

        is_security = pp_type in _SECURITY_TYPES

        # PP vuole sempre il valore come numero positivo; il segno è implicito nel Type
        value = abs(importo_netto)

        # Gross Amount = importo lordo prima di fee/tasse; se zero usa quantita*prezzo
        gross = abs(importo_lordo)
        if gross == 0 and is_security:
            prezzo = float(ev.get("prezzo_unitario") or 0.0)
            gross = abs(quantita * prezzo)

        row = [
            str(ev.get("data", "") or ""),                                  # Date
            pp_type,                                                         # Type
            _fmt_amount(value),                                              # Value
            "EUR",                                                           # Transaction Currency
            _fmt_amount(gross) if is_security and gross else "",            # Gross Amount
            "EUR" if is_security and gross else "",                         # Currency Gross Amount
            "",                                                              # Exchange Rate
            _fmt_amount(abs(commissioni)) if commissioni else "",           # Fees
            _fmt_amount(abs(imposte)) if imposte else "",                   # Taxes
            _fmt_amount(abs(quantita), 6) if is_security and quantita else "", # Shares
            isin if is_security else "",                                     # ISIN
            "",                                                              # WKN
            ticker if is_security else "",                                   # Ticker Symbol
            nome if is_security else "",                                     # Security Name
            str(ev.get("note", "") or ""),                                  # Note
        ]

        # Metti in virgolette i campi che contengono il separatore ";"
        def _quote(s: str) -> str:
            if _SEP in s or '"' in s:
                return '"' + s.replace('"', '""') + '"'
            return s

        output.write(_SEP.join(_quote(f) for f in row) + "\r\n")

    return output.getvalue()
