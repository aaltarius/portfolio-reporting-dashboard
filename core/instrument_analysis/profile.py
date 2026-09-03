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
from core.instrument_analysis.text_classification import classify as classify_text


@dataclass(slots=True)
class RawIdentitySignals:
    raw_type_text: str = ""
    yahoo: YahooIdentity | None = None
    openfigi: OpenFigiIdentity | None = None
    borsa_italiana: BorsaItalianaEtfInfo | None = None
    issuer: IssuerFactsheet | None = None
    #: Composizione reale equity/bond/cash/altro (0-100) da
    #: `reference_data.yahoo.fetch_fund_asset_mix` — presente solo per fondi
    #: comuni con dato disponibile, mai un'euristica testuale (handoff
    #: sezione H "MULTI-ASSET / FONDI FLESSIBILI", Task R).
    fund_asset_mix: dict[str, float] | None = None


#: Sopra questa soglia (0-100) su una singola componente, il fondo e'
#: considerato a asset class pura: niente composito, il resolver normale
#: basta. Sotto, e' davvero misto e serve la gamba equity+bond.
_MULTI_ASSET_PURITY_THRESHOLD = 90.0


def _combined_text(signals: RawIdentitySignals) -> str:
    """Testo aggregato per `text_classification.classify` — stesso principio
    del `text=" | ".join(...)` di POC17.2 `profile()`: nome + benchmark +
    tipo grezzo, tutte le fonti disponibili senza preferirne una sola.
    Deliberatamente include SIA `borsa_italiana.benchmark_name` SIA
    `issuer.benchmark_text` (non solo la prima disponibile): il primo e'
    troncato in scraping reale (visto su XDWT.MI: "MSCI D WORLD INFORMA",
    tagliato a meta' parola), il secondo no — scegliere una sola fonte
    "preferita" avrebbe perso il segnale di settore quando quella fonte e'
    tronca ma un'altra fonte disponibile non lo e'."""
    parts = (
        signals.borsa_italiana.name if signals.borsa_italiana else "",
        signals.yahoo.name if signals.yahoo else "",
        signals.openfigi.name if signals.openfigi else "",
        signals.borsa_italiana.benchmark_name if signals.borsa_italiana else "",
        signals.issuer.benchmark_text if signals.issuer else "",
        signals.raw_type_text,
    )
    return " | ".join(p for p in parts if p)


def build_profile(signals: RawIdentitySignals) -> InstrumentProfile:
    profile = InstrumentProfile()
    profile.asset_class = infer_category_code(signals.raw_type_text, default="ALTRO")

    text_result = classify_text(_combined_text(signals))
    profile.structural_type = text_result.structural_type
    profile.geography = text_result.geography
    profile.geo_scope = text_result.geo_scope
    profile.sector = text_result.sector
    profile.theme = text_result.theme
    profile.factor = text_result.factor
    profile.size = text_result.size
    if text_result.issuer_type:
        profile.issuer_type = text_result.issuer_type
    if text_result.hedged is not None:
        profile.hedged = text_result.hedged

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

    if signals.fund_asset_mix:
        dominant_key, dominant_value = max(
            signals.fund_asset_mix.items(), key=lambda kv: kv[1], default=("", 0.0)
        )
        if dominant_value < _MULTI_ASSET_PURITY_THRESHOLD:
            # Miscela reale, non riconducibile a una singola asset class: NON
            # tocca profile.asset_class (tassonomia FND/ETF/ecc. di
            # core/asset_categories.py, un vocabolario diverso) — asset_mix e'
            # il segnale dedicato che benchmark.py usa per il ramo composito
            # multi-asset (Task R).
            profile.asset_mix = dict(signals.fund_asset_mix)
        elif profile.asset_class == "ALTRO" and dominant_key in ("equity", "bond"):
            # Fondo puro per composizione reale (es. FAM-EMD, 96% bond): non
            # serve un composito a 2 gambe, ma se la classificazione
            # testuale non ha riconosciuto la asset class, il dato reale
            # basta a evitare l'emergenza infrastrutturale — almeno il
            # fallback "mercato generale" per OBB/AZI si applica.
            profile.asset_class = "AZI" if dominant_key == "equity" else "OBB"

    profile.provenance = provenance
    profile.completeness = min(1.0, signal_count / 4.0)
    profile.confidence = min(1.0, 0.3 + 0.15 * signal_count)
    return profile
