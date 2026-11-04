"""Adapter factsheet/issuer. Riusa core/instrument_enrichment.py
(gia' scrapa justETF: benchmark testuale, replica, AUM, holdings) invece di
reimplementare lo scraping factsheet."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from core.instrument_analysis.contracts import ProvenanceItem
from core.instrument_enrichment import enrich_etf_etc


@dataclass(slots=True)
class IssuerFactsheet:
    benchmark_text: str = ""
    replica: str = ""
    aum: str = ""
    holdings_top: list = field(default_factory=list)
    provenance: ProvenanceItem | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def fetch_factsheet(isin: str) -> IssuerFactsheet | None:
    strumento = {"isin": str(isin or "").strip()}
    result = enrich_etf_etc(strumento)
    if result.get("enrichment_error"):
        return None
    return IssuerFactsheet(
        benchmark_text=str(result.get("benchmark") or ""),
        replica=str(result.get("replica") or ""),
        aum=str(result.get("aum") or ""),
        holdings_top=list(result.get("holdings_top") or []),
        provenance=ProvenanceItem(
            source="issuer_factsheet", field="profile", value=result.get("benchmark"),
            confidence=0.75, fetched_at=_now_iso(),
        ),
    )
