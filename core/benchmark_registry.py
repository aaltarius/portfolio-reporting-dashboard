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

from typing import TYPE_CHECKING
if TYPE_CHECKING:
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
        from core.instrument_analysis.service import InstrumentAnalysisService
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

    # Task V-diciannovesima (2026-09-06): esposti anche quando NON sono il
    # ticker scelto (`ticker` puo' gia' essere questo stesso valore, se
    # series_is_fetchable=False). Servono a chi vuole rilevare una sorgente
    # ferma/morta a runtime e verificare se esiste gia' un'alternativa
    # ufficiale nota nel motore di risoluzione, senza inventarne una nuova.
    fallback_fetchable_series: str = ""
    fallback_fetchable_label: str = ""

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
    *, ticker: str | None = None, isin: str | None = None,
    raw_type: str | None = None, category: str | None = None,
    master_entry: dict[str, Any] | None = None,
    prefer_master: bool = True, force_refresh: bool = False,
) -> BenchmarkAssignment:
    """Unico punto di accesso: indice, ETF proxy dichiarato o composito.

    Gli override ETF sono ammessi soltanto se censiti come proxy. `force_refresh` puo' attivare
    richieste online esplicite; il render normale legge sempre solo SQLite.
    """
    from core.verified_benchmarks.engine import resolve as resolve_verified
    from core.verified_benchmarks import IndexStore

    inst = dict(instrument) if isinstance(instrument, dict) else {}
    master = master_entry if isinstance(master_entry, dict) else {}
    tk = str(ticker or inst.get('ticker') or master.get('ticker') or '').strip()
    if not inst:
        inst = {'ticker': tk, 'nome': master.get('name') or tk,
                'tipo': raw_type or master.get('type_raw') or category or ''}
    else:
        inst.setdefault('ticker', tk)
        if raw_type and not inst.get('tipo'): inst['tipo'] = raw_type

    store = IndexStore()
    # Fase audit V4: tutti gli override manuali sono ignorati, anche qualora
    # fossero rimasti in un vecchio SQLite. Le scelte importate dai JSON non
    # dimostrano una decisione consapevole dell'utente.
    try:
        verified = resolve_verified(inst,master,store=store,online=force_refresh)
    except Exception:
        verified = None
    if verified is None:
        return BenchmarkAssignment(
            ticker='', label='Benchmark non ancora validato', source='motore indici',
            confidence='Bassa',
            note='Aggiornare online indici o ETF proxy; non simulare storici mancanti.',
            resolution_level='PENDING', relation_grade='NON_RISOLTO')
    return BenchmarkAssignment(
        ticker=verified.ticker, label=verified.label, source=verified.source,
        confidence=verified.confidence, note='; '.join(verified.notes),
        official_name=verified.label,operational_provider=verified.source,
        operational_kind=verified.kind,resolution_level='VERIFIED',
        relation_grade=verified.grade,coverage_obs=len(verified.series),
        components=tuple(verified.components))



def known_benchmark_catalog() -> list[tuple[str, str]]:
    """Opzioni per override: indici autentici ed ETF proxy dichiarati."""
    from core.verified_benchmarks import IndexStore
    return sorted([(code, ('[ETF proxy] ' if spec.asset_kind=='etf_proxy' else '[Indice] ')+spec.label)
                   for code,spec in IndexStore().specs().items() if spec.asset_kind!='composite'], key=lambda x:x[1])

