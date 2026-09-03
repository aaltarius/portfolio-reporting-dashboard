from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class OperationalKind(str, Enum):
    YAHOO_INDEX = "YAHOO_INDEX"
    PROVIDER_INDEX = "PROVIDER_INDEX"
    SYNTHETIC_BOND = "SYNTHETIC_BOND"
    SOVEREIGN_CURVE = "SOVEREIGN_CURVE"
    RATE = "RATE"
    COMPOSITE = "COMPOSITE"
    HOLDINGS_SYNTHETIC = "HOLDINGS_SYNTHETIC"
    DIRECT_UNDERLYING = "DIRECT_UNDERLYING"
    INFRASTRUCTURE_EMERGENCY = "INFRASTRUCTURE_EMERGENCY"


class RelationGrade(str, Enum):
    EXACT = "PROPRIA"
    SISTER = "SORELLA"
    COUSIN = "CUGINA"
    AUNT = "ZIA"
    GRANDMOTHER = "NONNA"
    BROAD_FAMILY = "FAMIGLIA_AMPIA"
    GENERAL_MARKET = "MERCATO_GENERALE"
    STRUCTURAL_COMPOSITE = "PROPRIA_STRUTTURALE"
    TECHNICAL_EMERGENCY = "NONNA_TECNICA"


@dataclass(slots=True)
class ProvenanceItem:
    source: str
    field: str
    value: Any
    confidence: float = 0.0
    url: str = ""
    fetched_at: str = ""


@dataclass(slots=True)
class BenchmarkComponent:
    series_id: str
    label: str
    weight_pct: float
    provider: str = ""
    kind: OperationalKind | str = ""


@dataclass(slots=True)
class InstrumentProfile:
    asset_class: str = ""
    structural_type: str = ""
    geography: str = ""
    geo_scope: str = ""
    sector: str = ""
    theme: str = ""
    factor: str = ""
    size: str = ""
    market_breadth: float = 0.0
    issuer_type: str = ""
    currency: str = ""
    hedged: bool = False
    duration_years: float | None = None
    maturity_date: str = ""
    commodity_type: str = ""
    asset_mix: dict[str, float] = field(default_factory=dict)
    confidence: float = 0.0
    completeness: float = 0.0
    provenance: list[ProvenanceItem] = field(default_factory=list)


@dataclass(slots=True)
class CDSAssignment:
    raw_core_pct: float = 0.0
    raw_defensive_pct: float = 0.0
    raw_satellite_pct: float = 0.0
    core_pct: float = 0.0
    defensive_pct: float = 0.0
    satellite_pct: float = 0.0
    active_roles: list[str] = field(default_factory=list)
    confidence: float = 0.0
    reliability_score: float = 0.0
    validation_flags: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    def validate(self) -> None:
        total = self.core_pct + self.defensive_pct + self.satellite_pct
        if abs(total - 100.0) > 0.05:
            raise ValueError(f"C/D/S must sum to 100, got {total:.4f}")


@dataclass(slots=True)
class BenchmarkResolution:
    official_name: str = ""
    official_code: str = ""
    official_provider: str = ""
    official_source: str = ""

    operational_series: str = ""
    operational_label: str = ""
    operational_provider: str = ""
    operational_kind: OperationalKind | str = ""

    resolution_level: str = ""
    relation_grade: RelationGrade | str = ""
    components: list[BenchmarkComponent] = field(default_factory=list)

    benchmark_confidence: float = 0.0
    semantic_confidence: float = 0.0
    geometry_score: float = 0.0
    selection_score: float = 0.0
    coverage_obs: int = 0

    trend_similarity_pct: float | None = None
    tracking_adherence_pct: float | None = None
    correlation: float | None = None
    beta: float | None = None
    tracking_error_ann_pct: float | None = None

    note: str = ""
    provenance: list[ProvenanceItem] = field(default_factory=list)


@dataclass(slots=True)
class InstrumentAnalysis:
    ticker: str
    isin: str
    name: str = ""

    profile: InstrumentProfile = field(default_factory=InstrumentProfile)
    cds: CDSAssignment = field(default_factory=CDSAssignment)
    benchmark: BenchmarkResolution = field(default_factory=BenchmarkResolution)

    identity_sources: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    algorithm_version: str = ""
    resolved_at: str = ""
    elapsed_ms: int = 0
    cache_hit: bool = False

    def validate(self) -> None:
        self.cds.validate()
        if not self.benchmark.operational_series:
            raise ValueError("Every result must expose an operational comparison series.")
