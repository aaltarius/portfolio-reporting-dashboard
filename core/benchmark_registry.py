"""Registro centrale benchmark per singolo strumento.

Questo modulo e' l'unica fonte di verita' per assegnare un benchmark operativo
al singolo strumento. Non dipende da Streamlit e non legge/scrive file: espone
solo regole pure e riutilizzabili da Quotazioni, Cruscotti, Summary e refresh
cache benchmark.

Fase B (2026-09-03): facade sottile su `InstrumentAnalysisService` — nessun
mapping statico ticker/ISIN/tipo/categoria in questo file. La risoluzione
automatica e' online-first (identita' ufficiale, ladder di famiglie, curve
sovrane, compositi multi-asset): vedi `core/instrument_analysis/`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.instrument_analysis.service import InstrumentAnalysisService

_SERVICE: InstrumentAnalysisService | None = None


def _service() -> InstrumentAnalysisService:
    """Singleton lazy — un solo `InstrumentAnalysisService` per processo
    (cache interna condivisa tra tutte le chiamate). Nei test si sostituisce
    direttamente `core.benchmark_registry._SERVICE` con un fake che implementa
    `analyze()`/`discovered_benchmark_catalog()`, mai una chiamata di rete
    reale in un test unitario."""
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = InstrumentAnalysisService()
    return _SERVICE


@dataclass(frozen=True, slots=True)
class BenchmarkAssignment:
    """Vista compatibile per i consumer esistenti.

    `ticker` resta il campo che i consumer usano per scaricare storico
    prezzi/correlazione: e' `operational_series` quando davvero interrogabile
    (`series_is_fetchable`), altrimenti il ticker di riserva del motore
    (`fallback_fetchable_series`, Task S) quando esiste, altrimenti vuoto.
    `label` resta SEMPRE l'identita' ufficiale (`operational_label`), mai
    sostituita dal fallback.
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
    coverage_obs: int = 0
    components: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    @property
    def has_benchmark(self) -> bool:
        return bool(str(self.ticker or "").strip())

    def as_dict(self) -> dict[str, str]:
        return {
            "ticker": str(self.ticker or "").strip(),
            "label": str(self.label or "").strip(),
            "source": str(self.source or "").strip(),
            "confidence": str(self.confidence or "").strip(),
            "note": str(self.note or "").strip(),
        }


def _norm(value: Any) -> str:
    return str(value or "").strip()


def _confidence_label(value: float) -> str:
    if value >= 0.85:
        return "Alta"
    if value >= 0.60:
        return "Media"
    return "Bassa"


def _duration_years(inst: dict[str, Any], master: dict[str, Any]) -> float | None:
    """`duration_modificata` (arricchimento PDF gia' esistente sullo
    strumento reale) se disponibile — necessario alla curva sovrana per i
    titoli di stato singoli. `None` se assente o non numerico: il motore
    degrada da solo (curva con floor minimo, vedi `sovereign_curve.py`)."""
    raw = master.get("duration_modificata")
    if raw is None:
        raw = inst.get("duration_modificata")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def resolve_instrument_benchmark(
    instrument: dict[str, Any] | None = None,
    *,
    ticker: str | None = None,
    isin: str | None = None,
    raw_type: str | None = None,
    category: str | None = None,
    master_entry: dict[str, Any] | None = None,
    prefer_master: bool = True,
) -> BenchmarkAssignment:
    """Restituisce il benchmark operativo per uno strumento.

    Ordine di priorita':
    1. override esplicito dell'utente (`manual_overrides.sator.benchmark_user_edited`);
    2. risoluzione automatica via `InstrumentAnalysisService` (identita'
       ufficiale online-first — mai euristiche per parola chiave).

    `raw_type`/`category` sono mantenuti in firma solo per compatibilita'
    con le chiamate esistenti: non guidano piu' la risoluzione automatica.
    """
    inst = instrument if isinstance(instrument, dict) else {}
    master = master_entry if isinstance(master_entry, dict) else {}

    tk = _norm(ticker or inst.get("ticker") or master.get("ticker")).upper()
    isincode = _norm(isin or inst.get("isin") or master.get("isin")).upper()

    if prefer_master:
        overrides = (master.get("manual_overrides") or {}).get("sator") or {}
        if overrides.get("benchmark_user_edited"):
            mt = _norm(overrides.get("benchmark_code"))
            ml = _norm(overrides.get("benchmark_label"))
            if mt or ml:
                return BenchmarkAssignment(mt, ml or mt or "Benchmark concettuale", "anagrafica", "Alta")

    analysis = _service().analyze(
        ticker=tk, isin=isincode, duration_years=_duration_years(inst, master),
    )
    b = analysis.benchmark

    fetchable_ticker = (
        b.operational_series if b.series_is_fetchable else b.fallback_fetchable_series
    )
    components = tuple(
        {
            "series_id": c.series_id,
            "label": c.label,
            "weight_pct": c.weight_pct,
            "provider": c.provider,
            "kind": str(c.kind or ""),
        }
        for c in b.components
    )

    return BenchmarkAssignment(
        ticker=_norm(fetchable_ticker),
        label=_norm(b.operational_label) or _norm(b.official_name) or "—",
        source=_norm(b.official_source) or _norm(b.operational_provider) or "runtime",
        confidence=_confidence_label(b.benchmark_confidence),
        note=_norm(b.note),
        official_name=b.official_name,
        official_code=b.official_code,
        operational_provider=b.operational_provider,
        operational_kind=str(b.operational_kind or ""),
        resolution_level=b.resolution_level,
        relation_grade=str(b.relation_grade or ""),
        semantic_confidence=b.semantic_confidence,
        geometry_score=b.geometry_score,
        selection_score=b.selection_score,
        coverage_obs=b.coverage_obs,
        components=components,
    )


def known_benchmark_catalog() -> list[tuple[str, str]]:
    """Coppie (ticker, label) scoperte a runtime dal motore (cache di
    risoluzione gia' popolata), per un `<datalist>` di scelta rapida in UI —
    non piu' un catalogo statico. Il campo benchmark resta testo libero."""
    return list(_service().discovered_benchmark_catalog())
