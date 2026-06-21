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
import zipfile
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

# Colonne con nomi italiani (PP installato in italiano — ricavati dall'errore di mappatura)
_COLUMNS = [
    "Data",
    "Tipo",
    "Valore",
    "Valuta Operazione",
    "Importo Lordo",
    "Importo lordo valuta",
    "Tasso di cambio",
    "Commissioni",
    "Tasse",
    "Azioni",
    "ISIN",
    "WKN",
    "Simbolo Titolo",
    "Nome Titolo",
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


def build_portfolio_performance_prices_zip(data: dict[str, Any], tickers: list[str] | None = None) -> bytes:
    """
    Genera uno ZIP con un CSV di prezzi storici per ogni strumento.

    Ogni file si chiama {ISIN}_{ticker}.csv e contiene:
        Data;Quotazione
        2024-01-02;98,50
        ...

    PP importa i prezzi per singolo titolo: seleziona titolo → "Dati storici" → Importa CSV.

    Args:
        data:    dizionario portafoglio
        tickers: lista di ticker da includere (None = tutti con storico prezzi)

    Returns:
        Bytes dello ZIP pronto per st.download_button.
    """
    storico: dict[str, dict] = data.get("storico_prezzi") or {}
    strumenti_list: list[dict] = data.get("strumenti") or []
    lookup = _build_instrument_lookup(strumenti_list)

    # Raccogli tutti i ticker presenti nello storico
    all_tickers: set[str] = set()
    for day_prices in storico.values():
        all_tickers.update(day_prices.keys())

    target = set(tickers) if tickers else all_tickers

    # Raggruppa per ticker: {ticker: [(date_str, price), ...]}
    per_ticker: dict[str, list[tuple[str, float]]] = {}
    for date_str in sorted(storico.keys()):
        day = storico[date_str]
        for ticker, price in day.items():
            if ticker not in target:
                continue
            try:
                p = float(price)
            except (TypeError, ValueError):
                continue
            per_ticker.setdefault(ticker, []).append((date_str, p))

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for ticker, rows in sorted(per_ticker.items()):
            if not rows:
                continue
            strumento = lookup.get(ticker.upper(), {})
            isin = str(strumento.get("isin", "") or "").strip()
            safe_ticker = ticker.replace("/", "-").replace("\\", "-")
            filename = f"{isin}_{safe_ticker}.csv" if isin else f"{safe_ticker}.csv"

            csv_content = "Data;Quotazione\r\n"
            for date_str, price in rows:
                csv_content += f"{date_str};{_fmt_amount(price)}\r\n"

            zf.writestr(filename, csv_content.encode("utf-8-sig"))

    return buf.getvalue()
