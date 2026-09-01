"""Ladder di parentela per il benchmark: identita' ufficiale separata dalla
curva operativa (spec sezione 6). Domain lock applicato PRIMA di qualunque
punteggio di geometry/correlazione — vincolo non negoziabile."""
from __future__ import annotations

from core.instrument_analysis.contracts import (
    BenchmarkResolution, InstrumentProfile, OperationalKind, ProvenanceItem, RelationGrade,
)
from core.instrument_analysis.profile import RawIdentitySignals

DOMAIN_LOCK_FORBIDDEN: dict[str, frozenset[str]] = {
    "AZI": frozenset({"OBB", "GOV", "LIQ"}),
    "ETF": frozenset({"OBB", "GOV", "LIQ"}),
    "OBB": frozenset({"AZI", "ETF", "ETC"}),
    "GOV": frozenset({"AZI", "ETF", "ETC"}),
    "ETC": frozenset({"OBB", "GOV"}),
}

# Curva "mercato generale" per asset_class quando nessuna fonte online ha
# prodotto un match utilizzabile: ultimo gradino del ladder prima
# dell'emergenza infrastrutturale, sempre una curva reale (mai BASE100
# normale).
_GENERAL_MARKET_SERIES: dict[str, str] = {
    "AZI": "^990100-USD-STRD",  # MSCI World
    "ETF": "^990100-USD-STRD",
    "OBB": "LEGATRUU-Index",    # Bloomberg Global Aggregate (placeholder di libreria, non hardcoded per strumento)
    "GOV": "LEGATRUU-Index",
    "ETC": "BCOMTR-Index",      # Bloomberg Commodity
}


def domain_locked(source_asset_class: str, candidate_asset_class: str) -> bool:
    forbidden = DOMAIN_LOCK_FORBIDDEN.get(str(source_asset_class or "").upper(), frozenset())
    return str(candidate_asset_class or "").upper() in forbidden


def resolve_benchmark(profile: InstrumentProfile, signals: RawIdentitySignals) -> BenchmarkResolution:
    # Nota: nessun ramo qui valorizza `series_is_fetchable`, che resta al
    # default False. E' voluto — vedi il commento del campo in contracts.py:
    # oggi `operational_series` e' sempre un'etichetta o un placeholder, mai
    # un identificativo che una fonte dati sappia interrogare.
    resolution = BenchmarkResolution()

    if signals.borsa_italiana and signals.borsa_italiana.benchmark_name:
        resolution.official_name = signals.borsa_italiana.benchmark_name
        resolution.official_source = "borsa_italiana"
        resolution.operational_series = signals.borsa_italiana.benchmark_name
        resolution.operational_label = signals.borsa_italiana.benchmark_name
        resolution.operational_kind = OperationalKind.PROVIDER_INDEX
        resolution.resolution_level = "EXACT_FROM_OFFICIAL_SOURCE"
        resolution.relation_grade = RelationGrade.EXACT
        resolution.benchmark_confidence = signals.borsa_italiana.provenance.confidence
        resolution.provenance.append(signals.borsa_italiana.provenance)
        return resolution

    if signals.issuer and signals.issuer.benchmark_text:
        resolution.official_name = signals.issuer.benchmark_text
        resolution.official_source = "issuer_factsheet"
        resolution.operational_series = signals.issuer.benchmark_text
        resolution.operational_label = signals.issuer.benchmark_text
        resolution.operational_kind = OperationalKind.PROVIDER_INDEX
        resolution.resolution_level = "SISTER_FROM_FACTSHEET_TEXT"
        resolution.relation_grade = RelationGrade.SISTER
        if signals.issuer.provenance:
            resolution.benchmark_confidence = signals.issuer.provenance.confidence
            resolution.provenance.append(signals.issuer.provenance)
        else:
            resolution.benchmark_confidence = 0.5
        return resolution

    # Nessuna fonte diretta: scende al mercato generale per la stessa
    # asset class (mai cross-asset — domain lock rispettato per
    # costruzione, non serve verificarlo qui perche' la tabella e' chiavata
    # per asset_class della fonte).
    general_series = _GENERAL_MARKET_SERIES.get(str(profile.asset_class or "").upper())
    if general_series:
        resolution.operational_series = general_series
        resolution.operational_label = f"Mercato generale ({profile.asset_class})"
        resolution.operational_kind = OperationalKind.YAHOO_INDEX
        resolution.resolution_level = "GENERAL_MARKET_FALLBACK"
        resolution.relation_grade = RelationGrade.GENERAL_MARKET
        resolution.benchmark_confidence = 0.3
        resolution.note = "Nessuna fonte diretta disponibile: fallback a mercato generale per asset class."
        return resolution

    # Emergenza infrastrutturale esplicita — mai un normale BASE100.
    resolution.operational_series = "INFRASTRUCTURE_EMERGENCY"
    resolution.operational_kind = OperationalKind.INFRASTRUCTURE_EMERGENCY
    resolution.resolution_level = "INFRASTRUCTURE_EMERGENCY"
    resolution.relation_grade = RelationGrade.TECHNICAL_EMERGENCY
    resolution.benchmark_confidence = 0.0
    resolution.note = "Nessuna asset class riconosciuta: fonti esaurite."
    return resolution
