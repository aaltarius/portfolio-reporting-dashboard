"""Orchestratore del motore InstrumentAnalysis. Unico punto che chiama gli
adapter di rete (reference_data/) e assembla il risultato finale — la
Fase D (background) e' responsabile di garantire che questo metodo giri
solo fuori dal render di una pagina."""
from __future__ import annotations

from datetime import datetime, timezone

from core.instrument_analysis import cache as ia_cache
from core.instrument_analysis.benchmark import resolve_benchmark
from core.instrument_analysis.cds import compute_cds
from core.instrument_analysis.contracts import (
    BenchmarkResolution, CDSAssignment, InstrumentAnalysis, InstrumentProfile,
    OperationalKind, RelationGrade,
)
from core.instrument_analysis.profile import RawIdentitySignals, build_profile
from core.instrument_analysis.reference_data.borsa_italiana import fetch_etf_info
from core.instrument_analysis.reference_data.issuer import fetch_factsheet
from core.instrument_analysis.reference_data.openfigi import map_isin
from core.instrument_analysis.reference_data.yahoo import resolve_yahoo_identity

_RESOLUTION_TTL_DAYS = 14.0


# ---------------------------------------------------------------------------
# Serializzazione domain-specific per la cache di risoluzione.
#
# `cache.py` (A2) tratta il payload come un dict JSON generico: non sa nulla
# di InstrumentProfile/CDSAssignment/BenchmarkResolution. La conversione
# da/verso quei dataclass (incluse le enum OperationalKind/RelationGrade,
# che non sono JSON-serializzabili cosi' come sono) appartiene qui, dove le
# forme sono note. `provenance` (liste di ProvenanceItem) e `components`
# (lista di BenchmarkComponent, mai popolata da resolve_benchmark oggi) sono
# volutamente esclusi: sono audit trail, non servono a soddisfare
# InstrumentAnalysis.validate() ne' ai consumer che leggono percentuali C/D/S
# e identita' del benchmark.
# ---------------------------------------------------------------------------

def _enum_value(value: object) -> str:
    raw = getattr(value, "value", value)
    return str(raw or "")


def _operational_kind_from_cache(value: str) -> OperationalKind | str:
    try:
        return OperationalKind(value)
    except ValueError:
        return value


def _relation_grade_from_cache(value: str) -> RelationGrade | str:
    try:
        return RelationGrade(value)
    except ValueError:
        return value


def _profile_to_cache(profile: InstrumentProfile) -> dict:
    return {
        "asset_class": profile.asset_class,
        "structural_type": profile.structural_type,
        "geography": profile.geography,
        "geo_scope": profile.geo_scope,
        "sector": profile.sector,
        "theme": profile.theme,
        "factor": profile.factor,
        "size": profile.size,
        "market_breadth": profile.market_breadth,
        "issuer_type": profile.issuer_type,
        "currency": profile.currency,
        "hedged": profile.hedged,
        "duration_years": profile.duration_years,
        "maturity_date": profile.maturity_date,
        "commodity_type": profile.commodity_type,
        "asset_mix": dict(profile.asset_mix or {}),
        "confidence": profile.confidence,
        "completeness": profile.completeness,
    }


def _profile_from_cache(data: dict) -> InstrumentProfile:
    return InstrumentProfile(
        asset_class=data.get("asset_class", ""),
        structural_type=data.get("structural_type", ""),
        geography=data.get("geography", ""),
        geo_scope=data.get("geo_scope", ""),
        sector=data.get("sector", ""),
        theme=data.get("theme", ""),
        factor=data.get("factor", ""),
        size=data.get("size", ""),
        market_breadth=data.get("market_breadth", 0.0),
        issuer_type=data.get("issuer_type", ""),
        currency=data.get("currency", ""),
        hedged=bool(data.get("hedged", False)),
        duration_years=data.get("duration_years"),
        maturity_date=data.get("maturity_date", ""),
        commodity_type=data.get("commodity_type", ""),
        asset_mix=dict(data.get("asset_mix") or {}),
        confidence=data.get("confidence", 0.0),
        completeness=data.get("completeness", 0.0),
    )


def _cds_to_cache(cds: CDSAssignment) -> dict:
    return {
        "raw_core_pct": cds.raw_core_pct,
        "raw_defensive_pct": cds.raw_defensive_pct,
        "raw_satellite_pct": cds.raw_satellite_pct,
        "core_pct": cds.core_pct,
        "defensive_pct": cds.defensive_pct,
        "satellite_pct": cds.satellite_pct,
        "active_roles": list(cds.active_roles),
        "confidence": cds.confidence,
        "reliability_score": cds.reliability_score,
        "validation_flags": list(cds.validation_flags),
        "reasons": list(cds.reasons),
    }


def _cds_from_cache(data: dict) -> CDSAssignment:
    return CDSAssignment(
        raw_core_pct=data.get("raw_core_pct", 0.0),
        raw_defensive_pct=data.get("raw_defensive_pct", 0.0),
        raw_satellite_pct=data.get("raw_satellite_pct", 0.0),
        core_pct=data.get("core_pct", 0.0),
        defensive_pct=data.get("defensive_pct", 0.0),
        satellite_pct=data.get("satellite_pct", 0.0),
        active_roles=list(data.get("active_roles") or []),
        confidence=data.get("confidence", 0.0),
        reliability_score=data.get("reliability_score", 0.0),
        validation_flags=list(data.get("validation_flags") or []),
        reasons=list(data.get("reasons") or []),
    )


def _benchmark_to_cache(benchmark: BenchmarkResolution) -> dict:
    return {
        "official_name": benchmark.official_name,
        "official_code": benchmark.official_code,
        "official_provider": benchmark.official_provider,
        "official_source": benchmark.official_source,
        "operational_series": benchmark.operational_series,
        "operational_label": benchmark.operational_label,
        "operational_provider": benchmark.operational_provider,
        "operational_kind": _enum_value(benchmark.operational_kind),
        "resolution_level": benchmark.resolution_level,
        "relation_grade": _enum_value(benchmark.relation_grade),
        "benchmark_confidence": benchmark.benchmark_confidence,
        "semantic_confidence": benchmark.semantic_confidence,
        "geometry_score": benchmark.geometry_score,
        "selection_score": benchmark.selection_score,
        "coverage_obs": benchmark.coverage_obs,
        "trend_similarity_pct": benchmark.trend_similarity_pct,
        "tracking_adherence_pct": benchmark.tracking_adherence_pct,
        "correlation": benchmark.correlation,
        "beta": benchmark.beta,
        "tracking_error_ann_pct": benchmark.tracking_error_ann_pct,
        "note": benchmark.note,
    }


def _benchmark_from_cache(data: dict) -> BenchmarkResolution:
    return BenchmarkResolution(
        official_name=data.get("official_name", ""),
        official_code=data.get("official_code", ""),
        official_provider=data.get("official_provider", ""),
        official_source=data.get("official_source", ""),
        operational_series=data.get("operational_series", ""),
        operational_label=data.get("operational_label", ""),
        operational_provider=data.get("operational_provider", ""),
        operational_kind=_operational_kind_from_cache(data.get("operational_kind", "")),
        resolution_level=data.get("resolution_level", ""),
        relation_grade=_relation_grade_from_cache(data.get("relation_grade", "")),
        benchmark_confidence=data.get("benchmark_confidence", 0.0),
        semantic_confidence=data.get("semantic_confidence", 0.0),
        geometry_score=data.get("geometry_score", 0.0),
        selection_score=data.get("selection_score", 0.0),
        coverage_obs=data.get("coverage_obs", 0),
        trend_similarity_pct=data.get("trend_similarity_pct"),
        tracking_adherence_pct=data.get("tracking_adherence_pct"),
        correlation=data.get("correlation"),
        beta=data.get("beta"),
        tracking_error_ann_pct=data.get("tracking_error_ann_pct"),
        note=data.get("note", ""),
    )


def _analysis_to_cache_payload(
    name: str, profile: InstrumentProfile, cds: CDSAssignment, benchmark: BenchmarkResolution,
) -> dict:
    return {
        # Chiave storica, letta da discovered_benchmark_catalog(): resta al
        # livello superiore per compatibilita', duplicata dentro "benchmark".
        "operational_series": benchmark.operational_series,
        "name": name,
        "profile": _profile_to_cache(profile),
        "cds": _cds_to_cache(cds),
        "benchmark": _benchmark_to_cache(benchmark),
    }


class InstrumentAnalysisService:
    def analyze(self, *, ticker: str = "", isin: str = "", force_refresh: bool = False) -> InstrumentAnalysis:
        tk = str(ticker or "").strip().upper()
        isincode = str(isin or "").strip().upper()

        cache = ia_cache.load_resolution_cache()
        cache_key = ia_cache.resolution_cache_key(tk, isincode)

        if not force_refresh:
            cached = ia_cache.get_cached_resolution(cache, cache_key, ttl_days=_RESOLUTION_TTL_DAYS)
            if cached is not None:
                analysis = InstrumentAnalysis(
                    ticker=tk, isin=isincode,
                    name=str(cached.get("name") or ""),
                    profile=_profile_from_cache(cached.get("profile") or {}),
                    cds=_cds_from_cache(cached.get("cds") or {}),
                    benchmark=_benchmark_from_cache(cached.get("benchmark") or {}),
                    algorithm_version=ia_cache.ALGORITHM_VERSION,
                    cache_hit=True,
                )
                return analysis

        yahoo_identity = resolve_yahoo_identity(tk, isincode)
        openfigi_identity = map_isin(isincode)
        borsa_italiana_info = fetch_etf_info(isincode)
        issuer_factsheet = fetch_factsheet(isincode)

        signals = RawIdentitySignals(
            yahoo=yahoo_identity, openfigi=openfigi_identity,
            borsa_italiana=borsa_italiana_info, issuer=issuer_factsheet,
        )
        profile = build_profile(signals)
        cds = compute_cds(profile)
        benchmark = resolve_benchmark(profile, signals)

        analysis = InstrumentAnalysis(
            ticker=tk, isin=isincode,
            name=(yahoo_identity.name if yahoo_identity else ""),
            profile=profile, cds=cds, benchmark=benchmark,
            algorithm_version=ia_cache.ALGORITHM_VERSION,
            resolved_at=datetime.now(timezone.utc).isoformat(),
            cache_hit=False,
        )

        ia_cache.put_cached_resolution(
            cache, cache_key,
            _analysis_to_cache_payload(analysis.name, profile, cds, benchmark),
        )
        ia_cache.save_resolution_cache(cache)

        return analysis

    def discovered_benchmark_catalog(self) -> list[tuple[str, str]]:
        cache = ia_cache.load_resolution_cache()
        seen: dict[str, str] = {}
        for entry in cache.values():
            series = str(entry.get("operational_series") or "").strip()
            if series and series not in seen:
                seen[series] = series
        return sorted(seen.items())
