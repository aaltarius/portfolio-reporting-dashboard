"""Vocabolario di TERMINI FINANZIARI GENERICI (italiano/inglese -> parola chiave).

E' l'unica tabella testuale ammessa dalla specifica: contiene concetti
(azioni, obbligazioni, governativo, energia...), mai nomi di strumenti,
ticker, ISIN o indici. Serve a trasformare i testi dell'arricchimento in
parole chiave per le frasi di ricerca e per il controllo di coerenza.
"""
from __future__ import annotations

import re

# frase o parola (minuscola) -> (parola chiave, gruppo)
TERMS: dict[str, tuple[str, str]] = {
    # tipo di strumento
    "azioni": ("equity", "kind"), "azionario": ("equity", "kind"), "equity": ("equity", "kind"),
    "obbligazioni": ("bond", "kind"), "obbligazionario": ("bond", "kind"), "obbligazione": ("bond", "kind"),
    "bond": ("bond", "kind"), "fixed income": ("bond", "kind"), "titolo di stato": ("bond", "kind"),
    "titoli di stato": ("bond", "kind"), "btp": ("bond", "kind"), "debt": ("bond", "kind"),
    "materie prime": ("commodity", "kind"), "commodities": ("commodity", "kind"), "commodity": ("commodity", "kind"),
    "criptovalute": ("crypto", "kind"), "crypto": ("crypto", "kind"), "digital assets": ("crypto", "kind"),
    "mercato monetario": ("money_market", "kind"), "money market": ("money_market", "kind"),
    "liquidita": ("money_market", "kind"), "liquidità": ("money_market", "kind"), "overnight": ("money_market", "kind"),
    "bilanciati": ("multi_asset", "kind"), "bilanciato": ("multi_asset", "kind"),
    "multi-asset": ("multi_asset", "kind"), "multi asset": ("multi_asset", "kind"),
    # area geografica
    "globale": ("global", "area"), "globali": ("global", "area"), "global": ("global", "area"), "mondiale": ("world", "area"),
    "mondo": ("world", "area"), "world": ("world", "area"),
    "europa": ("europe", "area"), "europe": ("europe", "area"), "europeo": ("europe", "area"),
    "eurozona": ("euro", "area"), "area euro": ("euro", "area"),
    "stati uniti": ("us", "area"), "usa": ("us", "area"),
    "emergenti": ("emerging", "area"), "emerging": ("emerging", "area"),
    "giappone": ("japan", "area"), "japan": ("japan", "area"),
    "italia": ("italy", "area"), "italy": ("italy", "area"), "italiano": ("italy", "area"),
    "cina": ("china", "area"), "china": ("china", "area"), "asia": ("asia", "area"),
    "sviluppati": ("developed", "area"), "developed": ("developed", "area"),
    # tema, settore, fattore
    "informatica": ("technology", "theme"), "tecnologia": ("technology", "theme"),
    "technology": ("technology", "theme"), "information technology": ("technology", "theme"),
    "energia": ("energy", "theme"), "energy": ("energy", "theme"),
    "sanita": ("health care", "theme"), "sanità": ("health care", "theme"),
    "health care": ("health care", "theme"), "healthcare": ("health care", "theme"),
    "immobiliare": ("real estate", "theme"), "real estate": ("real estate", "theme"),
    "governative": ("government", "theme"), "governativo": ("government", "theme"),
    "government": ("government", "theme"), "treasury": ("government", "theme"),
    "societarie": ("corporate", "theme"), "corporate": ("corporate", "theme"),
    "aggregate": ("aggregate", "theme"), "aggregato": ("aggregate", "theme"),
    "indicizzate all'inflazione": ("inflation linked", "theme"),
    "indicizzate all’inflazione": ("inflation linked", "theme"),
    "inflation linked": ("inflation linked", "theme"), "inflation-linked": ("inflation linked", "theme"),
    "qualità": ("quality", "theme"), "qualita": ("quality", "theme"), "quality": ("quality", "theme"),
    "bassa volatilità": ("minimum volatility", "theme"), "minimum volatility": ("minimum volatility", "theme"),
    "piccole imprese": ("small cap", "theme"), "small cap": ("small cap", "theme"),
    "metalli preziosi": ("precious metals", "theme"), "precious metals": ("precious metals", "theme"),
    "artificial intelligence": ("artificial intelligence", "theme"),
    "intelligenza artificiale": ("artificial intelligence", "theme"), "big data": ("artificial intelligence", "theme"),
    "govt": ("government", "theme"), "trsy": ("government", "theme"), "gov": ("government", "theme"),
    "infl lkd": ("inflation linked", "theme"), "inf tech": ("technology", "theme"), "info tech": ("technology", "theme"),
    "minimum vol": ("minimum volatility", "theme"), "min vol": ("minimum volatility", "theme"),
    "minim vol": ("minimum volatility", "theme"), "metals and mining": ("metals mining", "theme"),
    "wld": ("world", "area"), "wrld": ("world", "area"),
    "oro": ("gold", "theme"), "gold": ("gold", "theme"),
    "metalli e miniere": ("metals mining", "theme"), "metals mining": ("metals mining", "theme"),
}

# concetti che implicano altri concetti (un titolo di Stato e' obbligazione governativa)
IMPLIES = {
    "titolo di stato": ["government"], "titoli di stato": ["government"], "btp": ["government", "italy"],
}

# tipo -> formulazioni generiche da cercare (livelli 3 e 4)
KIND_QUERIES = {
    "equity": ["equity"],
    "bond": ["bond", "aggregate bond", "government bond"],
    "commodity": ["commodities"],
    "crypto": ["crypto", "bitcoin"],
    "money_market": ["money market", "overnight rate"],
    "multi_asset": ["multi asset allocation"],
}

# abbreviazioni correnti nei nomi dei fornitori (per il controllo di coerenza)
ABBREVIATIONS = {
    "bd": "bond", "bnd": "bond", "gov": "government", "govt": "government", "gl": "global", "glob": "global",
    "wrld": "world", "wrd": "world", "wld": "world", "eo": "euro", "eur": "euro", "infl": "inflation", "lkd": "linked",
    "inf": "inflation", "techn": "technology", "tech": "technology", "inform": "information", "ene": "energy",
    "enrg": "energy", "hlth": "health", "mkts": "markets", "em": "emerging", "sc": "small cap",
}

# valuta di quotazione dal suffisso di borsa (convenzione dei fornitori); senza suffisso: mercato USA
SUFFIX_CURRENCY = {
    ".MI": "EUR", ".DE": "EUR", ".F": "EUR", ".AS": "EUR", ".PA": "EUR", ".MU": "EUR", ".BE": "EUR", ".SG": "EUR",
    ".BR": "EUR", ".MC": "EUR", ".VI": "EUR", ".HE": "EUR", ".IR": "EUR", ".LS": "EUR", ".DU": "EUR", ".HM": "EUR",
    ".SW": "CHF", ".L": "GBP", ".IL": "GBP", ".TO": "CAD", ".V": "CAD", ".KS": "KRW", ".T": "JPY", ".HK": "HKD",
    ".AX": "AUD", ".SS": "CNY", ".SZ": "CNY", ".ST": "SEK", ".OL": "NOK", ".CO": "DKK",
}


def listing_currency(symbol: str) -> str:
    sym = str(symbol or "").upper()
    if sym.startswith("^"):
        return "USD" if "." not in sym else SUFFIX_CURRENCY.get("." + sym.rsplit(".", 1)[-1], "")
    if "." in sym:
        return SUFFIX_CURRENCY.get("." + sym.rsplit(".", 1)[-1], "")
    return "USD"


# aree equivalenti nel nome di un candidato
AREA_EQUIVALENTS = {"europe": ["europe", "euro"], "euro": ["euro", "europe"]}

# forma estesa con cui i prodotti nominano certe aree
AREA_PHRASES = {"emerging": "emerging markets"}

# parole che indicano una regione precisa nel nome di un candidato (un prodotto globale non e' regionale)
REGION_WORDS = {
    "europe", "euro", "eurozone", "usa", "us", "canada", "canadian", "japan", "japanese", "china", "chinese",
    "emerging", "italy", "italian", "germany", "german", "swiss", "korea", "korean", "india", "indian",
    "brazil", "australia", "asia", "pacific", "uk", "british",
}

# prodotti a leva, inversi o con strategia di opzioni sopra: non sono benchmark di uno strumento ordinario
STRATEGY_WORDS = {"leveraged", "leverage", "inverse", "inv", "bull", "bear", "2x", "3x", "1x"}
STRATEGY_PAIRS = (("premium", "income"), ("covered", "call"), ("buffer", "protect"))

# aree troppo generiche per essere richieste nel nome di un candidato
WEAK_AREAS = {"global", "world", "developed"}

# parole che il nome di un candidato deve contenere perche' sia dello stesso tipo
KIND_NAME_WORDS = {
    "bond": ["bond", "treasury", "debt", "govt"],
    "money_market": ["overnight", "money", "rate", "cash", "estr", "ovni"],
    "crypto": ["bitcoin", "btc", "crypto", "ether", "digital"],
    "commodity": ["commodity", "comm", "gold", "silver", "metal", "oil", "precious"],
}

_NORMALIZE = re.compile(r"[,;/()\[\]]+")


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", _NORMALIZE.sub(" ", str(text or "").lower().replace("&", " and ")))


def translate(text: str) -> list[str]:
    """Parole chiave generiche presenti nel testo, senza ripetizioni, nell'ordine di comparsa."""
    s = f" {_normalise(text)} "
    found: list[tuple[float, str]] = []
    for term in sorted(TERMS, key=len, reverse=True):
        pat = re.compile(rf"(?<![a-zà-ù]){re.escape(term)}(?![a-zà-ù])")
        for m in pat.finditer(s):
            found.append((m.start(), TERMS[term][0]))
            for extra in IMPLIES.get(term, []):
                found.append((m.start() + 0.5, extra))
    out: list[str] = []
    for _, kw in sorted(found):
        if kw not in out:
            out.append(kw)
    return out


def group_of(keyword: str) -> str:
    for kw, group in TERMS.values():
        if kw == keyword:
            return group
    return ""
