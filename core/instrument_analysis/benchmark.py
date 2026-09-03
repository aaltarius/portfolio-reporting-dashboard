"""Ladder di parentela per il benchmark: identita' ufficiale separata dalla
curva operativa (spec sezione 6). Domain lock applicato PRIMA di qualunque
punteggio di geometry/correlazione — vincolo non negoziabile."""
from __future__ import annotations

from typing import Callable

from core.instrument_analysis.contracts import (
    BenchmarkComponent, BenchmarkResolution, CDSAssignment, InstrumentProfile,
    OperationalKind, ProvenanceItem, RelationGrade,
)
from core.instrument_analysis.geometry import geometry_score
from core.instrument_analysis.metrics import benchmark_score, coverage_score
from core.instrument_analysis.profile import RawIdentitySignals
from core.instrument_analysis.reference_families import _is_equity, family_ladder
from core.instrument_analysis.series import blend_series

#: Semantic score fisso per il composito C/D/S (Task Q), stesso valore
#: usato da `_mixed_role_composite` nel riferimento validato
#: (`semantic_confidence=.70`, grado "NONNA COMPOSITA") — non e' un
#: confronto diretto (CUGINA/ZIA), e' una costruzione pesata di due
#: confronti, valutata sul proprio merito via geometria.
_COMPOSITE_SEMANTIC_SCORE = 0.70

#: Semantic score per il composito multi-asset da composizione REALE
#: (Task R, `profile.asset_mix` da `funds_data.asset_classes`) — piu' alto
#: del composito C/D/S (Task Q, euristica sui ruoli) perche' qui i pesi
#: delle gambe vengono dal fondo stesso, non da un'inferenza.
_MULTI_ASSET_SEMANTIC_SCORE = 0.80

#: Osservazioni minime per accettare il composito multi-asset — a
#: differenza del composito C/D/S (Task Q) NON c'e' una soglia minima di
#: geometry_score: la composizione e' un dato reale del fondo, non
#: un'euristica da validare sul tracking (handoff sezione H, invariante
#: "asset_class multiasset => operational_kind COMPOSITE").
_MULTI_ASSET_MIN_OBSERVATIONS = 20

#: Soglie minime per accettare un candidato del ladder intermedio (gap 1):
#: almeno 20 osservazioni comuni (stesso ordine di grandezza usato altrove
#: nel motore per considerare una serie "avviata") e geometry_score >= 40
#: (POC17.2 usa soglie piu' articolate per tier di n — qui un valore unico
#: di partenza, da tarare col replay ufficiale, Task L5 del piano).
_LADDER_MIN_OBSERVATIONS = 20
_LADDER_MIN_GEOMETRY_SCORE = 40.0

DOMAIN_LOCK_FORBIDDEN: dict[str, frozenset[str]] = {
    "AZI": frozenset({"OBB", "GOV", "LIQ"}),
    "ETF": frozenset({"OBB", "GOV", "LIQ"}),
    "OBB": frozenset({"AZI", "ETF", "ETC"}),
    "GOV": frozenset({"AZI", "ETF", "ETC"}),
    "ETC": frozenset({"OBB", "GOV"}),
}

# Curva "mercato generale" per asset_class quando nessuna fonte online ha
# prodotto un match utilizzabile: ultimo gradino del ladder prima
# dell'emergenza infrastrutturale, sempre una curva reale (mai BASE100
# normale).
_GENERAL_MARKET_SERIES: dict[str, str] = {
    "AZI": "^990100-USD-STRD",  # MSCI World
    "ETF": "^990100-USD-STRD",
    "OBB": "LEGATRUU-Index",    # Bloomberg Global Aggregate (placeholder di libreria, non hardcoded per strumento)
    "GOV": "LEGATRUU-Index",
    "ETC": "BCOMTR-Index",      # Bloomberg Commodity
}


def domain_locked(source_asset_class: str, candidate_asset_class: str) -> bool:
    forbidden = DOMAIN_LOCK_FORBIDDEN.get(str(source_asset_class or "").upper(), frozenset())
    return str(candidate_asset_class or "").upper() in forbidden


def _best_candidate_geometry(
    instrument_series: dict[str, float],
    candidates: list[tuple[str, dict[str, float]]],
) -> tuple[float, int, str] | None:
    """Tra tutti i candidati di una riga del ladder, tiene quello con la
    geometria migliore che supera il gate — non il primo disponibile
    (Task O: verificato che XDBC.MI traccia `^BCOM` molto meglio di
    `^SPGSCI` — 82,0 contro 63,8 — pur essendo entrambi candidati
    legittimi della stessa famiglia COMMODITY; stesso pattern su
    EIMI.MI/XMME.MI dove `000001.SS` batte nettamente `^HSI`/`^BSESN`)."""
    best: tuple[float, int, str] | None = None
    for ticker, series in candidates:
        if not series:
            continue
        geom_score, n = geometry_score(instrument_series, series)
        if n < _LADDER_MIN_OBSERVATIONS or geom_score < _LADDER_MIN_GEOMETRY_SCORE:
            continue
        if best is None or geom_score > best[0]:
            best = (geom_score, n, ticker)
    return best


def _best_ladder_match(
    instrument_series: dict[str, float],
    ladder: list[tuple[RelationGrade, float, str, str]],
    family_series_fn: Callable[[str], list[tuple[str, dict[str, float]]]],
) -> tuple[RelationGrade, float, float, int, str, str, str, float] | None:
    """Tra TUTTE le righe della scaletta che superano il gate (non solo la
    prima, Task N2), tiene quella con il punteggio combinato finale
    migliore — non necessariamente il grado semantico piu' vicino.

    Task P: verificato che il grado piu' vicino puo' tracciare peggio nella
    pratica — VJPA.MI (Japan) traccia `^N225` solo a 35,0 di geometria (sotto
    il gate), mentre il confronto piu' ampio GLOBAL_EQUITY arriva a 60,8:
    fermarsi alla prima riga che supera la soglia (ordine di priorita'
    semantica) avrebbe potuto scegliere un candidato peggiore di uno
    disponibile su una riga successiva. Confrontare il punteggio combinato
    finale (semantic+geometry+coverage, non la sola geometria) evita questo
    rischio in entrambe le direzioni.

    Ritorna (grade, semantic_score, geom_score, n, family, ticker, reason,
    combined_score) o None se nessuna riga produce un candidato che supera
    il gate."""
    best: tuple[RelationGrade, float, float, int, str, str, str, float] | None = None
    for grade, semantic_score, family, reason in ladder:
        candidates = family_series_fn(family)
        if not candidates:
            continue
        candidate_best = _best_candidate_geometry(instrument_series, candidates)
        if candidate_best is None:
            continue
        geom_score, n, ticker = candidate_best
        combined = benchmark_score(semantic_score * 100.0, geom_score, coverage_score(n))
        if best is None or combined > best[7]:
            best = (grade, semantic_score, geom_score, n, family, ticker, reason, combined)
    return best


def _mixed_role_composite_candidate(
    profile: InstrumentProfile,
    cds: CDSAssignment | None,
    instrument_series: dict[str, float],
    family_series_fn: Callable[[str], list[tuple[str, dict[str, float]]]],
) -> tuple[RelationGrade, float, float, int, str, str, str, float, list[BenchmarkComponent]] | None:
    """Curva composita a 2 gambe pesata per C/D/S (Task Q, 2026-09-03 —
    idea dell'utente, confermata in `_mixed_role_composite` di
    `HANDOFF_PROGRAMMATORE_BENCHMARK_CDS/reference/poc17_4_engine_VALIDATED_REFERENCE.py`,
    riga 3558). Porta il PRINCIPIO (pesi C/D/S, step 5% come gia'
    dichiarato nel docstring di `composite.py`), non il codice letterale:
    `_domain_role_series` del riferimento userebbe lo stesso identico
    profilo per entrambe le gambe sull'equity, collassando quasi sempre a
    un'unica serie (branch `SINGLE_DOMAIN_COLLAPSE`) — qui le due gambe
    sono deliberatamente diverse (la riga piu' stretta del ladder per il
    ruolo satellite, la riga piu' ampia per l'altro ruolo), verificato
    empiricamente che funziona (VJPA.MI: geometria 82,6 contro 58,4 del
    solo confronto ampio).

    Scope deliberatamente ristretto: **solo profili equity con satellite
    tra i due ruoli C/D/S piu' grandi**. Verificato che il blend
    danneggia i bond (EM13.MI: 62,8 contro 65,7 del solo AGG) — non
    tentato qui, `_is_equity` filtra a monte."""
    if cds is None:
        return None
    structural_type = str(profile.structural_type or "")
    if not _is_equity(structural_type):
        return None

    roles = sorted(
        [("core", cds.core_pct), ("defensive", cds.defensive_pct), ("satellite", cds.satellite_pct)],
        key=lambda item: item[1], reverse=True,
    )
    dominant_role, dominant_pct = roles[0]
    second_role, second_pct = roles[1]
    if second_pct <= 0:
        return None  # un solo ruolo attivo: nessun blend da fare
    if "satellite" not in (dominant_role, second_role):
        return None  # scope Task Q: solo core/defensive misti a satellite

    ladder = family_ladder(profile)
    if len(ladder) < 2:
        return None
    narrow_family = ladder[0][2]
    broad_family = ladder[-1][2]
    if narrow_family == broad_family:
        return None

    total_pct = dominant_pct + second_pct
    dominant_weight = max(0.05, min(0.95, round((dominant_pct / total_pct) * 20) / 20.0))
    second_weight = 1.0 - dominant_weight
    satellite_weight = dominant_weight if dominant_role == "satellite" else second_weight
    other_weight = 1.0 - satellite_weight

    narrow_candidates = family_series_fn(narrow_family)
    broad_candidates = family_series_fn(broad_family)
    if not narrow_candidates or not broad_candidates:
        return None
    narrow_ticker, narrow_series = narrow_candidates[0]
    broad_ticker, broad_series = broad_candidates[0]
    if not narrow_series or not broad_series:
        return None

    blended = blend_series(narrow_series, satellite_weight, broad_series, other_weight)
    if not blended:
        return None
    geom_score, n = geometry_score(instrument_series, blended)
    if n < _LADDER_MIN_OBSERVATIONS or geom_score < _LADDER_MIN_GEOMETRY_SCORE:
        return None

    narrow_pct = round(satellite_weight * 100.0)
    broad_pct = 100.0 - narrow_pct
    components = [
        BenchmarkComponent(series_id=narrow_ticker, label=narrow_family, weight_pct=narrow_pct, kind=OperationalKind.COMPOSITE),
        BenchmarkComponent(series_id=broad_ticker, label=broad_family, weight_pct=broad_pct, kind=OperationalKind.COMPOSITE),
    ]
    combined = benchmark_score(_COMPOSITE_SEMANTIC_SCORE * 100.0, geom_score, coverage_score(n))
    reason = f"C/D/S-weighted composite: {narrow_pct:.0f}% {narrow_family} + {broad_pct:.0f}% {broad_family}"
    label = f"{narrow_pct:.0f}% {narrow_family} + {broad_pct:.0f}% {broad_family}"
    return (
        RelationGrade.BROAD_FAMILY, _COMPOSITE_SEMANTIC_SCORE, geom_score, n,
        label, "COMPOSITE", reason, combined, components,
    )


def _multi_asset_composite_candidate(
    profile: InstrumentProfile,
    instrument_series: dict[str, float],
    family_series_fn: Callable[[str], list[tuple[str, dict[str, float]]]],
) -> tuple[RelationGrade, float, float, int, str, str, str, float, list[BenchmarkComponent]] | None:
    """Curva composita a 2 gambe da composizione REALE del fondo (Task R,
    2026-09-03 — handoff sezione H "MULTI-ASSET / FONDI FLESSIBILI", mai
    collegata prima: `composite.py`/A11 esisteva gia', mancava solo il dato
    di composizione in ingresso). A differenza del composito C/D/S (Task Q,
    euristica sui ruoli), qui i pesi vengono da `profile.asset_mix`
    (`funds_data.asset_classes` di yfinance, popolato in `service.py` solo
    per fondi comuni con dato disponibile — mai un'euristica testuale).

    Verificato in diretta (2026-09-03) sui 4 fondi Fineco AM proprietari
    (FAM-EMD/FLEX/PU6/PU8): composizione reale plausibile con la natura
    dichiarata di ciascun fondo (es. FAM-FLEX 59% azioni/33% bond)."""
    mix = profile.asset_mix
    if not mix:
        return None
    equity_pct = float(mix.get("equity", 0.0))
    bond_pct = float(mix.get("bond", 0.0))
    if equity_pct <= 0 or bond_pct <= 0:
        return None  # non una miscela equity+bond: nessuna gamba da costruire

    total_pct = equity_pct + bond_pct
    equity_weight = max(0.05, min(0.95, round((equity_pct / total_pct) * 20) / 20.0))
    bond_weight = 1.0 - equity_weight

    equity_candidates = family_series_fn("GLOBAL_EQUITY")
    bond_candidates = family_series_fn("AGG_BOND")
    if not equity_candidates or not bond_candidates:
        return None
    equity_ticker, equity_series = equity_candidates[0]
    bond_ticker, bond_series = bond_candidates[0]
    if not equity_series or not bond_series:
        return None

    blended = blend_series(equity_series, equity_weight, bond_series, bond_weight)
    if not blended:
        return None
    geom_score, n = geometry_score(instrument_series, blended)
    if n < _MULTI_ASSET_MIN_OBSERVATIONS:
        return None  # troppo pochi punti in comune per un confronto onesto

    equity_leg_pct = round(equity_weight * 100.0)
    bond_leg_pct = 100.0 - equity_leg_pct
    components = [
        BenchmarkComponent(series_id=equity_ticker, label="GLOBAL_EQUITY", weight_pct=equity_leg_pct, kind=OperationalKind.COMPOSITE),
        BenchmarkComponent(series_id=bond_ticker, label="AGG_BOND", weight_pct=bond_leg_pct, kind=OperationalKind.COMPOSITE),
    ]
    combined = benchmark_score(_MULTI_ASSET_SEMANTIC_SCORE * 100.0, geom_score, coverage_score(n))
    label = f"{equity_leg_pct:.0f}% GLOBAL_EQUITY + {bond_leg_pct:.0f}% AGG_BOND"
    reason = f"Multi-asset composite (real composition): {label}"
    return (
        RelationGrade.STRUCTURAL_COMPOSITE, _MULTI_ASSET_SEMANTIC_SCORE, geom_score, n,
        label, "COMPOSITE", reason, combined, components,
    )


#: ETF governativo reale per paese (2026-09-03, richiesta esplicita
#: dell'utente: "basta il confronto con qualsiasi indice obbligazionario
#: nazionale... senza complicarci troppo la vita" — molto piu' semplice
#: della curva sintetica ECB sotto, che resta come fallback per i paesi
#: non mappati qui). Espandibile ad altri paesi se servisse.
_COUNTRY_GOV_BOND_FAMILY: dict[str, str] = {"IT": "ITALY_GOV_BOND"}


def _country_gov_bond_candidate(
    profile: InstrumentProfile,
    country: str,
    instrument_series: dict[str, float],
    family_series_fn: Callable[[str], list[tuple[str, dict[str, float]]]] | None,
) -> tuple[str, str, float, int] | None:
    """Titolo di stato singolo confrontato con un ETF governativo REALE del
    paese emittente (es. BTP contro `EDMA.MU`, iShares Italy Govt Bond,
    254 osservazioni Yahoo reali verificate). Assegnazione diretta come
    EXACT/SISTER (non passa dal ladder con gate di geometria obbligatorio,
    Task N1/L): un BTP non ha un ticker Yahoo proprio interrogabile da
    questo motore, quindi non c'e' `instrument_series` con cui competere
    sul punteggio — la geometria, se per qualche motivo disponibile, resta
    solo un bonus di qualita' sui campi di punteggio, mai un gate."""
    if str(profile.issuer_type or "") != "government":
        return None
    family = _COUNTRY_GOV_BOND_FAMILY.get(str(country or "").upper())
    if not family or family_series_fn is None:
        return None
    candidates = family_series_fn(family)
    if not candidates:
        return None
    ticker, series = candidates[0]
    if not series:
        return None
    geom_score, n = (0.0, 0)
    if instrument_series:
        candidate_score, candidate_n = geometry_score(instrument_series, series)
        # Stesso minimo osservazioni del ladder (Task N1): con troppo pochi
        # punti in comune (es. un BTP appena entrato in portafoglio, storico
        # a 7 giorni) un punteggio alto sarebbe rumore statistico, non un
        # segnale affidabile — meglio restare al solo punteggio di
        # confidence che gonfiarlo con una geometria non robusta.
        if candidate_n >= _LADDER_MIN_OBSERVATIONS:
            geom_score, n = candidate_score, candidate_n
    return ticker, family, geom_score, n


def _sovereign_synthetic_candidate(
    profile: InstrumentProfile,
    sovereign_curve_fn: Callable[[float], tuple[dict[str, float], bool]] | None,
    instrument_series: dict[str, float],
) -> tuple[str, str, float, dict[str, float], float, int] | None:
    """Curva sovrana sintetica duration-matched per obbligazioni governative
    singole (Task R, 2026-09-03 — handoff sezione I "BOND/BTP": "Mai usare
    ETF proxy... costruire curve duration-specific con fonti ufficiali").
    Porta il principio di `sovereign_synthetic` dal riferimento validato
    (righe 2096-2130): curva euro-area (ECB, verificata in diretta) piu'
    spread Italia best-effort (Banca d'Italia, degrada onestamente se non
    disponibile — vedi `service._fetch_sovereign_synthetic_curve`).

    Preferita esplicitamente dall'utente rispetto a un ETF (2026-09-03:
    "non mi fa impazzire avere per indice un ETF... vorrei un indice puro
    se possibile") — questa e' una curva di rendimenti pubblicata, non un
    fondo. Se `instrument_series` e' disponibile con abbastanza
    osservazioni (storico reale fornito dal chiamante, es.
    `portafoglio_storico_prezzi.json` per un BTP), la geometria contro
    questa stessa curva sintetica diventa un bonus di qualita' sul
    punteggio finale — mai un gate, la curva resta valida anche senza.

    Scope ristretto a `issuer_type == "government"` con duration nota:
    corporate bond e fondi obbligazionari pooled continuano a usare la
    scaletta normale (ETF proxy legittimo per un fondo, non per
    un'obbligazione singola)."""
    if sovereign_curve_fn is None:
        return None
    if str(profile.issuer_type or "") != "government":
        return None
    duration = profile.duration_years
    if not duration or duration <= 0:
        return None
    series, spread_found = sovereign_curve_fn(duration)
    if len(series) < 2:
        return None
    confidence = 0.89 if spread_found else 0.58
    sovereign_label = "IT" if spread_found else "EUR"
    label = (
        f"Italy Sovereign Synthetic Total Return — duration {duration:.2f}Y"
        if spread_found else
        f"EUR Sovereign Reference — duration {duration:.2f}Y (Italy spread unavailable)"
    )
    series_id = f"{sovereign_label}-SOV-SYNTH-D{duration:.2f}"
    geom_score, n = (0.0, 0)
    if instrument_series:
        candidate_score, candidate_n = geometry_score(instrument_series, series)
        if candidate_n >= _LADDER_MIN_OBSERVATIONS:
            geom_score, n = candidate_score, candidate_n
    return series_id, label, confidence, series, geom_score, n


def _best_geometry_candidate(
    profile: InstrumentProfile,
    cds: CDSAssignment | None,
    instrument_series: dict[str, float],
    ladder: list[tuple[RelationGrade, float, str, str]],
    family_series_fn: Callable[[str], list[tuple[str, dict[str, float]]]],
) -> tuple[RelationGrade, float, float, int, str, str, str, float, list[BenchmarkComponent] | None] | None:
    """Combina il miglior confronto singolo (`_best_ladder_match`) e il
    composito pesato per C/D/S (Task Q, `_mixed_role_composite_candidate`)
    — tiene quello col punteggio combinato finale migliore, mai
    automaticamente il composito solo perche' "piu' sofisticato": se una
    famiglia singola traccia meglio, vince quella (verificato che il
    composito puo' anche fare peggio, es. sui bond)."""
    single = _best_ladder_match(instrument_series, ladder, family_series_fn)
    composite = _mixed_role_composite_candidate(profile, cds, instrument_series, family_series_fn)
    candidates = []
    if single is not None:
        candidates.append((*single, None))
    if composite is not None:
        candidates.append(composite)
    if not candidates:
        return None
    return max(candidates, key=lambda candidate: candidate[7])


def _dominant_component_fallback(components: list[BenchmarkComponent] | None) -> tuple[str, str]:
    """Task S: quando l'identita' ufficiale e' un composito (nessun ticker
    Yahoo singolo per costruzione), la gamba di peso maggiore e' un proxy
    scaricabile onesto per grafici/correlazione — non l'identita' ufficiale,
    solo un fallback opportunistico. ("", "") se non c'e' nulla."""
    if not components:
        return "", ""
    dominant = max(components, key=lambda c: c.weight_pct)
    return dominant.series_id, dominant.label


def _augment_with_geometry_signal(
    resolution: BenchmarkResolution,
    profile: InstrumentProfile,
    cds: CDSAssignment | None,
    instrument_series_fn: Callable[[], dict[str, float]] | None,
    family_series_fn: Callable[[str], list[tuple[str, dict[str, float]]]] | None,
) -> None:
    """Popola geometry_score/coverage_obs su un EXACT/SISTER gia' risolto,
    come controllo di qualita' supplementare (Task M3-bis — la ricerca
    testuale nome->ticker prevista in origine non funziona nella pratica,
    vedi "Verifica empirica" nel piano). Non tocca MAI
    operational_series/relation_grade/official_name: il candidato di
    famiglia (o composito, Task Q) qui e' solo un termine di paragone per
    la geometria, non sostituisce l'identita' ufficiale gia' trovata.
    No-op silenzioso se manca un dato qualunque — mai un errore, mai un
    valore inventato."""
    if instrument_series_fn is None or family_series_fn is None:
        return
    ladder = family_ladder(profile)
    if not ladder:
        return
    instrument_series = instrument_series_fn()
    if not instrument_series:
        return
    best = _best_geometry_candidate(profile, cds, instrument_series, ladder, family_series_fn)
    if best is None:
        return
    _grade, semantic_score, geom_score, n, _family, _ticker, _reason, combined, _components = best
    resolution.semantic_confidence = semantic_score
    resolution.geometry_score = geom_score
    resolution.coverage_obs = n
    resolution.selection_score = combined
    # Task S: se il candidato vincente e' un ticker di famiglia singolo (non
    # un composito, che qui userebbe il placeholder "COMPOSITE" al posto di
    # un simbolo reale), offrirlo come fallback scaricabile per grafici —
    # senza mai toccare operational_series/relation_grade sopra.
    if not _components and _ticker and _ticker != "COMPOSITE":
        resolution.fallback_fetchable_series = _ticker
        resolution.fallback_fetchable_label = _family
    elif _components:
        resolution.fallback_fetchable_series, resolution.fallback_fetchable_label = (
            _dominant_component_fallback(_components)
        )


def resolve_benchmark(
    profile: InstrumentProfile,
    signals: RawIdentitySignals,
    *,
    cds: CDSAssignment | None = None,
    instrument_series_fn: Callable[[], dict[str, float]] | None = None,
    family_series_fn: Callable[[str], list[tuple[str, dict[str, float]]]] | None = None,
    sovereign_curve_fn: Callable[[float], tuple[dict[str, float], bool]] | None = None,
    country: str = "",
) -> BenchmarkResolution:
    # Nota: solo il ramo FAMILY_LADDER (gap 1, sotto) valorizza
    # `series_is_fetchable=True` — l'unico caso in cui `operational_series`
    # e' davvero un ticker Yahoo interrogabile, non un'etichetta scrapata
    # (EXACT/SISTER) o un placeholder di libreria (GENERAL_MARKET_FALLBACK).
    # Vedi il commento del campo in contracts.py.
    resolution = BenchmarkResolution()

    if signals.borsa_italiana and signals.borsa_italiana.benchmark_name:
        resolution.official_name = signals.borsa_italiana.benchmark_name
        resolution.official_source = "borsa_italiana"
        resolution.operational_series = signals.borsa_italiana.benchmark_name
        resolution.operational_label = signals.borsa_italiana.benchmark_name
        resolution.operational_kind = OperationalKind.PROVIDER_INDEX
        resolution.resolution_level = "EXACT_FROM_OFFICIAL_SOURCE"
        resolution.relation_grade = RelationGrade.EXACT
        resolution.benchmark_confidence = signals.borsa_italiana.provenance.confidence
        resolution.provenance.append(signals.borsa_italiana.provenance)
        _augment_with_geometry_signal(resolution, profile, cds, instrument_series_fn, family_series_fn)
        return resolution

    if signals.issuer and signals.issuer.benchmark_text:
        resolution.official_name = signals.issuer.benchmark_text
        resolution.official_source = "issuer_factsheet"
        resolution.operational_series = signals.issuer.benchmark_text
        resolution.operational_label = signals.issuer.benchmark_text
        resolution.operational_kind = OperationalKind.PROVIDER_INDEX
        resolution.resolution_level = "SISTER_FROM_FACTSHEET_TEXT"
        resolution.relation_grade = RelationGrade.SISTER
        if signals.issuer.provenance:
            resolution.benchmark_confidence = signals.issuer.provenance.confidence
            resolution.provenance.append(signals.issuer.provenance)
        else:
            resolution.benchmark_confidence = 0.5
        _augment_with_geometry_signal(resolution, profile, cds, instrument_series_fn, family_series_fn)
        return resolution

    # Multi-asset da composizione reale (Task R, handoff sezione H): tentato
    # PRIMA della scaletta CUGINA/ZIA/NONNA, che presuppone una singola
    # asset class — un fondo genuinamente misto (`profile.asset_mix`
    # popolato solo quando nessuna classe supera il 90%, vedi profile.py)
    # non ha una "famiglia" unica sensata da confrontare. Tentato SOLO se
    # EXACT/SISTER non hanno gia' risolto sopra: un nome ufficiale scrapato
    # resta piu' autorevole di una ricostruzione sintetica quando esiste.
    if profile.asset_mix and instrument_series_fn is not None and family_series_fn is not None:
        instrument_series = instrument_series_fn()
        if instrument_series:
            multi_asset = _multi_asset_composite_candidate(profile, instrument_series, family_series_fn)
            if multi_asset is not None:
                grade, semantic_score, geom_score, n, label, _ticker, reason, combined, components = multi_asset
                resolution.official_name = f"Reference (composite): {label}"
                resolution.official_source = "reference_composite"
                resolution.operational_series = "COMPOSITE"
                resolution.operational_label = label
                resolution.operational_kind = OperationalKind.COMPOSITE
                resolution.series_is_fetchable = False
                resolution.components = components
                resolution.fallback_fetchable_series, resolution.fallback_fetchable_label = (
                    _dominant_component_fallback(components)
                )
                resolution.resolution_level = "MULTI_ASSET_COMPOSITE"
                resolution.relation_grade = grade
                resolution.semantic_confidence = semantic_score
                resolution.geometry_score = geom_score
                resolution.selection_score = combined
                resolution.benchmark_confidence = combined / 100.0
                resolution.coverage_obs = n
                resolution.note = f"{grade.value}: {reason}."
                return resolution

    # Titolo di stato singolo (Task R, handoff sezione I: "mai usare ETF
    # proxy... costruire curve duration-specific con fonti ufficiali").
    # Ordine deciso dall'utente (2026-09-03, dopo aver visto il primo giro
    # con un ETF: "non mi fa impazzire avere per indice un ETF... vorrei un
    # indice puro se possibile"): PRIMA la curva sovrana ECB (fonte
    # ufficiale, una curva di rendimenti pubblicata — non un fondo/ETF),
    # SOLO se quella fallisce (rete, fonte indisponibile) il confronto
    # diretto con l'ETF governativo nazionale come rete di sicurezza — mai
    # "non trovo nulla" quando esiste un'alternativa ragionevole.
    # `instrument_series` calcolato una sola volta e riusato da entrambi i
    # tentativi (bug corretto: prima veniva richiesto due volte).
    if str(profile.issuer_type or "") == "government":
        instrument_series = instrument_series_fn() if instrument_series_fn is not None else {}

        sovereign = _sovereign_synthetic_candidate(profile, sovereign_curve_fn, instrument_series)
        if sovereign is not None:
            series_id, label, confidence, series, geom_score, n = sovereign
            resolution.official_name = label
            resolution.official_source = "ecb_sdw"
            resolution.operational_series = series_id
            resolution.operational_label = label
            resolution.operational_kind = OperationalKind.SOVEREIGN_CURVE
            resolution.series_is_fetchable = False
            resolution.resolution_level = "SOVEREIGN_SYNTHETIC_CURVE"
            resolution.relation_grade = RelationGrade.STRUCTURAL_COMPOSITE
            resolution.benchmark_confidence = confidence
            resolution.geometry_score = geom_score
            resolution.coverage_obs = n if n else len(series)
            resolution.note = f"Sovereign synthetic curve (duration {profile.duration_years:.2f}Y, no ETF proxy)."
            # Task S: la curva ECB non ha un ticker Yahoo per costruzione —
            # l'ETF governativo nazionale (stessa fonte usata sotto come
            # fallback quando la curva fallisce) offre un proxy scaricabile
            # per grafici, senza toccare l'identita' ufficiale (la curva
            # resta operational_series/relation_grade).
            country_bond_fallback = _country_gov_bond_candidate(profile, country, instrument_series, family_series_fn)
            if country_bond_fallback is not None:
                fb_ticker, fb_family, _fb_geom, _fb_n = country_bond_fallback
                resolution.fallback_fetchable_series = fb_ticker
                resolution.fallback_fetchable_label = fb_family.replace("_", " ").title()
            return resolution

        country_bond = _country_gov_bond_candidate(profile, country, instrument_series, family_series_fn)
        if country_bond is not None:
            ticker, family, geom_score, n = country_bond
            family_label = family.replace("_", " ").title()
            resolution.official_name = f"Reference: {family_label} ({ticker})"
            resolution.official_source = "reference_family"
            resolution.operational_series = ticker
            resolution.operational_label = f"Reference: {family_label} ({ticker})"
            resolution.operational_kind = OperationalKind.YAHOO_INDEX
            resolution.series_is_fetchable = True
            resolution.resolution_level = "COUNTRY_GOV_BOND"
            resolution.relation_grade = RelationGrade.SISTER
            resolution.geometry_score = geom_score
            resolution.coverage_obs = n
            resolution.benchmark_confidence = 0.75
            resolution.note = f"Country government bond ETF reference ({family}, curva ECB non disponibile)."
            return resolution

    # Gradini intermedi (CUGINA/ZIA/NONNA — gap 1, Task L4): tentati solo se
    # il chiamante ha iniettato le due funzioni di fetch (lazy — mai una
    # chiamata di rete se questo ramo non serve, es. quando EXACT/SISTER
    # hanno gia' risolto sopra). `family_ladder(profile)` e' vuoto per i
    # bond (nessun branch equity/gold/commodity/digital_asset) — il domain
    # lock e' garantito per costruzione, non serve riverificarlo qui.
    ladder = family_ladder(profile)
    if ladder and instrument_series_fn is not None and family_series_fn is not None:
        instrument_series = instrument_series_fn()
        if instrument_series:
            best = _best_geometry_candidate(profile, cds, instrument_series, ladder, family_series_fn)
            if best is not None:
                grade, semantic_score, geom_score, n, family_or_label, candidate_ticker, reason, combined, components = best
                if components:
                    # Task Q: vince il composito pesato per C/D/S — l'identita'
                    # ufficiale e' la curva pesata stessa, non un singolo ticker.
                    resolution.official_name = f"Reference (composite): {family_or_label}"
                    resolution.official_source = "reference_composite"
                    resolution.operational_series = "COMPOSITE"
                    resolution.operational_label = family_or_label
                    resolution.operational_kind = OperationalKind.COMPOSITE
                    resolution.series_is_fetchable = False
                    resolution.components = components
                    resolution.fallback_fetchable_series, resolution.fallback_fetchable_label = (
                        _dominant_component_fallback(components)
                    )
                else:
                    family_label = family_or_label.replace("_", " ").title()
                    resolution.official_name = f"Reference: {family_label}"
                    resolution.official_source = "reference_family"
                    resolution.operational_series = candidate_ticker
                    resolution.operational_label = f"Reference: {family_label} ({candidate_ticker})"
                    resolution.operational_kind = OperationalKind.YAHOO_INDEX
                    resolution.series_is_fetchable = True
                resolution.resolution_level = "FAMILY_LADDER"
                resolution.relation_grade = grade
                resolution.semantic_confidence = semantic_score
                resolution.geometry_score = geom_score
                resolution.selection_score = combined
                resolution.benchmark_confidence = combined / 100.0
                resolution.coverage_obs = n
                resolution.note = f"{grade.value}: {reason}."
                return resolution

    # Nessuna fonte diretta: scende al mercato generale per la stessa
    # asset class (mai cross-asset — domain lock rispettato per
    # costruzione, non serve verificarlo qui perche' la tabella e' chiavata
    # per asset_class della fonte).
    general_series = _GENERAL_MARKET_SERIES.get(str(profile.asset_class or "").upper())
    if general_series:
        resolution.operational_series = general_series
        resolution.operational_label = f"Mercato generale ({profile.asset_class})"
        resolution.operational_kind = OperationalKind.YAHOO_INDEX
        resolution.resolution_level = "GENERAL_MARKET_FALLBACK"
        resolution.relation_grade = RelationGrade.GENERAL_MARKET
        resolution.benchmark_confidence = 0.3
        resolution.note = "Nessuna fonte diretta disponibile: fallback a mercato generale per asset class."
        return resolution

    # Emergenza infrastrutturale esplicita — mai un normale BASE100.
    resolution.operational_series = "INFRASTRUCTURE_EMERGENCY"
    resolution.operational_kind = OperationalKind.INFRASTRUCTURE_EMERGENCY
    resolution.resolution_level = "INFRASTRUCTURE_EMERGENCY"
    resolution.relation_grade = RelationGrade.TECHNICAL_EMERGENCY
    resolution.benchmark_confidence = 0.0
    resolution.note = "Nessuna asset class riconosciuta: fonti esaurite."
    return resolution
