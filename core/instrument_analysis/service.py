"""Orchestratore del motore InstrumentAnalysis. Unico punto che chiama gli
adapter di rete (reference_data/) e assembla il risultato finale — la
Fase D (background) e' responsabile di garantire che questo metodo giri
solo fuori dal render di una pagina."""
from __future__ import annotations

from datetime import datetime, timezone

from core.instrument_analysis import cache as ia_cache
from core.instrument_analysis.benchmark import resolve_benchmark
from core.instrument_analysis.cds import compute_cds
from core.instrument_analysis.contracts import InstrumentAnalysis
from core.instrument_analysis.profile import RawIdentitySignals, build_profile
from core.instrument_analysis.reference_data.borsa_italiana import fetch_etf_info
from core.instrument_analysis.reference_data.issuer import fetch_factsheet
from core.instrument_analysis.reference_data.openfigi import map_isin
from core.instrument_analysis.reference_data.yahoo import resolve_yahoo_identity

_RESOLUTION_TTL_DAYS = 14.0


class InstrumentAnalysisService:
    def analyze(self, *, ticker: str = "", isin: str = "", force_refresh: bool = False) -> InstrumentAnalysis:
        tk = str(ticker or "").strip().upper()
        isincode = str(isin or "").strip().upper()

        cache = ia_cache.load_resolution_cache()
        cache_key = ia_cache.resolution_cache_key(tk, isincode)

        if not force_refresh:
            cached = ia_cache.get_cached_resolution(cache, cache_key, ttl_days=_RESOLUTION_TTL_DAYS)
            if cached is not None:
                analysis = InstrumentAnalysis(ticker=tk, isin=isincode)
                analysis.algorithm_version = ia_cache.ALGORITHM_VERSION
                analysis.cache_hit = True
                analysis.benchmark.operational_series = cached.get("operational_series", "CACHED")
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

        ia_cache.put_cached_resolution(cache, cache_key, {
            "operational_series": benchmark.operational_series,
        })
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
