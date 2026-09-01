"""Normalizzazione dei segnali grezzi (adapter reference_data/) in un
InstrumentProfile. Nessuna chiamata di rete qui: gli adapter sono gia'
stati invocati a monte (service.py), questo modulo e' puro."""
from __future__ import annotations

from dataclasses import dataclass

from core.asset_categories import infer_category_code
from core.instrument_analysis.contracts import InstrumentProfile, ProvenanceItem
from core.instrument_analysis.reference_data.borsa_italiana import BorsaItalianaEtfInfo
from core.instrument_analysis.reference_data.issuer import IssuerFactsheet
from core.instrument_analysis.reference_data.openfigi import OpenFigiIdentity
from core.instrument_analysis.reference_data.yahoo import YahooIdentity

_GEO_TOKENS: dict[str, tuple[str, str]] = {
    "world": ("world", "global"), "global": ("world", "global"), "all-world": ("world", "global"),
    "emerging": ("emerging", "regional"), "europe": ("europe", "regional"),
    "usa": ("usa", "single_country"), "italia": ("italia", "single_country"),
}


@dataclass(slots=True)
class RawIdentitySignals:
    raw_type_text: str = ""
    yahoo: YahooIdentity | None = None
    openfigi: OpenFigiIdentity | None = None
    borsa_italiana: BorsaItalianaEtfInfo | None = None
    issuer: IssuerFactsheet | None = None


def _benchmark_text(signals: RawIdentitySignals) -> str:
    if signals.borsa_italiana and signals.borsa_italiana.benchmark_name:
        return signals.borsa_italiana.benchmark_name
    if signals.issuer and signals.issuer.benchmark_text:
        return signals.issuer.benchmark_text
    return ""


def _infer_geography(benchmark_text: str) -> tuple[str, str]:
    text = benchmark_text.lower()
    for token, (geography, geo_scope) in _GEO_TOKENS.items():
        if token in text:
            return geography, geo_scope
    return "", ""


def build_profile(signals: RawIdentitySignals) -> InstrumentProfile:
    profile = InstrumentProfile()
    profile.asset_class = infer_category_code(signals.raw_type_text, default="ALTRO")

    benchmark_text = _benchmark_text(signals)
    if benchmark_text:
        geography, geo_scope = _infer_geography(benchmark_text)
        profile.geography = geography
        profile.geo_scope = geo_scope

    provenance: list[ProvenanceItem] = []
    signal_count = 0
    for signal, source in (
        (signals.yahoo, signals.yahoo.provenance if signals.yahoo else None),
        (signals.openfigi, signals.openfigi.provenance if signals.openfigi else None),
        (signals.borsa_italiana, signals.borsa_italiana.provenance if signals.borsa_italiana else None),
        (signals.issuer, signals.issuer.provenance if signals.issuer else None),
    ):
        if signal is not None:
            signal_count += 1
            if source is not None:
                provenance.append(source)

    profile.provenance = provenance
    profile.completeness = min(1.0, signal_count / 4.0)
    profile.confidence = min(1.0, 0.3 + 0.15 * signal_count)
    return profile
