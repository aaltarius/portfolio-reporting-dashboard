"""Orchestratore del motore InstrumentAnalysis. Unico punto che chiama gli
adapter di rete (reference_data/) e assembla il risultato finale — la
Fase D (background) e' responsabile di garantire che questo metodo giri
solo fuori dal render di una pagina."""
from __future__ import annotations

import time
from datetime import datetime, timezone

from core.instrument_analysis import cache as ia_cache
from core.instrument_analysis.benchmark import resolve_benchmark
from core.instrument_analysis.cds import compute_cds
from core.instrument_analysis.contracts import (
    BenchmarkComponent, BenchmarkResolution, CDSAssignment, InstrumentAnalysis, InstrumentProfile,
    OperationalKind, RelationGrade,
)
from core.instrument_analysis.profile import RawIdentitySignals, build_profile
from core.instrument_analysis.reference_data.borsa_italiana import fetch_etf_info
from core.instrument_analysis.reference_data.family_series import fetch_family_candidates
from core.instrument_analysis.reference_data.issuer import fetch_factsheet
from core.instrument_analysis.reference_data.openfigi import OpenFigiIdentity, map_isin
from core.instrument_analysis.reference_data.rates import fetch_italy_sovereign_yield, fetch_sovereign_curve
from core.instrument_analysis.reference_data.yahoo import YahooIdentity, fetch_fund_asset_mix, resolve_yahoo_identity
from core.instrument_analysis.sovereign_curve import synthetic_total_return
from core.market_data import get_yahoo_price_history_full

_RESOLUTION_TTL_DAYS = 14.0

#: Grade di benchmark che NON contengono segnale utile: se la risoluzione si
#: ferma qui e il profilo e' rimasto "ALTRO", non c'e' nulla da mettere in
#: cache (vedi `_is_result_worth_caching`).
_DEGRADED_GRADES = frozenset({
    RelationGrade.TECHNICAL_EMERGENCY.value,
    OperationalKind.INFRASTRUCTURE_EMERGENCY.value,
})


def _raw_type_text(
    openfigi_identity: OpenFigiIdentity | None, yahoo_identity: YahooIdentity | None,
) -> str:
    """Testo grezzo di tipologia per `infer_category_code()` (profile.py).

    Gli adapter non espongono una categoria di progetto (ETF/AZI/OBB/...):
    espongono etichette del loro dominio (OpenFIGI `securityType2` = "ETP"/
    "ETF"/"Common Stock", Yahoo `quoteType` = "ETF"/"EQUITY"/"MUTUALFUND").
    Qui vengono concatenate in ordine di affidabilita' (OpenFIGI, che mappa
    l'ISIN, prima di Yahoo, che parte da un ticker euristico) e passate al
    classificatore centralizzato: nessuna tabella di categorie duplicata.

    `market_sector` (Equity/Govt/Corp/Comdty) e' un ripiego di ultima
    istanza: e' la macro-area dell'emittente, non la forma dello strumento,
    quindi su un ETF azionario direbbe "Equity" (-> AZI) invece di ETF.
    Viene usato solo quando nessuna delle due etichette di forma esiste.
    """
    parts = [
        (openfigi_identity.security_type2 if openfigi_identity else "") or "",
        (yahoo_identity.quote_type if yahoo_identity else "") or "",
    ]
    text = " ".join(p.strip() for p in parts if p.strip()).strip()
    if text:
        return text
    return str((openfigi_identity.market_sector if openfigi_identity else "") or "").strip()


#: Pausa breve prima del retry (Task N3) — intermittenza di rete Yahoo
#: confermata empiricamente (stesso ticker risolto, stesso codice: un
#: tentativo fallisce, uno riesce, vedi piano). Un solo retry, mai un
#: loop, per rispettare il budget "≤8s/strumento" (regola non
#: negoziabile 0).
_HISTORY_RETRY_DELAY_SECONDS = 1.0


def _fetch_own_history_with_retry(ticker: str) -> dict[str, float]:
    history = get_yahoo_price_history_full(ticker, period="1y")
    if history:
        return history
    time.sleep(_HISTORY_RETRY_DELAY_SECONDS)
    return get_yahoo_price_history_full(ticker, period="1y")


#: Tenor piu' corto pubblicato dalla curva SDW YC euro-area (verificato in
#: diretta il 2026-09-03: "3M" risponde 200, "1M" risponde 404). Un BTP a
#: pochi giorni dalla scadenza (duration reale vicina a 0) usa questo
#: punto come proxy della curva — il rendimento totale usa comunque la
#: duration REALE dello strumento, non questo floor.
_ECB_CURVE_MIN_MATURITY_YEARS = 0.25


def _fetch_sovereign_synthetic_curve(duration_years: float) -> tuple[dict[str, float], bool]:
    """Curva sovrana sintetica duration-matched (Task R, handoff sezione I)
    — curva euro-area (ECB, verificata in diretta) piu' spread Italia
    best-effort (Banca d'Italia). Ritorna (serie, spread_trovato):
    spread_trovato=False quando la fonte Banca d'Italia non e' disponibile
    (verificato il 2026-09-03: pagina probabilmente ristrutturata dal sito
    dal 2026 in poi) — degrada onestamente alla sola curva euro-area, mai
    un errore ne' un valore inventato."""
    curve_maturity = max(_ECB_CURVE_MIN_MATURITY_YEARS, duration_years)
    euro_curve = fetch_sovereign_curve("EUR", curve_maturity)
    if euro_curve is None or len(euro_curve.observations) < 2:
        return {}, False
    observations = dict(euro_curve.observations)
    italy_yield = fetch_italy_sovereign_yield(curve_maturity)
    spread_found = False
    if italy_yield is not None:
        latest_date = max(observations)
        spread = italy_yield - observations[latest_date]
        observations = {d: v + spread for d, v in observations.items()}
        spread_found = True
    return synthetic_total_return(observations, duration_years), spread_found


def _is_result_worth_caching(profile: InstrumentProfile, benchmark: BenchmarkResolution) -> bool:
    """True solo se almeno una delle due risoluzioni ha prodotto segnale.

    Un risultato in cui il profilo e' rimasto "ALTRO" *e* il benchmark e'
    finito in emergenza infrastrutturale e' indistinguibile da un blackout
    di rete: metterlo in cache lo congelerebbe per l'intero TTL (14 giorni)
    senza che nulla possa riprovare. In quel caso non si scrive nulla e la
    chiamata successiva ritenta da capo.
    """
    if str(profile.asset_class or "").upper() not in ("", "ALTRO"):
        return True
    grade = getattr(benchmark.relation_grade, "value", benchmark.relation_grade)
    return bool(grade) and grade not in _DEGRADED_GRADES


# ---------------------------------------------------------------------------
# Serializzazione domain-specific per la cache di risoluzione.
#
# `cache.py` (A2) tratta il payload come un dict JSON generico: non sa nulla
# di InstrumentProfile/CDSAssignment/BenchmarkResolution. La conversione
# da/verso quei dataclass (incluse le enum OperationalKind/RelationGrade,
# che non sono JSON-serializzabili cosi' come sono) appartiene qui, dove le
# forme sono note. `provenance` (lista di ProvenanceItem) resta
# volutamente esclusa: e' audit trail, non serve a soddisfare
# InstrumentAnalysis.validate() ne' ai consumer che leggono percentuali C/D/S
# e identita' del benchmark. `components` (lista di BenchmarkComponent)
# invece E' serializzata (Task Q, 2026-09-03): il ramo composito pesato per
# C/D/S la popola davvero — senza round-trip in cache un cache-hit
# mostrerebbe `operational_series="COMPOSITE"` senza sapere di cosa e'
# fatto.
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
        "series_is_fetchable": benchmark.series_is_fetchable,
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
        "components": [
            {"series_id": c.series_id, "label": c.label, "weight_pct": c.weight_pct,
             "provider": c.provider, "kind": _enum_value(c.kind)}
            for c in benchmark.components
        ],
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
        series_is_fetchable=bool(data.get("series_is_fetchable", False)),
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
        components=[
            BenchmarkComponent(
                series_id=c.get("series_id", ""), label=c.get("label", ""),
                weight_pct=c.get("weight_pct", 0.0), provider=c.get("provider", ""),
                kind=_operational_kind_from_cache(c.get("kind", "")),
            )
            for c in (data.get("components") or [])
        ],
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
    def analyze(
        self, *, ticker: str = "", isin: str = "", force_refresh: bool = False,
        duration_years: float | None = None,
        own_history: dict[str, float] | None = None,
    ) -> InstrumentAnalysis:
        tk = str(ticker or "").strip().upper()
        isincode = str(isin or "").strip().upper()

        # Cronometro attivo anche sul ramo cache-hit: `elapsed_ms` misura
        # sempre il costo reale di analyze() per il chiamante (sul cache-hit
        # e' solo la lettura del file, tipicamente 0-1 ms; sul cache-miss e'
        # rete + elaborazione, il numero che interessa alla spec).
        started = time.perf_counter()

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
                    elapsed_ms=int(round((time.perf_counter() - started) * 1000.0)),
                    cache_hit=True,
                )
                return analysis

        yahoo_identity = resolve_yahoo_identity(tk, isincode)
        openfigi_identity = map_isin(isincode)
        borsa_italiana_info = fetch_etf_info(isincode)
        issuer_factsheet = fetch_factsheet(isincode)
        # Composizione reale solo per fondi comuni (quote_type MUTUALFUND,
        # tipicamente risolti da resolve_mutual_fund_identity per ISIN senza
        # ticker di borsa — es. i fondi Fineco AM proprietari): mai una
        # chiamata in piu' per ETF/azioni normali (Task R, 2026-09-03).
        fund_asset_mix = (
            fetch_fund_asset_mix(yahoo_identity.ticker)
            if yahoo_identity and yahoo_identity.quote_type == "MUTUALFUND"
            else None
        )

        signals = RawIdentitySignals(
            raw_type_text=_raw_type_text(openfigi_identity, yahoo_identity),
            yahoo=yahoo_identity, openfigi=openfigi_identity,
            borsa_italiana=borsa_italiana_info, issuer=issuer_factsheet,
            fund_asset_mix=fund_asset_mix,
        )
        profile = build_profile(signals)
        if duration_years is not None:
            # Fornita dal chiamante (es. `duration_modificata` gia' presente
            # sullo strumento reale, arricchimento PDF esistente) — non
            # derivabile dalle fonti online di questo motore per un BTP
            # (nessun ticker Yahoo per singole obbligazioni sovrane, Task R).
            profile.duration_years = duration_years
        cds = compute_cds(profile)
        # Ticker per lo storico: quello RISOLTO da resolve_yahoo_identity
        # (via ricerca ISIN, `find_ticker_candidates`), non il `tk` grezzo
        # passato dal chiamante — quest'ultimo puo' essere delisted/non piu'
        # quotato su Yahoo (visto su IQQ6.MI/E50.MI/XWCO.MI/KOREA.MI: 404 sul
        # ticker originale, storico reale disponibile solo su quello
        # risolto). E' lo stesso ticker gia' usato altrove nella pipeline
        # per nome/classificazione (`signals.yahoo.name`) — qui si allinea
        # anche il fetch storico, non se ne introduce uno nuovo.
        #
        # Lazy: chiamata solo se `resolve_benchmark` ne ha davvero bisogno
        # (EXACT/SISTER con family_ladder non vuoto, o ladder intermedio —
        # gap 1/geometry-per-EXACT-SISTER, Task L4/M3-bis) — mai una
        # chiamata di rete in piu' quando non serve.
        history_ticker = yahoo_identity.ticker if yahoo_identity else tk
        # Paese dal prefisso ISIN (standard ISO 6166, sempre le prime 2
        # lettere) — nessuna euristica testuale necessaria, l'ISIN lo dice
        # gia' in modo inequivocabile (2026-09-03, per il confronto diretto
        # con un ETF governativo nazionale reale, vedi benchmark.py).
        country = isincode[:2] if len(isincode) >= 2 else ""
        # own_history: storico prezzi gia' posseduto dal chiamante (es. lo
        # storico reale salvato in portafoglio per un BTP, che non ha un
        # ticker Yahoo interrogabile da questo motore — vedi
        # `find_ticker_candidates`) — se fornito, sostituisce il fetch
        # Yahoo, mai sommato ad esso. Verificato in diretta il 2026-09-03:
        # abilita un vero controllo di geometria contro l'ETF governativo
        # nazionale (52,7-65,6, sopra soglia) invece di restare a un
        # punteggio di sola confidence.
        instrument_series_fn = (
            (lambda: own_history) if own_history else (lambda: _fetch_own_history_with_retry(history_ticker))
        )
        benchmark = resolve_benchmark(
            profile, signals,
            cds=cds,
            instrument_series_fn=instrument_series_fn,
            family_series_fn=fetch_family_candidates,
            sovereign_curve_fn=_fetch_sovereign_synthetic_curve,
            country=country,
        )

        analysis = InstrumentAnalysis(
            ticker=tk, isin=isincode,
            name=(yahoo_identity.name if yahoo_identity else ""),
            profile=profile, cds=cds, benchmark=benchmark,
            algorithm_version=ia_cache.ALGORITHM_VERSION,
            resolved_at=datetime.now(timezone.utc).isoformat(),
            elapsed_ms=int(round((time.perf_counter() - started) * 1000.0)),
            cache_hit=False,
        )

        # Un risultato completamente degradato non viene scritto: vedi
        # `_is_result_worth_caching`.
        if _is_result_worth_caching(profile, benchmark):
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
            if not series or series in seen:
                continue
            benchmark_data = entry.get("benchmark") or {}
            label = str(benchmark_data.get("operational_label") or "").strip() or series
            seen[series] = label
        return sorted(seen.items())
