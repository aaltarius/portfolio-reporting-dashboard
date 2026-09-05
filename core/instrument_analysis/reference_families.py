"""Catalogo statico famiglie -> ticker reali e ladder intermedio
(CUGINA/ZIA/NONNA), porting fedele di POC17.2 `REFERENCE_FAMILIES`/
`_profile_family_ladder` (righe 2307/3287 di
`HANDOFF_PROGRAMMATORE_BENCHMARK_CDS/reference/poc17_4_engine_VALIDATED_REFERENCE.py`).

Catalogo fisso, non una ricerca web (compatibile col vincolo "no Google/
DuckDuckGo" dello spec sezione 4). Le 6 chiavi duplicate nell'originale
(FINANCIALS/INDUSTRIALS/UTILITIES/CONSUMER_STAPLES/CONSUMER_DISCRETIONARY/
COMMUNICATION_SERVICES comparivano due volte identiche, copy-paste) sono
qui presenti una sola volta.

Mapping gradi POC -> `RelationGrade` di questo progetto: "CUGINA" ->
COUSIN, "PARENTE" -> AUNT, "ZIA LONTANA" (ultima rete, mercato globale)
-> GRANDMOTHER. `BROAD_FAMILY` non ha equivalente diretto in POC, non
prodotto qui — riservato al composite multi-famiglia (gap 4)."""
from __future__ import annotations

from core.instrument_analysis.contracts import InstrumentProfile, RelationGrade

REFERENCE_FAMILIES: dict[str, tuple[str, ...]] = {
    "GLOBAL_EQUITY": ("^GSPC", "^IXIC"),
    "USA_EQUITY": ("^GSPC", "^DJI", "^IXIC"),
    "EUROPE_EQUITY": ("^STOXX50E", "^FTSE", "^GDAXI"),
    #: EEM (iShares MSCI Emerging Markets) aggiunto 2026-09-05 - bug reale
    #: segnalato dall'utente: XMME.MI (Xtrackers MSCI Emerging Markets,
    #: identita' ufficiale "MSCI EMERGING MARKET") riceveva ^GSPC (riga
    #: GLOBAL_EQUITY, geometry 57,65) come proxy scaricabile invece di un
    #: indice Emergenti vero, perche' questa riga aveva solo indici di
    #: singolo paese (Hong Kong/Cina/India) che non superano la soglia di
    #: geometria per un fondo Emergenti diversificato. Verificato con
    #: geometry_score reale sui dati del portafoglio: EEM 92,89 contro
    #: ^GSPC 57,65, ^HSI 18,00, 000001.SS 41,55, ^BSESN 18,63 - EEM vince
    #: nettamente sia per semantica (stessa famiglia) sia per tracking.
    "EMERGING_EQUITY": ("EEM", "^HSI", "000001.SS", "^BSESN"),
    "SMALL_CAP": ("^RUT",),
    "TECH_GROWTH": ("^NDX", "^IXIC"),
    "ENERGY": ("^GSPE",),
    "MATERIALS": ("^SP500-15",),
    "HEALTHCARE": ("^SP500-35",),
    "REAL_ESTATE": ("^SP500-60", "^DJUSRE"),
    "FINANCIALS": ("^SP500-40",),
    "INDUSTRIALS": ("^SP500-20",),
    "UTILITIES": ("^SP500-55",),
    "CONSUMER_STAPLES": ("^SP500-30",),
    "CONSUMER_DISCRETIONARY": ("^SP500-25",),
    "COMMUNICATION_SERVICES": ("^SP500-50",),
    "COMMODITY": ("^SPGSCI", "^BCOM"),
    "GOLD": ("GC=F",),
    "BITCOIN": ("BTC-USD",),
    #: Famiglie bond/money-market (Task N1, 2026-09-02) — non presenti nel
    #: POC17.2 originale (`_profile_family_ladder` le esclude, `if
    #: p.asset!="equity": return ladder`). Proxy ETF obbligazionari liquidi
    #: reali (non indici puri — coerente con GOLD/BITCOIN sopra, gia' non
    #: indici in senso stretto), verificati con geometry_score reale contro
    #: strumenti bond della fixture prima di aggiungerli (vedi piano, tabella
    #: Task N1): 7/9 fetchable superano il gate di qualita' (40) subito.
    "GOV_BOND_SHORT": ("SHY",),   # iShares 1-3 Year Treasury Bond
    "GOV_BOND_MED": ("IEF",),     # iShares 7-10 Year Treasury Bond
    "GOV_BOND_LONG": ("TLT",),    # iShares 20+ Year Treasury Bond
    "AGG_BOND": ("AGG", "BND"),   # iShares/Vanguard Core Aggregate Bond
    "CORP_BOND": ("LQD",),        # iShares Investment Grade Corporate Bond
    "INFLATION_BOND": ("TIP", "STIP"),  # iShares TIPS Bond / 0-5 Year TIPS
    "MONEY_MARKET_PROXY": ("BIL", "SHV"),  # SPDR/iShares 1-3 Month T-Bill
    #: Famiglie bond mirate (2026-09-03, richiesta esplicita dell'utente
    #: dopo aver visto BTP/FAM-EMD cadere su fallback deboli: "basta il
    #: confronto con qualsiasi indice obbligazionario nazionale... senza
    #: complicarci troppo la vita") — verificate con geometry_score reale
    #: prima di aggiungerle: EMB contro FAM-EMD (fondo debito EM reale)
    #: 64,1 (ben sopra soglia 40, contro 34-38 di CORP_BOND/AGG_BOND
    #: americani); EDMA.MU e' l'unico ETF Italia govt bond trovato con
    #: storico Yahoo reale (254 osservazioni).
    "EM_BOND": ("EMB", "EMLC"),               # iShares JPM USD EM Bond / VanEck EM Local Currency Bond
    "ITALY_GOV_BOND": ("EDMA.MU",),           # iShares Italy Govt Bond UCITS ETF
    #: Famiglie paese-specifiche (Task P, 2026-09-03) — `text_classification.py`
    #: riconosce gia' 15 paesi (`_COUNTRY_ALIASES`) ma solo 2 (usa, "italy"
    #: instradata su EUROPE_EQUITY) avevano una famiglia dedicata: gli altri
    #: 13 cadevano tutti su GLOBAL_EQUITY (indici USA) per costruzione —
    #: trovato analizzando i 32 strumenti nella fascia 70-80 del replay
    #: ufficiale (4 fondi Giappone, 1 Cina, 1 UK confrontati con S&P 500/
    #: Nasdaq invece che coi rispettivi indici nazionali). Selezione best-
    #: across-all-rows (Task P sopra) rende sicuro aggiungerli: se il
    #: confronto nazionale traccia peggio del generico GLOBAL_EQUITY (visto
    #: su alcuni fondi Giappone value/small — non tutti i fondi "Japan"
    #: tracciano il Nikkei 225 large-cap), il generico resta comunque
    #: disponibile come alternativa e vince sul punteggio combinato finale.
    "JAPAN_EQUITY": ("^N225",),
    "CHINA_EQUITY": ("^HSI", "000001.SS"),
    "KOREA_EQUITY": ("^KS11",),
    "INDIA_EQUITY": ("^NSEI", "^BSESN"),
    "BRAZIL_EQUITY": ("^BVSP",),
    "UK_EQUITY": ("^FTSE",),
    "SWITZERLAND_EQUITY": ("^SSMI",),
    "AUSTRALIA_EQUITY": ("^AXJO",),
    "CANADA_EQUITY": ("^GSPTSE",),
    "TAIWAN_EQUITY": ("^TWII",),
    "GERMANY_EQUITY": ("^GDAXI",),
    "FRANCE_EQUITY": ("^FCHI",),
    "SPAIN_EQUITY": ("^IBEX",),
    "ITALY_EQUITY": ("FTSEMIB.MI",),
}

_EQUITY_STRUCTURAL_TYPES = frozenset({
    "BROAD_EQUITY", "THEMATIC_EQUITY", "SMALL_CAP_EQUITY", "EX_MEGA_CAP_EQUITY",
    "EMERGING_BROAD_EQUITY", "SINGLE_COUNTRY_EQUITY", "COUNTRY_BROAD_EQUITY",
})

_SECTOR_FAMILY: dict[str, str] = {
    "technology": "TECH_GROWTH", "energy": "ENERGY",
    "metals_mining": "MATERIALS", "materials": "MATERIALS",
    "healthcare": "HEALTHCARE", "real_estate": "REAL_ESTATE",
    "financials": "FINANCIALS", "industrials": "INDUSTRIALS",
    "utilities": "UTILITIES", "consumer_staples": "CONSUMER_STAPLES",
    "consumer_discretionary": "CONSUMER_DISCRETIONARY",
    "communication_services": "COMMUNICATION_SERVICES",
}

_GEO_BROAD_FAMILY: dict[str, tuple[str, float]] = {
    "usa": ("USA_EQUITY", 0.70),
    "europe": ("EUROPE_EQUITY", 0.70),
    "italy": ("EUROPE_EQUITY", 0.70),
    "emerging": ("EMERGING_EQUITY", 0.68),
    "world": ("GLOBAL_EQUITY", 0.68),
    "": ("GLOBAL_EQUITY", 0.68),
}

#: Indice nazionale specifico (Task P) — grado CUGINA, piu' stretto della
#: riga AUNT/GLOBAL_EQUITY di `_GEO_BROAD_FAMILY` sopra. Non sostituisce
#: quella riga: entrambe entrano nel ladder, vince quella col punteggio
#: combinato migliore (`_best_ladder_match` in benchmark.py).
_COUNTRY_SPECIFIC_FAMILY: dict[str, str] = {
    "japan": "JAPAN_EQUITY", "china": "CHINA_EQUITY", "korea": "KOREA_EQUITY",
    "india": "INDIA_EQUITY", "brazil": "BRAZIL_EQUITY", "uk": "UK_EQUITY",
    "switzerland": "SWITZERLAND_EQUITY", "australia": "AUSTRALIA_EQUITY",
    "canada": "CANADA_EQUITY", "taiwan": "TAIWAN_EQUITY", "germany": "GERMANY_EQUITY",
    "france": "FRANCE_EQUITY", "spain": "SPAIN_EQUITY", "italy": "ITALY_EQUITY",
}

_FACTOR_PARENT_FAMILY: dict[str, str] = {
    "usa": "USA_EQUITY",
    "europe": "EUROPE_EQUITY",
}


def _is_equity(structural_type: str) -> bool:
    return (
        structural_type in _EQUITY_STRUCTURAL_TYPES
        or structural_type.startswith("SECTOR_")
        or structural_type.startswith("FACTOR_")
    )


def family_ladder(profile: InstrumentProfile) -> list[tuple[RelationGrade, float, str, str]]:
    structural_type = str(profile.structural_type or "")

    if structural_type == "DIGITAL_ASSET":
        return [(RelationGrade.COUSIN, 0.92, "BITCOIN", "digital-asset market reference")]
    if structural_type == "GOLD":
        return [
            (RelationGrade.COUSIN, 0.84, "GOLD", "physical gold market reference"),
            (RelationGrade.AUNT, 0.62, "COMMODITY", "broad commodity reference"),
        ]
    if structural_type == "COMMODITY":
        return [(RelationGrade.COUSIN, 0.78, "COMMODITY", "broad commodity index")]

    #: Bond/money-market (Task N1) — assenti dal ladder equity POC17.2 per
    #: design. Ordine SHORT->MED->LONG per i governativi: euristica, non
    #: verificata strumento per strumento (nessun `duration_years` reale
    #: disponibile, vedi limitazioni note di `text_classification.py`) — ma
    #: verificata empiricamente sui BTP della fixture (XBOT.MI/26TA.MI:
    #: SHY batte nettamente IEF e TLT).
    if structural_type == "MONEY_MARKET":
        return [(RelationGrade.COUSIN, 0.75, "MONEY_MARKET_PROXY", "short-term rate proxy")]
    if structural_type == "GOV_BOND":
        return [
            (RelationGrade.COUSIN, 0.75, "GOV_BOND_SHORT", "short-duration government bond proxy"),
            (RelationGrade.COUSIN, 0.70, "GOV_BOND_MED", "medium-duration government bond proxy"),
            (RelationGrade.AUNT, 0.60, "GOV_BOND_LONG", "long-duration government bond proxy"),
        ]
    if structural_type == "AGGREGATE_BOND":
        return [(RelationGrade.COUSIN, 0.78, "AGG_BOND", "aggregate bond proxy")]
    if structural_type == "INFLATION_LINKED_BOND":
        return [(RelationGrade.COUSIN, 0.75, "INFLATION_BOND", "inflation-linked bond proxy")]
    if structural_type == "BOND":
        bond_ladder: list[tuple[RelationGrade, float, str, str]] = []
        if str(profile.geography or "") == "emerging":
            # Verificato empiricamente (2026-09-03, FAM-EMD): EMB traccia un
            # fondo di debito EM molto meglio dei proxy generici americani
            # sotto — riga aggiuntiva, non sostituisce le altre: competono
            # sul punteggio combinato finale come ovunque nel ladder.
            bond_ladder.append((RelationGrade.COUSIN, 0.75, "EM_BOND", "emerging-market debt proxy"))
        bond_ladder += [
            (RelationGrade.COUSIN, 0.72, "CORP_BOND", "corporate bond proxy"),
            (RelationGrade.AUNT, 0.65, "AGG_BOND", "aggregate bond fallback proxy"),
        ]
        return bond_ladder

    if not _is_equity(structural_type):
        return []

    ladder: list[tuple[RelationGrade, float, str, str]] = []

    sector = str(profile.sector or "")
    sector_family = _SECTOR_FAMILY.get(sector)
    if sector_family:
        ladder.append((RelationGrade.COUSIN, 0.84, sector_family, f"same sector family: {sector}"))

    if profile.theme:
        ladder.append((RelationGrade.COUSIN, 0.78, "TECH_GROWTH", "thematic/growth market reference"))
    if profile.size in ("small", "ex_mega"):
        ladder.append((RelationGrade.COUSIN, 0.78, "SMALL_CAP", "size-related market reference"))

    if profile.factor:
        factor_family = _FACTOR_PARENT_FAMILY.get(str(profile.geography or ""), "GLOBAL_EQUITY")
        ladder.append((RelationGrade.AUNT, 0.72, factor_family, f"broad parent for factor {profile.factor}"))

    geography = str(profile.geography or "")
    country_family = _COUNTRY_SPECIFIC_FAMILY.get(geography)
    if country_family:
        ladder.append((RelationGrade.COUSIN, 0.80, country_family, f"same-country index reference: {geography}"))

    geo_row = _GEO_BROAD_FAMILY.get(geography)
    if geo_row:
        geo_family, geo_score = geo_row
        ladder.append((RelationGrade.AUNT, geo_score, geo_family, "same geography broad equity"))

    ladder.append((RelationGrade.GRANDMOTHER, 0.50, "GLOBAL_EQUITY", "broad market comparison"))

    seen: set[str] = set()
    deduped: list[tuple[RelationGrade, float, str, str]] = []
    for row in ladder:
        family = row[2]
        if family in seen:
            continue
        seen.add(family)
        deduped.append(row)
    return deduped
