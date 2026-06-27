"""
core/instrument_enrichment.py
Arricchimento strumenti: fetch da fonti pubbliche, parser PDF Fineco, bulk.
"""
from __future__ import annotations

import re
import datetime
from typing import Callable, Optional

import requests
from bs4 import BeautifulSoup


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _categoria(tipo: str) -> str:
    t = (tipo or "").lower()
    if any(k in t for k in ("stato", "btp", "titolo")):
        return "btp"
    if "etc" in t:
        return "etc"
    if any(k in t for k in ("fondo", "bilanc", "fless", "flex", "multi", "obbl. m", "az. pass", "passivo")):
        return "fondo"
    return "etf"


def _extract_yahoo_alt(fonte: str) -> Optional[str]:
    m = re.search(r"Yahoo\s*\[(.+?)\]", str(fonte or ""))
    return m.group(1) if m else None


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_BTP_FIELD_MAP = {
    "rendimento effettivo a scadenza lordo": "ytm_lordo",
    "rendimento effettivo a scadenza netto": "ytm_netto",
    "rateo lordo":                           "rateo_lordo",
    "rateo netto":                           "rateo_netto",
    "duration modificata":                   "duration_modificata",
    "scadenza":                              "scadenza",
    "periodicita cedola":                    "cedola_frequenza",
    "periodicita' cedola":                   "cedola_frequenza",
    "periodicità cedola":                    "cedola_frequenza",
    "tasso cedola periodale":                "cedola_tasso",
    "emittente":                             "emittente_btp",
    "struttura bond":                        "struttura",
    "data godimento":                        "data_godimento",
}


# ---------------------------------------------------------------------------
# Fetch implementations — implementati nei task successivi
# ---------------------------------------------------------------------------

def enrich_btp(strumento: dict) -> dict:
    isin = str(strumento.get("isin") or "").strip()
    if not isin:
        strumento["enrichment_error"] = "ISIN mancante"
        return strumento
    url = f"https://www.borsaitaliana.it/borsa/obbligazioni/mot/btp/scheda/{isin}-MOTX.html?lang=it"
    try:
        r = requests.get(url, headers=_HEADERS, timeout=12)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        src: dict[str, str] = {}
        for row in soup.select("table tr"):
            cells = row.find_all(["td", "th"])
            if len(cells) < 2:
                continue
            label = cells[0].get_text(strip=True).lower()
            value = cells[-1].get_text(strip=True)
            if not value or value in ("-", "n.d.", ""):
                continue
            for key, field in _BTP_FIELD_MAP.items():
                if key in label:
                    strumento[field] = value
                    src[field] = "auto"
                    break
        strumento["enriched_at"] = _now_iso()
        existing_src = strumento.get("enrichment_source") or {}
        strumento["enrichment_source"] = {**existing_src, **src}
        strumento.pop("enrichment_error", None)
    except Exception as exc:
        strumento["enrichment_error"] = str(exc)
    return strumento


def enrich_etf_etc(strumento: dict) -> dict:
    raise NotImplementedError


def enrich_fondo(strumento: dict) -> dict:
    raise NotImplementedError


def parse_fineco_pdf(pdf_bytes: bytes, tipo: str) -> dict:
    raise NotImplementedError


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

def enrich_strumento(strumento: dict) -> dict:
    cat = _categoria(strumento.get("tipo", ""))
    if cat == "btp":
        return enrich_btp(strumento)
    if cat in ("etf", "etc"):
        return enrich_etf_etc(strumento)
    if cat == "fondo":
        return enrich_fondo(strumento)
    return strumento


# ---------------------------------------------------------------------------
# Bulk
# ---------------------------------------------------------------------------

def enrich_all(
    data: dict,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
) -> tuple[int, int, list[str]]:
    strumenti = [s for s in (data.get("strumenti") or []) if str(s.get("stato", "aperto")) == "aperto"]
    total = len(strumenti)
    ok = 0
    err = 0
    msgs: list[str] = []
    for i, s in enumerate(strumenti):
        ticker = str(s.get("ticker") or "?")
        try:
            enrich_strumento(s)
            ok += 1
        except Exception as exc:
            err += 1
            msgs.append(f"{ticker}: {exc}")
            s["enrichment_error"] = str(exc)
        if on_progress:
            on_progress(i + 1, total, ticker)
    return ok, err, msgs
