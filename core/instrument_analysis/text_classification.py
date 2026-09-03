"""Classificazione da testo libero (nome + benchmark + testo emittente) in
uno `structural_type` canonico e campi ausiliari — porting fedele della
parte testuale di POC17.2 `profile()` + `structural_type()`
(HANDOFF_PROGRAMMATORE_BENCHMARK_CDS/reference/poc17_2_engine_CDS_BASELINE_REFERENCE.py,
righe 1022-1158), ristretto ai segnali derivabili da testo — stessi token,
stesso ordine di priorita' del prototipo validato a 99.4/100.

Esplicitamente fuori scope (richiedono nuove fonti dati, non solo testo,
per costruzione dell'evidenza — non semplicemente non ancora scritte):
- multiasset da composizione fondo reale (POC17.2 `mix(e)` legge
  `e.asset_classes`, un breakdown di fondo che nessun adapter espone oggi);
- duration_years da yfinance bond_holdings o range numerici nel testo
  (POC17.2 `yahoo_duration`/regex su "0-1"/"1-3" anni);
- hedged=False per assenza di segnale (POC17.2 lo deduce da `e.currency`,
  dato che non abbiamo qui) — solo hedged=True esplicito da testo e'
  affidabile senza inventare.

`_derive_view()`/`_structural_type()` in cds.py restano l'unica sede della
decisione strutturale finale: questo modulo produce un valore diretto per
`InstrumentProfile.structural_type` (che vince per `_resolve_structural_type`,
"il tipo dichiarato nel profilo vince") solo quando il testo e' abbastanza
esplicito da bastare da solo — non duplica ne' reinterpreta la logica di
cds.py, la precede."""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass


def ascii_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(c for c in normalized if not unicodedata.combining(c)).strip().lower()


#: POC17.2 righe 973-986.
THEME_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("clean_energy", (" clean energy ", " renewable energy ", " solar ", " wind ", " hydrogen ")),
    ("water", (" global water ", " water index ", " water ucits ")),
    ("robotics", (" robotics ", " automation ", " robo global ")),
    ("artificial_intelligence", (" artificial intelligence ", " ai & big data ", " ai and big data ")),
    ("cybersecurity", (" cyber security ", " cybersecurity ", " digital security ")),
    ("digitalisation", (" digitalisation ", " digitalization ")),
    ("battery", (" battery ", " batteries ")),
    ("gaming_esports", (" gaming ", " esports ", " e-sports ")),
    ("agribusiness", (" agribusiness ", " agriculture ")),
    ("ageing", (" ageing ", " aging population ")),
    ("electric_mobility", (" electric vehicle ", " electric vehicles ", " mobility ")),
    ("infrastructure", (" infrastructure ",)),
)

#: POC17.2 righe 1057-1065.
_FACTOR_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("minimum_volatility", (" minimum volatility ", " min volatility ", " low volatility ")),
    ("low_beta", (" low beta ",)),
    ("quality", (" quality factor ", " sector neutral quality ", " quality index ")),
    ("value", (" value factor ", " enhanced value ")),
    ("momentum", (" momentum ",)),
    ("dividend", (" dividend ",)),
    ("multifactor", (" multifactor ", " multi factor ")),
    ("quality", (" wide moat ", " moat index ")),
)

#: POC17.2 riga 1072.
_SIZE_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ex_mega", (" ex mega cap ", " ex-mega cap ")),
    ("small", (" small cap ", " small-cap ", " smallcap ")),
    ("mid", (" mid cap ", " mid-cap ")),
    ("large", (" large cap ", " large-cap ")),
)

#: POC17.2 righe 1076-1089.
_SECTOR_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("technology", (" information technology ", " technology ", " technology sector ")),
    ("healthcare", (" health care ", " healthcare ")),
    ("energy", (" oil & gas ", " oil and gas ", " energy ", " energy sector ")),
    ("real_estate", (" real estate ", " reit ", " property sector ")),
    ("financials", (" financials ", " financial sector ")),
    ("industrials", (" industrials ", " industrial sector ")),
    ("utilities", (" utilities ", " utility sector ")),
    ("consumer_staples", (" consumer staples ",)),
    ("consumer_discretionary", (" consumer discretionary ",)),
    ("communication_services", (" communication services ",)),
    ("metals_mining", (" metals and mining ", " metals & mining ", " metals an ", " metals mining ")),
    ("semiconductor", (" semiconductor sector ", " semiconductors index ")),
)

#: POC17.2 righe 956-972.
_COUNTRY_ALIASES: dict[str, tuple[str, ...]] = {
    "italy": (" italy ", " italian ", " ftse mib "),
    "usa": (" usa ", " united states ", " u.s. ", " s&p 500 ", " russell 2000 "),
    "japan": (" japan ", " japanese ", " nikkei ", " topix "),
    "china": (" china ", " chinese ", " hang seng ", " csi "),
    "korea": (" korea ", " korean "),
    "india": (" india ", " indian ", " nifty ", " sensex "),
    "brazil": (" brazil ", " brazilian ", " bovespa "),
    "uk": (" united kingdom ", " uk ", " britain ", " british ", " ftse 100 "),
    "switzerland": (" switzerland ", " swiss ", " smi "),
    "australia": (" australia ", " australian ", " asx "),
    "canada": (" canada ", " canadian ", " tsx "),
    "taiwan": (" taiwan ", " taiwanese "),
    "germany": (" germany ", " german ", " dax "),
    "france": (" france ", " french ", " cac 40 "),
    "spain": (" spain ", " spanish ", " ibex "),
}

#: Indici a scala nota stretta (POC17.2 `_infer_market_breadth`, riga 1015):
#: un singolo indice-paese con questi nomi e' SINGLE_COUNTRY, non COUNTRY_BROAD,
#: anche se il paese e' altrimenti riconosciuto. Soglia 0.45 identica a
#: cds.py::_structural_type.
_NARROW_COUNTRY_INDEX_TOKENS = (" ftse mib ", " mib index ")

_STRONG_GOLD_TOKENS = (" physical gold ", " gold etc ", " gold etp ", " gold bullion ", " gold spot ")
_STRONG_CRYPTO_TOKENS = (" bitcoin ", " crypto ", " cryptocurrency ", " digital asset ", " btc ")
_STRONG_EQUITY_TOKENS = (" msci ", " ftse ", " stoxx ", " s&p ", " nasdaq ", " dow jones ", " russell ", " equity ", " azionario ")
_STRONG_BOND_TOKENS = (
    " government bond ", " govt bond ", " sovereign bond ", " treasury bond ",
    " corporate bond ", " aggregate bond ", " aggr bond ", " fixed income ",
    " obbligazionario ", " ibonds ", " inflation linked ", " inflation-linked ",
    " inf-link ", " high yield ", " emerging markets debt ",
    # Varianti reali di abbreviazione "aggregate bond" viste in produzione,
    # assenti dalla lista di POC17.2 (validata su testo non troncato): Yahoo/
    # Borsa Italiana abbreviano "Agg Bond" (es. XBAE.MI, "Xtrackers Ii Esg
    # Glo Agg Bond Ucits Etf"), OpenFIGI abbrevia "AGGR BND" — nessuna delle
    # due contiene la frase intera " aggregate bond "/" aggr bond ", quindi
    # lo strumento cadeva nel ramo equity per il solo token " msci " nel
    # benchmark ufficiale.
    " agg bond ", " agg bnd ", " aggr bnd ",
)
_STRONG_COMMODITY_TOKENS = (" commodity ", " commodities ", " comdty ")
_MONEY_MARKET_TOKENS = (" overnight ", " estr ", " money market ")

_BOND_GOVERNMENT_TOKENS = (" government ", " govt ", " treasury ", " sovereign ")
_BOND_AGGREGATE_TOKENS = (" aggregate ", " aggr ")
_BOND_INFLATION_LINKED_TOKENS = (" inflation-linked ", " inflation linked ", " inf-link ")
_HEDGED_TOKENS = (" hedged ", " currency neutral ")


@dataclass(slots=True)
class TextClassification:
    structural_type: str = ""
    geography: str = ""
    geo_scope: str = ""
    theme: str = ""
    factor: str = ""
    size: str = ""
    sector: str = ""
    issuer_type: str = ""
    bond_style: str = ""
    hedged: bool | None = None


def _match_first(v: str, patterns: tuple[tuple[str, tuple[str, ...]], ...]) -> str:
    for label, tokens in patterns:
        if any(token in v for token in tokens):
            return label
    return ""


def _detect_geography(v: str) -> tuple[str, str]:
    """POC17.2 `_detect_geography`, righe 988-1004."""
    for country, aliases in _COUNTRY_ALIASES.items():
        if any(alias in v for alias in aliases):
            return country, "country"
    if " emerging " in v or " em imi " in v or " emerging markets " in v:
        return "emerging", "regional"
    if any(x in v for x in (" world ", " global ", " all-world ", " all world ", " acwi ")):
        return "world", "global"
    if any(x in v for x in (" europe ", " eurozone ", " euro area ", " stoxx europe ", " euro stoxx ")):
        return "europe", "regional"
    return "", ""


def classify(text: str) -> TextClassification:
    result = TextClassification()
    raw = str(text or "").strip()
    if not raw:
        return result

    v = f" {ascii_text(raw)} "

    if any(token in v for token in _STRONG_GOLD_TOKENS):
        result.structural_type = "GOLD"
        return result
    if any(token in v for token in _STRONG_CRYPTO_TOKENS):
        result.structural_type = "DIGITAL_ASSET"
        return result
    if any(token in v for token in _MONEY_MARKET_TOKENS):
        result.structural_type = "MONEY_MARKET"
        return result

    theme = _match_first(v, THEME_PATTERNS)
    #: Un token di settore o di factor (POC17.2 `sectors`/`factors`, righe
    #: 1076/1057) e' di per se' un segnale equity forte quanto quelli
    #: espliciti — non esiste un "Technology"/"Wide Moat" obbligazionario
    #: nel naming ETF reale (visto su MOAT.MI, "Vaneck Mstar Us Esg Wide
    #: Moat Ucits Etf": nessun token di `_STRONG_EQUITY_TOKENS`, solo
    #: "wide moat") — per questo entrano nel gate `strong_equity` anche se
    #: assenti dalla lista `_STRONG_EQUITY_TOKENS` originale del prototipo
    #: (che si appoggiava anche su `mix(e)`, non disponibile qui, solo testo).
    sector = "" if theme else _match_first(v, _SECTOR_PATTERNS)
    factor = "" if (theme or sector) else _match_first(v, _FACTOR_PATTERNS)
    strong_equity = bool(theme) or bool(sector) or bool(factor) or any(token in v for token in _STRONG_EQUITY_TOKENS)
    strong_bond = any(token in v for token in _STRONG_BOND_TOKENS)
    strong_commodity = any(token in v for token in _STRONG_COMMODITY_TOKENS)

    geography, geo_scope = _detect_geography(v)
    result.geography = geography
    result.geo_scope = geo_scope

    if strong_bond:
        result.bond_style = "inflation_linked" if any(token in v for token in _BOND_INFLATION_LINKED_TOKENS) else "nominal_fixed"
        if any(token in v for token in _BOND_GOVERNMENT_TOKENS):
            result.issuer_type = "government"
        elif any(token in v for token in _BOND_AGGREGATE_TOKENS):
            result.issuer_type = "aggregate"
        elif " corporate " in v:
            result.issuer_type = "corporate"

        if result.bond_style == "inflation_linked":
            result.structural_type = "INFLATION_LINKED_BOND"
        elif result.issuer_type == "aggregate":
            result.structural_type = "AGGREGATE_BOND"
        elif result.issuer_type == "government":
            result.structural_type = "GOV_BOND"
        else:
            result.structural_type = "BOND"

        if any(token in v for token in _HEDGED_TOKENS):
            result.hedged = True
        return result

    if strong_commodity:
        result.structural_type = "COMMODITY"
        return result

    if not strong_equity:
        return result

    result.theme = theme
    if theme:
        result.structural_type = "THEMATIC_EQUITY"
        return result

    if sector:
        result.sector = sector
        result.structural_type = "SECTOR_" + sector.upper()
        return result

    if factor:
        result.factor = factor
        result.structural_type = "FACTOR_" + factor.upper()
        return result

    size = _match_first(v, _SIZE_PATTERNS)
    if size == "small":
        result.size = size
        result.structural_type = "SMALL_CAP_EQUITY"
        return result
    if size == "ex_mega":
        result.size = size
        result.structural_type = "EX_MEGA_CAP_EQUITY"
        return result

    if geography == "emerging":
        result.structural_type = "EMERGING_BROAD_EQUITY"
        return result

    if geo_scope == "country":
        if any(token in v for token in _NARROW_COUNTRY_INDEX_TOKENS):
            result.structural_type = "SINGLE_COUNTRY_EQUITY"
        else:
            result.structural_type = "COUNTRY_BROAD_EQUITY"
        return result

    result.structural_type = "BROAD_EQUITY"
    return result
