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

_JUSTETF_INFO_KEYS = {
    "indice":                              "benchmark",
    "focus di investimento":               "focus_etf",
    "dimensione del fondo":                "aum",
    "indicatore sintetico di spesa (ter)": "ter",
    "replicazione":                        "replica",
    "politica di distribuzione":           "distribuzione",
    "valuta dell'etf":                     "valuta_etf",
    "rischio di cambio":                   "rischio_cambio",
    "emittente":                           "emittente",
    "domicilio del fondo":                 "domicilio",
}

_PCT_RE = re.compile(r"^[+-]?\d+[,.]?\d*\s*%")


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


def _parse_justetf(soup) -> dict:
    label_map: dict[str, str] = {}
    for dl in soup.select("dl"):
        for dt, dd in zip(dl.select("dt"), dl.select("dd")):
            lbl = dt.get_text(strip=True).lower()
            val = dd.get_text(strip=True)
            if lbl and val and val not in ("-", "n/d", "—", ""):
                label_map[lbl] = val
    for table in soup.select("table"):
        for row in table.select("tr"):
            cells = row.find_all(["td", "th"])
            if len(cells) == 2:
                lbl = cells[0].get_text(strip=True).lower()
                val = cells[1].get_text(strip=True)
                if lbl and val and val not in ("-", "n/d", "—", "") and not _PCT_RE.match(val):
                    label_map[lbl] = val

    info: dict[str, str] = {}
    for lbl, field in _JUSTETF_INFO_KEYS.items():
        if lbl in label_map:
            info[field] = label_map[lbl]

    holdings: list[dict] = []
    paesi: list[dict] = []
    settori: list[dict] = []

    for table in soup.select("table"):
        entries = []
        for row in table.select("tr"):
            cells = row.find_all(["td", "th"])
            if len(cells) >= 2:
                nome = cells[0].get_text(strip=True)
                pct = cells[1].get_text(strip=True)
                if nome and pct and _PCT_RE.match(pct):
                    entries.append({"nome": nome, "pct": pct})
        if not entries:
            continue
        names_lower = " ".join(e["nome"].lower() for e in entries)
        if any(k in names_lower for k in ("stati uniti", "giappone", "regno unito", "usa", "canada", "ireland", "italia", "germania")):
            paesi = entries[:10]
        elif any(k in names_lower for k in ("informatica", "finanza", "industria", "sanita", "beni", "tecnolog", "financial", "energy")):
            settori = entries[:10]
        elif not holdings:
            holdings = entries[:10]

    return {"info": info, "holdings": holdings, "paesi": paesi, "settori": settori}


def enrich_etf_etc(strumento: dict) -> dict:
    isin = str(strumento.get("isin") or "").strip()
    if not isin:
        strumento["enrichment_error"] = "ISIN mancante"
        return strumento
    url = f"https://www.justetf.com/it/etf-profile.html?isin={isin}"
    try:
        r = requests.get(url, headers=_HEADERS, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        parsed = _parse_justetf(soup)
        src: dict[str, str] = {}
        for field, val in parsed["info"].items():
            strumento[field] = val
            src[field] = "auto"
        if parsed["holdings"]:
            strumento["holdings_top"] = parsed["holdings"]
            src["holdings_top"] = "auto"
        if parsed["paesi"]:
            strumento["paesi_top"] = parsed["paesi"]
            src["paesi_top"] = "auto"
        if parsed["settori"]:
            strumento["settori_top"] = parsed["settori"]
            src["settori_top"] = "auto"
        strumento["enriched_at"] = _now_iso()
        existing_src = strumento.get("enrichment_source") or {}
        strumento["enrichment_source"] = {**existing_src, **src}
        strumento.pop("enrichment_error", None)
    except Exception as exc:
        strumento["enrichment_error"] = str(exc)
    return strumento


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
