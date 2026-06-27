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
import yfinance as yf


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
    fonte = str(strumento.get("fonte") or "")
    yticker = _extract_yahoo_alt(fonte)
    if not yticker:
        strumento["enrichment_error"] = "Ticker Yahoo non trovato nel campo fonte"
        return strumento
    try:
        info = yf.Ticker(yticker).info or {}
        src: dict[str, str] = {}

        def _set(field: str, value) -> None:
            if value is not None:
                strumento[field] = value
                src[field] = "auto"

        _set("valuta", info.get("currency"))
        _set("max_52w", info.get("fiftyTwoWeekHigh"))
        _set("min_52w", info.get("fiftyTwoWeekLow"))

        first_trade = info.get("firstTradeDateEpochUtc") or info.get("firstTradeDate")
        if first_trade:
            try:
                dl = datetime.datetime.fromtimestamp(int(first_trade)).strftime("%Y-%m-%d")
                _set("data_lancio", dl)
            except Exception:
                pass

        ytd = info.get("ytdReturn")
        if ytd is not None:
            _set("rendimento_ytd", f"{float(ytd):.2f}%")

        strumento["enriched_at"] = _now_iso()
        existing_src = strumento.get("enrichment_source") or {}
        strumento["enrichment_source"] = {**existing_src, **src}
        strumento.pop("enrichment_error", None)
    except Exception as exc:
        strumento["enrichment_error"] = str(exc)
    return strumento


def _re_val(pattern: str, text: str, flags: int = re.IGNORECASE) -> Optional[str]:
    """Search *pattern* in *text*, return first capture group stripped, or None."""
    m = re.search(pattern, text, flags)
    return m.group(1).strip() if m else None


def _parse_pdf_btp(text: str) -> dict:
    out: dict = {}
    patterns = {
        "ytm_netto":         r"Rendimento netto a scadenza\s+([\d,]+\s*%)",
        "cedola_annuale":    r"Cedola annuale\s+([\d,]+\s*%)",
        "cedola_frequenza":  r"Frequenza cedola\s+(\w+\.?)",
        "tipo_cedola":       r"Tipo cedola in corso\s+(\w+)",
        "prossima_cedola":   r"Prossima cedola\s+([\d/]+)",
        "scadenza":          r"Scadenza\s+([\d/]+)",
        "rating_emittente":  r"Rating emittente\s+([A-Z]{1,3}[+\-]?)",
        "data_emissione":    r"Data emissione\s+([\d/]+)",
        "prezzo_emissione":  r"Prezzo emissione\s+([\d,.]+)",
        "prezzo_rimborso":   r"Prezzo rimborso\s+([\d,.]+)",
        "rateo_interessi":   r"Rateo interessi\s+([\d,.()\w/]+)",
        "rateo_disaggio":    r"Rateo di disaggio\s*\(1\)\s+([\d,.]+)",
        "ritenute_totali":   r"Ritenute totali\s+([\d,.]+)",
    }
    for field, pat in patterns.items():
        val = _re_val(pat, text)
        if val:
            out[field] = val
    return out


def _parse_pdf_etf(text: str) -> dict:
    out: dict = {}
    patterns = {
        "ter":            r"Commissioni gestione e altri costi\s+([\d,.]+\s*%)",
        "benchmark":      r"Benchmark\s+(.+?)(?:\n|Morningstar|Area|$)",
        "categoria_etf":  r"Categoria\s+(.+?)(?:\n|Emittente|$)",
        "emittente":      r"Emittente\s+(.+?)(?:\n|Morningstar|$)",
        "rendimento_1a":  r"1\s*[Aa]\s*\n?\s*([+\-]?[\d,.]+\s*%)",
        "rendimento_3a":  r"3\s*[Aa]\s*\n?\s*([+\-]?[\d,.]+\s*%)",
        "deviazione_std": r"Deviazione standard\s+([\d,.]+\s*%)",
        "sharpe":         r"Indice di [Ss]harpe\s+([\d,.]+)",
        "beta":           r"Indice beta\s+([\d,.]+)",
        "var":            r"VaR\s+([\d,.]+)",
        "fiscalita":      r"Fiscalit[àa]\s+(\w+)",
        "data_lancio":    r"Data di partenza\s+([\d/]+)",
        "patrimonio":     r"Patrimonio netto\s*(?:mln)?\s*([\d,.]+)",
    }
    for field, pat in patterns.items():
        val = _re_val(pat, text)
        if val:
            out[field] = val.strip()

    # Morningstar stars: count ★ characters
    stars_m = re.search(r"Morningstar\s*([★☆✩❆⭐*]{1,5})", text)
    if stars_m:
        raw = stars_m.group(1)
        count = raw.count("★") or raw.count("*") or len(raw)
        out["rating_morningstar"] = count

    # Top holdings: "Name  xx,xx%"
    holdings = re.findall(
        r"([\w\s]+(?:SpA|NV|Ltd|SA|AG|Plc|Inc|Group)?)\s+([\d,.]+\s*%)", text
    )
    if holdings:
        out["holdings_top"] = [
            {"nome": h[0].strip(), "pct": h[1]} for h in holdings[:5]
        ]

    return out


def _parse_pdf_fam(text: str) -> dict:
    out: dict = {}

    # Rendimenti: "Da inizio anno 1 A 3 A\n4,47% 11,85% 26,52%"
    rend_m = re.search(
        r"Da inizio anno\s+1\s+A\s+3\s+A\s*\n\s*"
        r"([+\-]?[\d,.]+\s*%)\s+([+\-]?[\d,.]+\s*%)\s+([+\-]?[\d,.]+\s*%)",
        text,
    )
    if rend_m:
        out["rendimento_ytd"] = rend_m.group(1).strip()
        out["rendimento_1a"] = rend_m.group(2).strip()
        out["rendimento_3a"] = rend_m.group(3).strip()

    # Campi semplici (già funzionanti sul layout reale)
    simple: dict = {
        "ter":          r"Commissione gestione annua\s+([\d,.]+\s*%)",
        "categoria_fam": r"Categoria\s+MS\s+(.+?)(?:\n|Categoria Advice|$)",
        "data_lancio":  r"Data di lancio\s+([\d/]+)",
        "valuta":       r"Valuta NAV\s+([A-Z]{3})",
        "patrimonio":   r"Patrimonio\s+([\d,.]+\s*Mln[^\n]*)",
    }
    for field, pat in simple.items():
        val = _re_val(pat, text)
        if val:
            out[field] = val.strip()

    # Morningstar: stelle sono font-icon privati  (piena) e  (vuota)
    stars_m = re.search(r"Rating Morningstar\s+([]+)", text)
    if stars_m:
        count = stars_m.group(1).count("")
        if count:
            out["rating_morningstar"] = count

    return out


def parse_fineco_pdf(pdf_bytes: bytes, tipo: str) -> dict:
    """Parse a Fineco 'Scheda titolo' PDF exported from the web platform.

    Uses pdfplumber for text extraction.  Returns a dict of extracted fields,
    or ``{}`` (empty dict — never raises) if the PDF is not parsable (e.g.
    image-only PDFs generated by Microsoft Print To PDF, corrupt files, or
    unknown *tipo*).

    Parameters
    ----------
    pdf_bytes:
        Raw bytes of the PDF file.
    tipo:
        One of ``"btp"``, ``"etf"``, ``"fam"``.
    """
    try:
        import pdfplumber  # heavy — local import only
        import io
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            text = "\n".join(p.extract_text() or "" for p in pdf.pages)
    except Exception:
        return {}
    if not text.strip():
        return {}

    tipo = (tipo or "").lower()
    if tipo == "btp":
        return _parse_pdf_btp(text)
    if tipo == "etf":
        return _parse_pdf_etf(text)
    if tipo == "fam":
        return _parse_pdf_fam(text)
    return {}


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
        except Exception as exc:
            s["enrichment_error"] = str(exc)
        if s.get("enrichment_error"):
            err += 1
            msgs.append(f"{ticker}: {s['enrichment_error']}")
        else:
            ok += 1
        if on_progress:
            on_progress(i + 1, total, ticker)
    return ok, err, msgs
