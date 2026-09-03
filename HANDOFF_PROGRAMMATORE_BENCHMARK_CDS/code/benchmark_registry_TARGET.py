"""TARGET replacement for the legacy static benchmark_registry.py.

This module must remain thin. It is a backward-compatible facade over the
central InstrumentAnalysisService. It must NOT contain automatic benchmark
catalogs, ticker/ISIN mappings, or market-family symbol lists.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class AnalysisServiceProtocol(Protocol):
    def analyze(
        self,
        *,
        ticker: str = "",
        isin: str = "",
        force_refresh: bool = False,
    ) -> Any:
        ...

    def discovered_benchmark_catalog(self) -> list[tuple[str, str]]:
        ...


_SERVICE: AnalysisServiceProtocol | None = None


def configure_analysis_service(service: AnalysisServiceProtocol) -> None:
    """Call once from application bootstrap / dependency injection."""
    global _SERVICE
    _SERVICE = service


def _service() -> AnalysisServiceProtocol:
    if _SERVICE is None:
        raise RuntimeError(
            "InstrumentAnalysisService not configured. "
            "Configure it during application bootstrap."
        )
    return _SERVICE


@dataclass(frozen=True, slots=True)
class BenchmarkAssignment:
    """Backward-compatible view for legacy consumers.

    `ticker` is retained ONLY for compatibility and means operational series ID.
    It is not necessarily a Yahoo ticker and it is never required to be an ETF.
    """
    ticker: str
    label: str
    source: str
    confidence: str = "Media"
    note: str = ""

    official_name: str = ""
    official_code: str = ""
    operational_provider: str = ""
    operational_kind: str = ""
    resolution_level: str = ""
    relation_grade: str = ""
    semantic_confidence: float = 0.0
    geometry_score: float = 0.0
    selection_score: float = 0.0
    components: tuple[dict[str, Any], ...] = ()

    @property
    def has_benchmark(self) -> bool:
        return bool(str(self.ticker or "").strip())

    @property
    def operational_series(self) -> str:
        return str(self.ticker or "").strip()

    def as_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.operational_series,
            "operational_series": self.operational_series,
            "label": str(self.label or "").strip(),
            "source": str(self.source or "").strip(),
            "confidence": str(self.confidence or "").strip(),
            "note": str(self.note or "").strip(),
            "official_name": self.official_name,
            "official_code": self.official_code,
            "operational_provider": self.operational_provider,
            "operational_kind": self.operational_kind,
            "resolution_level": self.resolution_level,
            "relation_grade": self.relation_grade,
            "semantic_confidence": self.semantic_confidence,
            "geometry_score": self.geometry_score,
            "selection_score": self.selection_score,
            "components": [dict(x) for x in self.components],
        }


def _confidence_label(value: float) -> str:
    if value >= 0.85:
        return "Alta"
    if value >= 0.60:
        return "Media"
    return "Bassa"


def resolve_instrument_benchmark(
    instrument: dict[str, Any] | None = None,
    *,
    ticker: str | None = None,
    isin: str | None = None,
    raw_type: str | None = None,     # retained only for signature compatibility
    category: str | None = None,     # retained only for signature compatibility
    master_entry: dict[str, Any] | None = None,
    prefer_master: bool = True,
) -> BenchmarkAssignment:
    """Resolve via the central service.

    Automatic analysis is driven by ticker/ISIN.
    Legacy type/category fields MUST NOT steer automatic benchmark selection.
    """
    inst = instrument if isinstance(instrument, dict) else {}
    master = master_entry if isinstance(master_entry, dict) else {}

    tk = str(ticker or inst.get("ticker") or master.get("ticker") or "").strip().upper()
    isincode = str(isin or inst.get("isin") or master.get("isin") or "").strip().upper()

    # Explicit USER override is allowed and remains separate from automation.
    if prefer_master:
        overrides = (master.get("manual_overrides") or {}).get("sator") or {}
        if overrides.get("benchmark_user_edited"):
            series_id = str(overrides.get("benchmark_code") or "").strip()
            label = str(overrides.get("benchmark_label") or series_id or "Benchmark manuale").strip()
            return BenchmarkAssignment(
                ticker=series_id,
                label=label,
                source="manual_override",
                confidence="Alta",
                note=str(overrides.get("benchmark_reason") or "Override esplicito utente."),
                operational_kind="MANUAL_OVERRIDE",
                resolution_level="MANUAL_OVERRIDE",
                relation_grade="MANUAL_OVERRIDE",
            )

    analysis = _service().analyze(ticker=tk, isin=isincode)
    b = analysis.benchmark

    components = tuple(
        {
            "series_id": getattr(c, "series_id", ""),
            "label": getattr(c, "label", ""),
            "weight_pct": getattr(c, "weight_pct", 0.0),
            "provider": getattr(c, "provider", ""),
            "kind": str(getattr(c, "kind", "") or ""),
        }
        for c in (getattr(b, "components", None) or [])
    )

    return BenchmarkAssignment(
        ticker=str(getattr(b, "operational_series", "") or ""),
        label=str(getattr(b, "operational_label", "") or getattr(b, "official_name", "") or "—"),
        source=str(getattr(b, "official_source", "") or getattr(b, "operational_provider", "") or "runtime"),
        confidence=_confidence_label(float(getattr(b, "benchmark_confidence", 0.0) or 0.0)),
        note=str(getattr(b, "note", "") or ""),
        official_name=str(getattr(b, "official_name", "") or ""),
        official_code=str(getattr(b, "official_code", "") or ""),
        operational_provider=str(getattr(b, "operational_provider", "") or ""),
        operational_kind=str(getattr(b, "operational_kind", "") or ""),
        resolution_level=str(getattr(b, "resolution_level", "") or ""),
        relation_grade=str(getattr(b, "relation_grade", "") or ""),
        semantic_confidence=float(getattr(b, "semantic_confidence", 0.0) or 0.0),
        geometry_score=float(getattr(b, "geometry_score", 0.0) or 0.0),
        selection_score=float(getattr(b, "selection_score", 0.0) or 0.0),
        components=components,
    )


def discovered_benchmark_catalog() -> list[tuple[str, str]]:
    """UI/autocomplete only.

    Contains values discovered at runtime/cache by the central service.
    It MUST NOT influence automatic resolution.
    """
    return list(_service().discovered_benchmark_catalog())


def known_benchmark_catalog() -> list[tuple[str, str]]:
    """Temporary backward-compatible alias.

    Remove once all consumers have migrated.
    """
    return discovered_benchmark_catalog()
