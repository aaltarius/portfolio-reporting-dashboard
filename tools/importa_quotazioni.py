#!/usr/bin/env python3
"""
tools/importa_quotazioni.py — Importa le quotazioni scaricate dalla pagina PHP remota.

Utilizzo (dalla cartella radice del progetto):
    python tools/importa_quotazioni.py quotazioni_2024-04-26.json

Il file JSON deve avere il formato prodotto da aggiorna_remoto.php:
{
  "data": "2024-04-26",
  "generato": "2024-04-26 15:30:00",
  "prezzi": {"VWCE.DE": 118.50, "BTP-8128": 98.75},
  "log": [...]
}

Lo script aggiorna portafoglio_data.json (nella cartella data/ o nella root,
a seconda della versione installata).
"""

import json
import os
import sys
import shutil
from datetime import datetime, date

# La root del progetto è la cartella padre di tools/
_SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA_CANDIDATES = [
    os.path.join(_SCRIPT_DIR, "data", "portafoglio_data.json"),  # v3.8.MOD+
    os.path.join(_SCRIPT_DIR, "portafoglio_data.json"),          # versioni precedenti
]


def _find_data_file():
    for p in _DATA_CANDIDATES:
        if os.path.exists(p):
            return p
    return None


def _load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def filtra_strumenti_da_aggiornare(ptf: dict) -> list:
    """Strumenti per cui ha senso importare un prezzo: esclude i terminali
    (GOV rimborsati) e i chiusi non osservati, stessa regola del fetch
    quotazioni ordinario (core.domain.instrument_status.active_fetch_tickers)."""
    if _SCRIPT_DIR not in sys.path:
        sys.path.insert(0, _SCRIPT_DIR)
    from core.domain.instrument_status import active_fetch_tickers

    fetch_tickers = active_fetch_tickers(ptf)
    return [s for s in ptf.get("strumenti", []) if s.get("ticker", "") in fetch_tickers]


def _save_json(path, data):
    backup = path + ".bak"
    if os.path.exists(path):
        shutil.copy2(path, backup)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main():
    if len(sys.argv) < 2:
        print("Utilizzo: python tools/importa_quotazioni.py <file_quotazioni.json>")
        print("Esempio:  python tools/importa_quotazioni.py quotazioni_2024-04-26.json")
        sys.exit(1)

    quote_file = sys.argv[1]
    if not os.path.exists(quote_file):
        print(f"ERRORE: file non trovato: {quote_file}")
        sys.exit(1)

    print(f"Leggo: {quote_file}")
    try:
        quote_data = _load_json(quote_file)
    except Exception as e:
        print(f"ERRORE parsing JSON: {e}")
        sys.exit(1)

    prezzi = quote_data.get("prezzi", {})
    data_str = quote_data.get("data", str(date.today()))
    generato = quote_data.get("generato", "n/d")

    if not prezzi:
        print("ERRORE: nessun prezzo nel file.")
        sys.exit(1)

    print(f"Data quotazioni: {data_str} (generato: {generato})")
    print(f"Prezzi trovati: {len(prezzi)} strumento/i")

    ptf_file = _find_data_file()
    if not ptf_file:
        print("ERRORE: portafoglio_data.json non trovato. Avvia prima la dashboard.")
        sys.exit(1)

    print(f"Portafoglio: {ptf_file}")
    ptf = _load_json(ptf_file)

    n_ok = 0
    n_skip = 0
    for s in filtra_strumenti_da_aggiornare(ptf):
        tk = s.get("ticker", "")
        if tk in prezzi and prezzi[tk] is not None:
            old_price = s.get("prezzo")
            s["prezzo"] = float(prezzi[tk])
            s["aggiornato"] = data_str
            n_ok += 1
            print(f"  ✓ {tk:20s} {float(prezzi[tk]):.4f}  (era: {old_price})")
        else:
            n_skip += 1
            print(f"  - {tk:20s} non nel file quotazioni, mantenuto valore precedente")

    try:
        _weekday = datetime.strptime(data_str, "%Y-%m-%d").weekday()
    except Exception:
        _weekday = 0
    if _weekday < 5:
        if "storico_prezzi" not in ptf:
            ptf["storico_prezzi"] = {}
        for tk, pr in prezzi.items():
            if pr is not None:
                ptf["storico_prezzi"].setdefault(data_str, {})[tk] = float(pr)
        print(f"Storico aggiornato per data: {data_str}")
    else:
        print(f"Giorno non feriale ({data_str}): storico non aggiornato")

    ptf["last_quotes_update"] = generato
    _save_json(ptf_file, ptf)
    print(f"\n✅ Import completato: {n_ok} aggiornati, {n_skip} non trovati nel file")
    print(f"   Backup salvato in: {ptf_file}.bak")
    print(f"\nRiavvia la dashboard per vedere i nuovi dati.")


if __name__ == "__main__":
    main()
