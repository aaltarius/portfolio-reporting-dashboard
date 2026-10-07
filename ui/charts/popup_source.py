"""ui/charts/popup_source.py — URL della fonte di un prezzo, per i popup strumento.

Unica definizione condivisa da ui/charts/quotes_popup.py e
ui/charts/portfolio_popup.py: i due popup mostrano lo stesso "Link fonte".
"""
from __future__ import annotations

import re


def build_source_url(fonte: str, isin: str, ticker: str) -> str | None:
    """Link alla pagina della fonte del prezzo, o None se non risolvibile.

    - Borsa Italiana (con ISIN): scheda dati completi MOT dei BTP.
    - Yahoo: simbolo tra parentesi quadre nel nome fonte (es. "Yahoo [SWDA.MI]"),
      altrimenti il ticker interno.
    """
    fonte = str(fonte or "")
    isin = str(isin or "")
    if "Borsa Italiana" in fonte and isin and isin != "n/d":
        return f"https://www.borsaitaliana.it/borsa/obbligazioni/mot/btp/dati-completi.html?isin={isin}&lang=it"
    if "Yahoo" in fonte:
        match = re.search(r"\[(.+?)\]", fonte)
        symbol = match.group(1) if match else ticker
        return f"https://finance.yahoo.com/quote/{symbol}"
    return None
