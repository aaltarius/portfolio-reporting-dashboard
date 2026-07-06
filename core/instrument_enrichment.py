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
    if any(k in t for k in ("fond", "fam", "bilanc", "fless", "flex", "multi", "obbl. m", "az. pass", "passivo")):
        return "fondo"
    return "etf"


def _extract_yahoo_alt(fonte: str) -> Optional[str]:
    m = re.search(r"Yahoo\s*\[(.+?)\]", str(fonte or ""))
    return m.group(1) if m else None


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


import unicodedata as _unicodedata


_APOSTROPHES_RE = re.compile(r"[‘’‛′`´]")


def _norm_line(line: str) -> str:
    """Lowercase, strip accents/typographic apostrophes, collapse inline whitespace.

    Non-Fineco factsheet (iShares/Franklin/DWS/Amundi) use curly apostrophes
    (l'indice, d'investimento) that NFD accent-stripping doesn't touch since
    they aren't combining-diacritic sequences; stripped here so labels can be
    written without worrying about which apostrophe glyph a given PDF uses.
    """
    nfd = _unicodedata.normalize("NFD", line)
    no_acc = "".join(c for c in nfd if _unicodedata.category(c) != "Mn")
    no_apo = _APOSTROPHES_RE.sub("", no_acc)
    return re.sub(r"[ \t]+", " ", no_apo).strip().lower()


# ---------------------------------------------------------------------------
# Master label→(field, value_type) dictionary for PDF parsing.
# Keys are pre-normalized (no accents, lowercase, single spaces).
# Sorted longest-first at scan time so longer labels win over shorter ones.
# value_type: "percent" | "number" | "last_number" | "date" | "token" | "text"
# ---------------------------------------------------------------------------
_PDF_LABELS: dict[str, tuple[str, str]] = {
    # Costs
    "commissioni gestione e altri costi":        ("ter",                 "percent"),
    "commissione gestione annua":                ("ter",                 "percent"),
    "total expense ratio":                       ("ter",                 "percent"),
    "commissione annuale massima":                ("ter",                 "percent"),
    # Risk
    "deviazione standard":                       ("deviazione_std",      "percent"),
    "indice di sharpe":                          ("sharpe",              "number"),
    "indice beta":                               ("beta",                "number"),
    "var":                                       ("var",                 "number"),
    # Returns / pricing
    "rendimento medio":                          ("rendimento_medio",    "percent"),
    "dividend yield":                            ("dividend_yield",      "number"),
    "price / earnings":                          ("price_earnings",      "number"),
    "price to book value":                       ("price_to_book",       "number"),
    "nav":                                       ("nav",                 "last_number"),
    "patrimonio netto":                          ("patrimonio",          "last_number"),
    "patrimonio":                                ("patrimonio",          "last_number"),
    # Identity / classification
    "isin":                                      ("isin",                "token"),
    "emittente":                                 ("emittente",           "text"),
    "benchmark":                                 ("benchmark",           "text"),
    "categoria ms":                              ("categoria_fam",       "text"),
    "categoria":                                 ("categoria_etf",       "text"),
    "specializzazione":                          ("specializzazione",    "token"),
    "fiscalita":                                 ("fiscalita",           "token"),
    "domicilio":                                 ("domicilio",           "token"),
    # Dates
    "data di partenza":                          ("data_lancio",         "date"),
    "data di lancio":                            ("data_lancio",         "date"),
    "data lancio":                               ("data_lancio",         "date"),
    "data emissione":                            ("data_emissione",      "date"),
    "data godimento":                            ("data_godimento",      "date"),
    "prossima cedola":                           ("prossima_cedola",     "date"),
    # Valuta (longer alias first: se una di queste matcha, la bare "valuta"
    # sotto viene saltata — evita che catturi la parola "valuta" nel testo
    # legale boilerplate sul rischio cambio, presente in quasi ogni factsheet)
    "valuta nav":                                ("valuta",              "token"),
    "valuta di base":                            ("valuta",              "token"),
    "valuta del fondo":                          ("valuta",              "token"),
    "valuta":                                    ("valuta",              "token"),
    # BTP-specific
    "rendimento effettivo a scadenza netto":     ("ytm_netto",           "percent"),
    "rendimento effettivo a scadenza lordo":     ("ytm_lordo",           "percent"),
    "rendimento netto a scadenza":               ("ytm_netto",           "percent"),
    "cedola annuale":                            ("cedola_annuale",      "percent"),
    "tasso cedola periodale":                    ("cedola_tasso",        "percent"),
    "rateo lordo":                               ("rateo_lordo",         "text"),
    "rateo netto":                               ("rateo_netto",         "text"),
    "rateo interessi":                           ("rateo_interessi",     "text"),
    "rateo di disaggio":                         ("rateo_disaggio",      "number"),
    "ritenute totali":                           ("ritenute_totali",     "number"),
    "duration modificata":                       ("duration_modificata", "number"),
    "tipo cedola in corso":                      ("tipo_cedola",         "token"),
    "tipo cedola":                               ("tipo_cedola",         "token"),
    "periodicita cedola":                        ("cedola_frequenza",    "token"),
    "frequenza cedola":                          ("cedola_frequenza",    "token"),
    "struttura bond":                            ("struttura",           "text"),
    "prezzo emissione":                          ("prezzo_emissione",    "number"),
    "prezzo rimborso":                           ("prezzo_rimborso",     "number"),
    "scadenza":                                  ("scadenza",            "date"),
    "rating emittente":                          ("rating_emittente",    "token"),
}

_NO_VALUE: frozenset = frozenset({"-", "--", "n.d.", "n/d", "—", "vedi composizione", ""})
_DATE_RE_VAL  = re.compile(r"\d{2}[/.]\d{2}[/.]\d{4}")
_PCT_RE_VAL   = re.compile(r"[+\-]?\s*\d+[,.]?\d*\s*%")
_NUM_RE_VAL   = re.compile(r"\d[\d.,]*")
_LEADING_PUNCT_RE = re.compile(r"^[:\-–—\s]+")


def _extract_typed_value(remainder: str, next_line: str, vtype: str) -> Optional[str]:
    """Return a typed value from *remainder* (rest of label's line) or *next_line* fallback.

    Some issuers print "Label :Valore" (colon glued to the value, e.g. Amundi
    "Codice ISIN :FR0010754200") rather than Fineco's "Label Valore" — strip
    any such leading separator before token/text parsing.
    """
    src = remainder.strip() if remainder.strip() else next_line.strip()
    src = _LEADING_PUNCT_RE.sub("", src)

    if vtype == "percent":
        m = _PCT_RE_VAL.search(remainder) or _PCT_RE_VAL.search(next_line)
        return m.group(0).strip() if m else None

    if vtype == "number":
        m = _NUM_RE_VAL.search(remainder) or _NUM_RE_VAL.search(next_line)
        return m.group(0) if m else None

    if vtype == "last_number":
        nums = _NUM_RE_VAL.findall(remainder)
        if nums:
            return nums[-1]
        nums = _NUM_RE_VAL.findall(next_line)
        return nums[-1] if nums else None

    if vtype == "date":
        m = _DATE_RE_VAL.search(remainder) or _DATE_RE_VAL.search(next_line)
        if not m:
            return None
        raw = m.group(0)  # "DD/MM/YYYY" (Fineco) o "DD.MM.YYYY" (es. Franklin Templeton)
        for fmt in ("%d/%m/%Y", "%d.%m.%Y"):
            try:
                return datetime.datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
        return raw

    if vtype == "token":
        parts = src.split()
        val = parts[0] if parts else None
        return val if val and val.lower() not in _NO_VALUE else None

    # vtype == "text"
    val = src
    if val and val.lower() not in _NO_VALUE and not _looks_like_bled_text(val):
        return val
    return None


_TEXT_VALUE_BAD_PREFIXES = ("eu sfdr", "sfdr")


def _looks_like_bled_text(val: str) -> bool:
    """True se *val* sembra testo "sbordato" da una colonna/tabella adiacente
    invece del vero valore dell'etichetta — capita nei factsheet a piu'
    colonne (iShares/Franklin, Amundi) dove pdfplumber unisce righe di
    colonne diverse alla stessa altezza, o quando l'etichetta e' in realta'
    l'intestazione di una tabella (es. "Emittente ISIN Ponderazione")."""
    norm = _norm_line(val)
    if norm.startswith(_TEXT_VALUE_BAD_PREFIXES):
        return True
    first_word = norm.split()[0] if norm.split() else ""
    return first_word in _PDF_LABELS


def _scan_labels(text: str) -> dict:
    """Scan extracted PDF text for known labels; return {field: value} dict.

    Labels are tried longest-first so that longer labels (e.g. "Categoria MS")
    win over shorter prefix labels (e.g. "Categoria") when both start at the
    same word position.  A consumed-span set prevents a single word-position
    from being matched by two different labels.

    Labels may appear anywhere on a line, not only at line-start.  This
    handles PDFs that pack multiple fields onto one physical line (e.g.
    "Nav 141,58  Commissioni gestione e altri costi 0,12%") as well as ISINs
    preceded by token prefixes ("CFD ISIN IE00BGV5VN51").

    Deliberately does NOT try to recognize a label glued to punctuation with
    no surrounding space (e.g. "(NAV)"): on dense multi-column factsheets
    (iShares/Franklin, Amundi) pdfplumber often merges an unrelated column's
    text onto the same line, and "(NAV)" mentioned in disclaimer prose vastly
    outnumbers genuine "(NAV): value" field rows — matching it there produced
    more wrong extractions than right ones when tested against real sample
    factsheets, so plain-Fineco-style "Label Value" (space-separated) stays
    the only recognized shape here.
    """
    out: dict = {}
    lines = text.split("\n")
    n = len(lines)
    sorted_labels = sorted(_PDF_LABELS.items(), key=lambda x: -len(x[0]))
    # consumed_spans: set of (line_idx, word_idx) pairs already claimed
    consumed_spans: set[tuple[int, int]] = set()

    for label, (field, vtype) in sorted_labels:
        if field in out:
            continue
        label_words = label.split()
        lw = len(label_words)
        for i, line in enumerate(lines):
            norm = _norm_line(line)
            if label not in norm:
                continue
            # Find first occurrence, enforce word-boundary on both sides
            pos = norm.find(label)
            if pos > 0 and norm[pos - 1] != ' ':
                continue
            end = pos + len(label)
            if end < len(norm) and norm[end] != ' ':
                continue
            # Resolve the word index where the label starts
            norm_words = norm.split()
            orig_words = line.strip().split()
            label_start_idx: Optional[int] = None
            for wi in range(len(norm_words) - lw + 1):
                if " ".join(norm_words[wi:wi + lw]) == label:
                    if (i, wi) not in consumed_spans:
                        label_start_idx = wi
                    break  # found the label position (consumed or not) — stop
            if label_start_idx is None:
                continue
            # Mark label word-positions as consumed
            for wi in range(label_start_idx, label_start_idx + lw):
                consumed_spans.add((i, wi))
            remainder = " ".join(orig_words[label_start_idx + lw:])
            next_line = lines[i + 1].strip() if i + 1 < n else ""
            val = _extract_typed_value(remainder, next_line, vtype)
            if val:
                out[field] = val
            break

    return out


_PERIOD_LABELS = [
    (r"da\s+inizio\s+anno",  "rendimento_ytd"),
    (r"\b1\s+[Aa]\b",        "rendimento_1a"),
    (r"\b2\s+[Aa]\b",        "rendimento_2a"),
    (r"\b3\s+[Aa]\b",        "rendimento_3a"),
    (r"\b5\s+[Aa]\b",        "rendimento_5a"),
    (r"\b10\s+[Aa]\b",       "rendimento_10a"),
]


def _scan_rendimenti(text: str) -> dict:
    """Extract rendimenti for all available periods (YTD, 1A, 3A, 5A, 10A).

    Handles two PDF layouts:
    - Layout A: all period labels on one line, all values on the next line.
    - Layout B: label / value pairs interleaved line by line.

    ``last_val_end`` advances past each matched value so that Layout A labels
    (whose positions all precede the value block) don't all grab the same
    first percentage.
    """
    out: dict = {}
    anchor = re.search(r"[Dd]a\s+inizio\s+anno", text)
    if not anchor:
        return out
    # Work within a 400-char window from the anchor to avoid false positives
    block = text[anchor.start(): anchor.start() + 400]
    last_val_end = 0  # absolute position in block of end of last matched value
    for pat, field in _PERIOD_LABELS:
        m = re.search(pat, block, re.IGNORECASE)
        if not m:
            continue
        # For Layout A the label sits before all values; advance past any
        # already-consumed value so we don't re-use it.
        search_from = max(m.end(), last_val_end)
        vm = _PCT_RE_VAL.search(block[search_from: search_from + 80])
        if vm:
            out[field] = vm.group(0).strip()
            last_val_end = search_from + vm.end()
    return out


def _scan_morningstar(text: str) -> dict:
    """Extract Morningstar star rating (1-5) from PDF text."""
    m = re.search(r"[Mm]orningstar\s+(.{0,40})", text)
    if not m:
        return {}
    raw = m.group(1)
    # Count filled stars: Unicode ★ or first private-use-area char (varies by font:
    # e90c in some PDFs, e912 in others -- count whichever appears first)
    count = raw.count("★")
    if not count:
        pu = next((c for c in raw if "" <= c <= ""), None)
        if pu:
            count = raw.count(pu)
    if not count:
        count = raw.count("*")
    if not count:
        dm = re.search(r"(\d)(?:/5|\s|$)", raw)
        if dm:
            count = int(dm.group(1))
    return {"rating_morningstar": count} if count and 1 <= count <= 5 else {}


def _scan_holdings(text: str) -> list:
    """Extract top-holdings from 'Primi N titoli' section."""
    m = re.search(
        r"[Pp]rimi\s+\d+\s+titoli.*?[Vv]ar%?\s*([\s\S]+?)"
        r"(?:[Aa]vvertenze|[Ee]ducational|[Dd]ati in tempo|\Z)",
        text,
        re.IGNORECASE,
    )
    if not m:
        return []
    holdings: list = []
    for line in m.group(1).strip().splitlines():
        lm = re.match(r"^(.+?)\s+([\d,]+\s*%)\s*$", line.strip())
        if lm:
            holdings.append({"nome": lm.group(1).strip(), "pct": lm.group(2).strip()})
    return holdings[:10]


def _scan_distribuzione(text: str) -> dict:
    if re.search(r"[Dd]ividendo distribuito[^-\n\d]*(\d[\d,.]*)", text):
        return {"distribuzione": "Distribuzione"}
    if re.search(r"[Dd]ividendo distribuito\s*\(-\)", text):
        return {"distribuzione": "Accumulazione"}
    # Altri emittenti (iShares/Franklin, Xtrackers/DWS, Amundi...) non usano la
    # dicitura Fineco "Dividendo distribuito": etichettano la stessa cosa come
    # "Impiego del reddito" / "Utilizzo dei proventi" / "Tipologia dei
    # dividendi", seguita da un valore preso da un piccolo vocabolario noto —
    # più sicuro di una cattura di testo libero (niente rischio di "sbordare"
    # nella colonna/paragrafo adiacente del PDF).
    for anchor in (r"[Ii]mpiego del reddito", r"[Uu]tilizzo dei proventi", r"[Tt]ipologia dei dividendi"):
        m = re.search(anchor + r"[^\n]{0,40}?(Accumulazione|Distribuzione|Capitalizzazione)", text)
        if m:
            return {"distribuzione": m.group(1)}
    return {}


def _scan_replica(text: str) -> dict:
    """Metodologia di replica da vocabolario noto (fisica/ottimizzata/sintetica),
    cercata ovunque nel testo: più robusta di una cattura per etichetta perché
    non risente del testo di colonne/paragrafi adiacenti nei factsheet a più
    colonne (iShares/Franklin, Xtrackers/DWS)."""
    m = re.search(
        r"Replica\s+(?:diretta\s*\(fisica\)|fisica|ottimizzata|completa|sintetica)"
        r"|Replica\s+sintetica\s*\(swap\)"
        r"|Sintetica(?:\s*\(swap\))?",
        text,
    )
    return {"replica": m.group(0).strip()} if m else {}


def _scan_aum(text: str) -> dict:
    """Patrimonio in gestione (AUM) come stringa con valuta e scala inclusi
    (es. "USD 8,66 miliardi", "$2,29 Mld"): un numero nudo non è confrontabile
    tra emittenti che usano valute e ordini di grandezza diversi (milioni vs
    miliardi), quindi qui si preserva l'intera espressione invece di ridurla
    a un float come fa il vtype "last_number" per il campo Fineco "patrimonio"."""
    for anchor in (r"[Pp]atrimonio in gestione", r"[Aa]ttivi amministrati del [Ff]ondo"):
        m = re.search(
            anchor + r"[^\n]{0,15}?([$€£]?\s?[A-Z]{0,3}\s?[\d.,]+\s?(?:Mld|mld|miliardi|milioni|mln|Mln|bn|Bn))",
            text,
        )
        if m:
            return {"aum": m.group(1).strip()}
    return {}


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
                    if field in {"scadenza", "data_godimento"}:
                        for _dfmt in ("%d/%m/%y", "%d/%m/%Y"):
                            try:
                                value = datetime.datetime.strptime(value, _dfmt).strftime("%Y-%m-%d")
                                break
                            except ValueError:
                                continue
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


def parse_fineco_pdf(pdf_bytes: bytes, tipo: str = "") -> dict:
    """Parse a fund/ETF factsheet PDF: Fineco's own 'Scheda titolo' export as
    well as official issuer monthly factsheets (iShares/Franklin Templeton,
    Xtrackers/DWS, Amundi/Lyxor...).

    Accepts any ETF/ETC/FAM/BTP layout without type-switching.
    Returns a dict of extracted fields, or {} if the PDF is not parsable.
    The ``tipo`` parameter is accepted for API compatibility but is not used.
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

    out: dict = {}
    out.update(_scan_labels(text))
    out.update(_scan_rendimenti(text))
    out.update(_scan_morningstar(text))
    out.update(_scan_distribuzione(text))
    out.update(_scan_replica(text))
    out.update(_scan_aum(text))

    holdings = _scan_holdings(text)
    if holdings:
        out["holdings_top"] = holdings

    return out


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

def enrich_strumento(strumento: dict) -> dict:
    cat = _categoria(strumento.get("tipo", ""))
    if cat == "btp":
        return enrich_btp(strumento)
    if cat in ("etf", "etc"):
        strumento = enrich_etf_etc(strumento)
        focus = strumento.get("focus_etf", "")
        if focus and not strumento.get("enrichment_error"):
            from core.market_data import deduce_type
            strumento["tipo"] = deduce_type(
                str(strumento.get("isin", "")), str(strumento.get("ticker", "")),
                str(strumento.get("nome", "")), focus_etf=focus,
            ) or strumento.get("tipo", "")
        return strumento
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
