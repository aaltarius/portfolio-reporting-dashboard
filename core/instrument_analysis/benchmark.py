"""Benchmark dell'analisi strumento: stesso algoritmo della scoperta dal web (ADR-0021), nessuna scala propria.

Dai segnali raccolti online (nome, indice dichiarato, geografia, settore, durata, composizione) si costruisce
un profilo e lo si passa a `core.benchmark_discovery`. Il risultato e' tradotto nel contratto
`BenchmarkResolution`; se non si trova nulla il risultato lo dice (`INFRASTRUCTURE_EMERGENCY`), senza inventare.
"""
from __future__ import annotations

from typing import Callable

from core.instrument_analysis.contracts import (
    BenchmarkComponent, BenchmarkResolution, CDSAssignment, InstrumentProfile, OperationalKind,
)
from core.instrument_analysis.profile import RawIdentitySignals


def _declared_index(signals: RawIdentitySignals) -> tuple[str, str]:
    if signals.borsa_italiana and signals.borsa_italiana.benchmark_name:
        return signals.borsa_italiana.benchmark_name, "borsa_italiana"
    if signals.issuer and signals.issuer.benchmark_text:
        return signals.issuer.benchmark_text, "issuer_factsheet"
    return "", ""


def _pseudo_enrichment(profile: InstrumentProfile, signals: RawIdentitySignals, index_text: str) -> dict:
    """Le stesse voci dell'arricchimento che usa la scoperta, ricavate dai segnali online."""
    mix = profile.asset_mix or {}
    descriptive = ", ".join(x for x in (profile.geography, profile.sector, profile.theme, profile.factor,
                                         profile.size, profile.commodity_type) if x)
    return {
        "ticker": signals.yahoo.ticker if signals.yahoo else "",
        "nome": signals.yahoo.name if signals.yahoo else "",
        "tipo": profile.structural_type, "natura": signals.raw_type_text,
        "focus_etf": descriptive, "indice_sottostante": index_text,
        "duration_modificata": profile.duration_years, "scadenza": profile.maturity_date,
        "valuta": profile.currency, "rischio_cambio": "Coperto" if profile.hedged else "",
        "emittente_btp": profile.issuer_type if profile.issuer_type == "government" else "",
        "composizione_az": mix.get("equity") if len(mix) > 1 else None,
        "composizione_obbl": mix.get("bond") if len(mix) > 1 else None,
    }


def resolve_benchmark(
    profile: InstrumentProfile,
    signals: RawIdentitySignals,
    *,
    cds: CDSAssignment | None = None,
    instrument_series_fn: Callable[[], dict[str, float]] | None = None,
    source=None,
    country: str = "",
) -> BenchmarkResolution:
    from core.benchmark_discovery.decide import resolve
    from core.benchmark_discovery.profile import build_profile

    index_text, index_source = _declared_index(signals)
    dprofile = build_profile(_pseudo_enrichment(profile, signals, index_text))
    own = (instrument_series_fn() if instrument_series_fn else {}) or {}
    if source is None:
        from core.benchmark_discovery.yahoo_source import YahooSource
        source = YahooSource()
    decision = resolve(dprofile, own, source)
    out = BenchmarkResolution(official_name=index_text, official_source=index_source)
    choice = decision.choice
    if decision.status != "SCELTO" or choice is None:
        out.operational_series = "INFRASTRUCTURE_EMERGENCY"
        out.operational_kind = OperationalKind.INFRASTRUCTURE_EMERGENCY
        out.resolution_level = "INFRASTRUCTURE_EMERGENCY"
        out.note = "Nessun candidato trovato sul web: ripetere la ricerca quando la rete e' disponibile."
        return out
    fit = decision.fit
    out.relation_grade = decision.grade
    out.resolution_level = "DISCOVERY"
    out.benchmark_confidence = max(0.0, min(1.0, float(decision.score)))
    out.selection_score = float(decision.score)
    if fit is not None:
        out.correlation, out.coverage_obs = fit.corr, fit.n
        out.tracking_error_ann_pct = fit.te_pct
    if choice.symbol == "BLEND":
        legs = decision.trace.get("legs", [])
        out.operational_series, out.operational_label = "COMPOSITE", choice.name
        out.operational_kind, out.series_is_fetchable = OperationalKind.COMPOSITE, False
        out.components = [BenchmarkComponent(series_id=l["symbol"], label=l.get("name") or l["symbol"],
                                             weight_pct=float(l["weight_pct"]), provider="yahoo",
                                             kind=OperationalKind.YAHOO_INDEX) for l in legs]
        if legs:
            top = max(legs, key=lambda l: l["weight_pct"])
            out.fallback_fetchable_series, out.fallback_fetchable_label = top["symbol"], top.get("name") or top["symbol"]
    else:
        out.operational_series, out.operational_label = choice.symbol, choice.name
        out.operational_provider, out.operational_kind = "yahoo", OperationalKind.YAHOO_INDEX
        out.series_is_fetchable = True
    out.note = f"{decision.grade}: scelto dalla ricerca sul web (livello {decision.level})."
    return out
