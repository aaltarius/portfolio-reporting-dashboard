"""Dataset condivisi per le pagine dashboard.

Primo step del refactor centralizzato:
- separa i dati raw dalle derivazioni condivise
- concentra firme/cache di payload e figure fuori dalle pagine UI
- offre un punto unico di invalidazione e osservazione
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from typing import Any

import pandas as pd
import streamlit as st

from core.asset_categories import ACTIVE_CATEGORY_CODES, get_selected_category_codes
from core.cache_signatures import build_category_data_signature
from core.cache_policy import build_cache_artifact_signature, get_cache_artifact_spec
from core.cache_orchestrator import get_or_build_registered_artifact
from core.cashflow_indices import build_group_cashflow_indices, seed_group_cashflow_indices_cache
from core.settings_profiles import get_effective_summary_settings, get_runtime_ui_settings
from core.services import get_valid_quote_tickers_by_category
from core.finance import build_category_dashboard_data, build_gov_dashboard_data
from core.finance import build_portfolio_summary_payload, get_cached_benchmark_series, calc_positions
from core.series_utils import get_current_position_start_dates
from core.series_resample import downsample_for_display
from core.render_profiler import profile_step, record_render_event
from persistence.storage import DATA_DIR, macro_cat, save_benchmark_data, save_data
from core.benchmark_registry import resolve_instrument_benchmark
import yfinance as yf

logger = logging.getLogger("portafoglio.core.dashboard_datasets")

_BENCHMARK_NORMALIZED_CACHE_DIR = os.path.join(DATA_DIR, "cache", "derived_runtime", "normalized_benchmarks")


@dataclass(slots=True)
class SummaryPayloadBundle:
    payload: dict[str, Any]
    data_sig: str
    payload_sig: str
    render_mode: str


@dataclass(slots=True)
class AnalysisCategoryDataset:
    category: str
    df: pd.DataFrame
    summary: dict[str, Any]
    title: str
    intro_text: str


@dataclass(slots=True)
class QuotazioniTickerBundle:
    category: str
    ticker: str
    instrument_info: dict[str, Any]
    normalized_series: pd.Series
    benchmark_series: tuple[str, list[pd.Timestamp], list[float]] | None
    purchase_date: "pd.Timestamp | None" = None


@dataclass(slots=True)
class QuotazioniDatasetBundle:
    valid_tickers: list[str]
    info_map: dict[str, dict[str, Any]]
    category_groups: dict[str, list[str]]
    ticker_bundles: list[QuotazioniTickerBundle]
    instrument_flow_index_df: pd.DataFrame
    portfolio_flow_index_series: pd.Series
    category_flow_index_df: pd.DataFrame


def _resolve_dataset_category_codes(settings: dict[str, Any] | None = None) -> list[str]:
    if settings is None:
        return list(ACTIVE_CATEGORY_CODES)
    return list(get_selected_category_codes(settings))


_BENCHMARK_EXPECTED_COVERAGE_DAYS = 1500
"""Sotto questa profondita' (~4,1 anni) una cache benchmark e' sospetta:
_prefetch_benchmark_data chiede sempre period="5y" (~1825gg), quindi uno
storico piu' corto indica quasi certamente un fetch passato troncato
(causa non isolata, es. transiente lato Yahoo), non un ticker davvero
neo-quotato - tutti i benchmark usati qui (indici, ETF, materie prime,
tassi) hanno decenni di storico reale.

Task V-quater (2026-09-05, bug reale confermato dall'utente - "tanti
strumenti con benchmark parziali", persisteva anche dopo il fix
06180f9): period="2y" NON era un fetch troncato per errore, era il
comportamento VOLUTO di yfinance (verificato dal vivo: SHY/AGG/^STOXX50E/
^GSPC/^SP500-15 con period="2y" tornano ESATTAMENTE gli ultimi ~730 giorni
da oggi, mai di piu', anche se il ticker ha decenni di storico reale).
Per uno strumento posseduto da piu' di 2 anni (nel portafoglio reale
dell'utente: XBAE.MI/XBAG.MI/XGIN.MI/XXSC.MI/XDEB.MI/XDEQ.MI/EM13.MI/
FAMAMW.MI, tutti dal 2023) la curva benchmark normalizzata partiva quindi
SEMPRE a meta' grafico per costruzione, non per un bug di refresh - "benchmark
parziale" a ogni apertura, indipendentemente da cache/refresh. Alzato a
period="5y" (verificato dal vivo: SHY/AGG/^STOXX50E/^SP500-15 tornano
davvero ~5 anni pieni, 2021-2026) - copre con margine anche lo strumento
piu' vecchio del portafoglio reale (dal 2023, ~3,3 anni)."""


def _latest_valid_benchmark_date(existing: dict[str, Any]) -> str:
    last_valid = ""
    for raw_date, raw_value in existing.items():
        if raw_value is None or pd.isna(raw_value):
            continue
        raw_date = str(raw_date or "")
        if len(raw_date) == 10 and raw_date > last_valid:
            last_valid = raw_date
    return last_valid


def _earliest_valid_benchmark_date(existing: dict[str, Any]) -> str:
    earliest = ""
    for raw_date, raw_value in existing.items():
        if raw_value is None or pd.isna(raw_value):
            continue
        raw_date = str(raw_date or "")
        if len(raw_date) == 10 and (not earliest or raw_date < earliest):
            earliest = raw_date
    return earliest


def _benchmark_series_looks_degenerate(existing: dict[str, Any]) -> bool:
    """Vero se la serie ha abbastanza punti da aspettarsi una variazione
    reale ma e' PIATTA (un solo valore distinto, es. tutta a 100,0).

    Task V-quattuordecies (2026-09-05, bug reale trovato dall'utente:
    SWDA.MI - e con lui XDEB.MI/XDEQ.MI, tutti col benchmark ^GSPC -
    "senza alcun benchmark"): il benchmark NON mancava - `bench_^GSPC`
    aveva 1800 punti dal 2021 a oggi, tutti letteralmente 100.0. Sul
    grafico una curva costante a 100 si sovrappone esattamente alla linea
    di riferimento orizzontale (`fig.add_hline(y=100)`) - visivamente
    indistinguibile da "nessun benchmark", anche se i dati tecnicamente ci
    sono. Nessuno dei controlli esistenti lo intercettava: la copertura
    (1800 punti, molto oltre la soglia) e la freschezza (ultima data =
    oggi) erano entrambe perfette - il problema e' nei VALORI, mai
    controllati prima d'ora. Tutti gli altri 20 benchmark reali
    dell'utente hanno centinaia di valori distinti: 1 solo valore
    distinto su una serie lunga e' un segnale di corruzione (dati
    normalizzati/segnaposto salvati per errore al posto dei prezzi grezzi
    Yahoo), non un caso legittimo."""
    valori = {
        round(float(v), 6) for v in existing.values()
        if v is not None and not pd.isna(v) and float(v) > 0
    }
    return len(existing) >= 30 and len(valori) <= 1


_BENCHMARK_STALE_SOURCE_THRESHOLD_DAYS = 14


def _benchmark_source_is_stale(existing: dict[str, Any], *, threshold_days: int = _BENCHMARK_STALE_SOURCE_THRESHOLD_DAYS) -> bool:
    """Vero se la sorgente non produce un valore valido da piu' di
    `threshold_days` giorni, nonostante i tentativi di refresh periodici.

    Task V-diciannovesima (2026-09-06): bug reale trovato dall'utente -
    ^GSPE (STOXX Europe 600 Energy, benchmark di ENRG.MI) ha smesso di
    pubblicare quotazioni su Yahoo dopo il 17/07/2026; ^BCOM (Bloomberg
    Commodity, benchmark di XDBC.MI) risulta "possibly delisted" - Yahoo
    non ha piu' alcun dato. In entrambi i casi _benchmark_refresh_state
    continua a segnalare "serve un refresh" ogni volta (corretto, cosi' se
    la sorgente si riprende viene ripresa in automatico), ma nessun
    controllo distingueva "sto ancora aspettando dati recenti" da "questa
    fonte e' morta da settimane, serve smettere di aspettare e considerare
    un'alternativa". Soglia di 14 giorni: abbastanza larga da non scattare
    per normali chiusure di mercato o indici a pubblicazione poco frequente,
    abbastanza stretta da intercettare una sorgente davvero interrotta in
    poche settimane."""
    last_valid_txt = _latest_valid_benchmark_date(existing)
    if not last_valid_txt:
        return False
    try:
        last_valid = pd.Timestamp(last_valid_txt).date()
    except Exception:
        return False
    today = pd.Timestamp.now().date()
    return (today - last_valid).days > threshold_days


def _record_auto_benchmark_fallback(
    master_map: dict[str, Any], tk: str, bench_assignment: Any, to_ticker: str, to_label: str,
) -> bool:
    """Registra in instrument_master[tk] il passaggio automatico a un
    ticker fallback per sorgente ferma/morta. Ritorna True solo se ha
    scritto qualcosa di NUOVO (evita save ripetuti a ogni render quando il
    marcatore e' gia' corretto). Letto poi da
    core.benchmark_registry.resolve_instrument_benchmark (priorita' minore
    di un override manuale utente, maggiore della risoluzione automatica
    pura). `to_ticker`/`to_label` sono passati esplicitamente (non letti da
    bench_assignment.fallback_fetchable_series) perche' Task V-ventunesima
    (2026-09-06) puo' scegliere un'alternativa DIVERSA dal singolo fallback
    "vincente" del motore di risoluzione - vedi _find_alive_family_fallback."""
    entry = master_map.setdefault(tk, {})
    if not isinstance(entry, dict):
        return False
    existing = entry.get("auto_benchmark_fallback")
    to_ticker = str(to_ticker or "").strip()
    from_ticker = str(bench_assignment.ticker or "").strip()
    if (
        isinstance(existing, dict)
        and existing.get("active")
        and existing.get("from_ticker") == from_ticker
        and existing.get("to_ticker") == to_ticker
    ):
        return False
    entry["auto_benchmark_fallback"] = {
        "active": True,
        "from_ticker": from_ticker,
        "from_label": bench_assignment.label,
        "to_ticker": to_ticker,
        "to_label": to_label,
        "since": str(pd.Timestamp.now().date()),
        "reason": f"nessun dato aggiornato da oltre {_BENCHMARK_STALE_SOURCE_THRESHOLD_DAYS} giorni",
    }
    logger.warning(
        "Benchmark %s (%s) fermo da oltre %d giorni: passaggio automatico a %s (%s) per ticker %s",
        from_ticker, bench_assignment.label, _BENCHMARK_STALE_SOURCE_THRESHOLD_DAYS,
        to_ticker, to_label, tk,
    )
    return True


def _find_alive_family_fallback(
    _data: dict[str, Any],
    bench_assignment: Any,
    benchmark_runtime_cache: dict[str, dict[str, Any]],
) -> tuple[str, str] | None:
    """Cerca un'alternativa VIVA nella stessa famiglia di riferimento
    (REFERENCE_FAMILIES) quando anche il fallback "vincente" del motore di
    risoluzione risulta fermo/morto.

    Task V-ventunesima (2026-09-06), caso reale ENRG.MI/XDBC.MI: il motore
    espone un solo fallback (`fallback_fetchable_series`, il migliore per
    tracking storico, non per salute ATTUALE della fonte) - per XDBC.MI e'
    ^BCOM (Bloomberg Commodity, "possibly delisted" su Yahoo), ma la stessa
    famiglia COMMODITY nel catalogo statico (reference_families.py) ha
    anche ^SPGSCI (S&P GSCI, verificato vivo con dati fino a oggi), mai
    esposto perche' storicamente traccia XDBC.MI un po' peggio - non perche'
    sia morto. Qui si prova ogni membro della famiglia, nell'ordine del
    catalogo, e si usa il primo vivo: mai un ticker inventato o un ETF
    proxy, solo membri gia' presenti nel catalogo statico curato a mano."""
    from core.instrument_analysis.reference_families import REFERENCE_FAMILIES

    family = str(bench_assignment.fallback_fetchable_label or "").strip()
    candidates = REFERENCE_FAMILIES.get(family, ())
    tried = {str(bench_assignment.ticker or "").strip(), str(bench_assignment.fallback_fetchable_series or "").strip()}
    for candidate in candidates:
        candidate = str(candidate or "").strip()
        if not candidate or candidate in tried:
            continue
        tried.add(candidate)
        bd = _get_cached_benchmark_data(_data, candidate, benchmark_runtime_cache)
        if not bd:
            try:
                h = yf.Ticker(candidate).history(period="5y")
                if not h.empty:
                    bd = {
                        str(d.date()): float(v)
                        for d, v in h["Close"].items()
                        if v == v and float(v) > 0
                    }
                    if bd:
                        _data.setdefault("benchmark_data", {})[f"bench_{candidate}"] = bd
                        benchmark_runtime_cache[candidate] = bd
            except Exception:
                bd = {}
        if bd and not _benchmark_source_is_stale(bd):
            return candidate, family
    return None


def _benchmark_refresh_state(existing: dict[str, Any]) -> tuple[bool, str]:
    today = pd.Timestamp.now().date()
    needs_refresh = not existing
    last_valid_txt = _latest_valid_benchmark_date(existing) or "n/d"
    if last_valid_txt != "n/d":
        try:
            last_valid = pd.Timestamp(last_valid_txt).date()
            needs_refresh = (today - last_valid).days > 1
        except Exception:
            needs_refresh = True
    if not needs_refresh:
        # Bug reale segnalato dall'utente 2026-09-05: curve benchmark che
        # "spuntano dal nulla" a meta' grafico. Un fetch passato troncato
        # (period="5y" richiesto ma meno ottenuto, es. transiente Yahoo)
        # resta "fresco" per sempre col solo controllo sopra, perche' il merge in
        # _prefetch_benchmark_data aggiunge solo giorni nuovi in avanti,
        # mai quelli mancanti nel passato. Ritenta un fetch pieno se la
        # copertura e' sospettosamente corta - ma solo una volta al
        # giorno (mai se last_valid e' gia' oggi: se il tentativo di oggi
        # non ha allungato la copertura, il ticker probabilmente non ha
        # davvero piu' storico disponibile, non ha senso ritentare piu'
        # volte nello stesso giorno).
        earliest_txt = _earliest_valid_benchmark_date(existing)
        if earliest_txt and last_valid_txt != str(today):
            try:
                earliest = pd.Timestamp(earliest_txt).date()
                if (today - earliest).days < _BENCHMARK_EXPECTED_COVERAGE_DAYS:
                    needs_refresh = True
            except Exception:
                pass
        # Stesso principio, ma per il caso "serie piatta" (vedi
        # _benchmark_series_looks_degenerate): copertura e freschezza
        # possono essere entrambe perfette su dati comunque corrotti (il
        # caso reale, bench_^GSPC, aveva last_valid = OGGI) - a differenza
        # del controllo di copertura sopra, qui NON si salta il retry se
        # last_valid e' gia' oggi: una serie costante e' sempre e comunque
        # un segnale di corruzione, mai un limite legittimo dei dati, per
        # cui ritentare anche piu' volte nello stesso giorno e' corretto
        # (non e' un ticker "senza piu' storico" come nel caso sopra).
        if _benchmark_series_looks_degenerate(existing):
            needs_refresh = True
    return needs_refresh, last_valid_txt


def _prefetch_benchmark_data(data: dict[str, Any], benchmark_tickers: list[str]) -> dict[str, dict[str, Any]]:
    benchmark_data = data.setdefault("benchmark_data", {})
    runtime_cache: dict[str, dict[str, Any]] = {}
    changed = False
    for benchmark_ticker in sorted({str(tk).strip() for tk in benchmark_tickers if str(tk).strip()}):
        existing = benchmark_data.get(f"bench_{benchmark_ticker}", {})
        if not isinstance(existing, dict):
            existing = {}
        needs_refresh, _ = _benchmark_refresh_state(existing)
        if not needs_refresh:
            runtime_cache[benchmark_ticker] = existing
            continue
        try:
            bd = yf.Ticker(benchmark_ticker).history(period="5y")
            if not bd.empty:
                # Task V-diciassettesima (2026-09-06): bug reale trovato dal
                # vivo su bench_^GSPE - yfinance puo' restituire un valore
                # NaN per una singola data anche dentro una risposta "5y"
                # altrimenti sana (riprodotto due volte di fila sullo stesso
                # ticker: una chiamata torna la storia piena fino a oggi,
                # quella subito dopo si ferma settimane prima o porta un NaN
                # per la data odierna - instabilita' lato Yahoo, non
                # dell'app). Senza questo filtro un NaN entrava in `fresh` e
                # con `{**existing, **fresh}` sovrascriveva silenziosamente
                # un valore buono gia' in cache per quella data.
                fresh = {
                    str(d.date()): float(v)
                    for d, v in bd["Close"].items()
                    if v == v and float(v) > 0  # v == v esclude NaN senza importare pandas qui
                }
                merged = {**existing, **fresh}
                benchmark_data[f"bench_{benchmark_ticker}"] = merged
                runtime_cache[benchmark_ticker] = merged
                if merged != existing:
                    changed = True
            else:
                runtime_cache[benchmark_ticker] = existing
        except Exception:
            runtime_cache[benchmark_ticker] = existing
    if changed:
        save_benchmark_data(data)
    return runtime_cache


def _get_cached_benchmark_data(
    data: dict[str, Any],
    benchmark_ticker: str,
    runtime_cache: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if runtime_cache is not None and benchmark_ticker in runtime_cache:
        return runtime_cache[benchmark_ticker]
    benchmark_data = data.setdefault("benchmark_data", {})
    existing = benchmark_data.get(f"bench_{benchmark_ticker}", {})
    if not isinstance(existing, dict):
        existing = {}
    return existing


def _get_runtime_normalized_benchmark_series(
    cache: dict[tuple[str, str, str], tuple[str, list[pd.Timestamp], list[float]] | None],
    data: dict[str, Any],
    benchmark_ticker: str,
    benchmark_label: str,
    benchmark_data: dict[str, Any],
    start_date: pd.Timestamp,
    base_date: pd.Timestamp | None = None,
) -> tuple[str, list[pd.Timestamp], list[float]] | None:
    """`start_date` delimita il range MOSTRATO (sempre l'inizio storico
    completo dello strumento, Task V-diciottesima). `base_date`, quando
    presente, e' la data di ANCORAGGIO a quota 100 - la data di acquisto
    della posizione corrente, cosi' come lo strumento si ribasa a 100 li' -
    senza tagliare il resto della curva benchmark prima/dopo quel punto
    (Task V-ventesima, 2026-09-06, richiesta esplicita dell'utente: "nel
    caso di acquisto il benchmark va reso con origine dalla base 100 al
    momento dell'acquisto", cioe' stesso ancoraggio dello strumento, non
    piu' sempre l'inizio storico)."""
    start_key = str(pd.to_datetime(start_date).date())
    base_key = str(pd.to_datetime(base_date).date()) if base_date is not None else start_key
    cache_key = (benchmark_ticker, start_key, base_key)
    if cache_key in cache:
        return cache[cache_key]
    os.makedirs(_BENCHMARK_NORMALIZED_CACHE_DIR, exist_ok=True)
    benchmark_latest = max(benchmark_data.keys(), default="") if isinstance(benchmark_data, dict) else ""
    # Task V-diciassettesima (2026-09-06): bug reale trovato dall'utente -
    # (points, latest) restava invariato mentre i VALORI della serie benchmark
    # cambiavano sotto (es. una riparazione che sostituisce lo stesso range di
    # date con prezzi diversi, o una finestra momentaneamente incompleta che
    # poi si autoripara mantenendo pero' lo stesso numero di punti e la stessa
    # ultima data) - un pickle persistito con questa firma restava valido per
    # sempre anche con un contenuto ormai stantio. Trovato dal vivo: un
    # pickle per ^GSPE scritto alle 18:45:45 con soli 65 punti (15 apr - 17
    # lug) veniva ancora restituito il giorno dopo nonostante bench_^GSPE su
    # disco avesse gia' 1221 punti fino al 4 settembre - "points"/"latest" del
    # dict COMPLETO coincidevano comunque, la firma non vedeva la differenza.
    # Un hash del contenuto (valori arrotondati, non l'intero dict per
    # velocita') costringe a un rebuild ogni volta che cambia davvero qualcosa.
    content_hash = hashlib.md5(
        ",".join(f"{k}={round(v, 4)}" for k, v in sorted(benchmark_data.items())).encode()
    ).hexdigest()[:12] if isinstance(benchmark_data, dict) else ""
    persist_sig = hashlib.md5(
        json.dumps(
            {
                "ticker": benchmark_ticker,
                "label": benchmark_label,
                "start": start_key,
                "base": base_key,
                "points": len(benchmark_data) if isinstance(benchmark_data, dict) else 0,
                "latest": benchmark_latest,
                "content_hash": content_hash,
            },
            sort_keys=True,
            default=str,
        ).encode()
    ).hexdigest()[:16]
    persist_path = os.path.join(_BENCHMARK_NORMALIZED_CACHE_DIR, f"{benchmark_ticker}_{persist_sig}.pkl")

    def _persist(payload: dict[str, Any]) -> None:
        try:
            pd.to_pickle(payload, persist_path)
            from core.derived_cache_utils import prune_sibling_pkl
            prune_sibling_pkl(_BENCHMARK_NORMALIZED_CACHE_DIR, benchmark_ticker, persist_path)
        except Exception:
            pass

    if os.path.exists(persist_path):
        try:
            persisted = pd.read_pickle(persist_path)
        except Exception:
            persisted = None
        if isinstance(persisted, dict) and persisted.get("cache_key") == cache_key:
            persisted_value = persisted.get("value")
            if persisted_value is None or (
                isinstance(persisted_value, tuple)
                and len(persisted_value) == 3
            ):
                record_render_event(
                    "Quotazioni",
                    "benchmark normalizzato persisted hit",
                    0.0,
                    detail=f"{benchmark_ticker}; start={start_key}; sig={persist_sig}",
                    count=len(persisted_value[1]) if isinstance(persisted_value, tuple) else 0,
                )
                cache[cache_key] = persisted_value
                return persisted_value
    raw_series = get_cached_benchmark_series(data, benchmark_ticker, min_start=start_date)
    if raw_series.empty:
        cache[cache_key] = None
        _persist({"cache_key": cache_key, "value": None})
        return None
    sliced = raw_series[raw_series.index >= pd.to_datetime(start_date)]
    if sliced.empty:
        cache[cache_key] = None
        _persist({"cache_key": cache_key, "value": None})
        return None
    if base_date is not None:
        anchor_slice = sliced[sliced.index >= pd.to_datetime(base_date)]
        base_value = float(anchor_slice.iloc[0]) if not anchor_slice.empty else float(sliced.iloc[0])
    else:
        base_value = float(sliced.iloc[0])
    if base_value == 0 or pd.isna(base_value):
        cache[cache_key] = None
        _persist({"cache_key": cache_key, "value": None})
        return None
    if _benchmark_series_looks_degenerate({str(idx): val for idx, val in sliced.items()}):
        # Task V-sedicesima (2026-09-06): bug reale trovato dall'utente subito
        # dopo il fix V-quindecies - una volta che la figura per-ticker e'
        # diventata benchmark-aware (si ricostruisce quando benchmark_data
        # cambia), un rebuild puo' capitare nell'istante esatto in cui
        # bench_^GSPC e' momentaneamente piatto in memoria (la stessa
        # corruzione mai del tutto isolata in V-quindecies, che il guard di
        # scrittura in _merged_benchmark_cache_payload impedisce di
        # persistere su disco ma non impedisce di essere letta a runtime).
        # Prima di questo controllo, una serie piatta veniva comunque
        # normalizzata (una costante diviso se stessa e' sempre 100.0) e
        # salvata per sempre nella figura cacheata: una linea perfettamente
        # sovrapposta alla hline di riferimento a 100, invisibile ma con la
        # sua voce in legenda (segnalato dall'utente: "si vede solo la
        # scritta della legenda ma il grafico non appare"). Meglio nessun
        # benchmark per questo render (si riprova al prossimo) che una
        # curva-fantasma cacheata in modo permanente.
        cache[cache_key] = None
        _persist({"cache_key": cache_key, "value": None})
        return None
    normalized = sliced.divide(base_value).multiply(100.0)
    chart_series = downsample_for_display(normalized)
    result = (benchmark_label, list(chart_series.index), list(chart_series.values))
    cache[cache_key] = result
    _persist({"cache_key": cache_key, "value": result})
    return result


def _summary_payload_cache_is_valid(payload: Any) -> bool:
    """Evita che una cache parziale lasci la Summary senza metriche base."""
    if not isinstance(payload, dict):
        return False
    required_payload_keys = ("summary_history", "twr", "max_drawdown", "quarterly_returns")
    return not any(key not in payload for key in required_payload_keys)


def summary_figures_cache_is_valid(figures: Any, include_advanced: bool) -> bool:
    """Il grafico history e il drawdown sono il minimo sindacale della Summary."""
    if not isinstance(figures, dict):
        return False
    if figures.get("history") is None or figures.get("drawdown") is None:
        return False
    if include_advanced and (figures.get("rolling_vol") is None or figures.get("rolling_sharpe") is None):
        return False
    return True


def _summary_payload_input_signature(
    *,
    data: dict[str, Any],
    da_frame: pd.DataFrame,
    dfh: pd.DataFrame,
    proventi: list[dict[str, Any]] | None,
) -> str:
    benchmark_data = data.get("benchmark_data", {}) if isinstance(data, dict) else {}
    benchmark_state = {
        str(key): {
            "points": len(value) if isinstance(value, dict) else 0,
            "last": max(value.keys(), default="") if isinstance(value, dict) else "",
        }
        for key, value in sorted((benchmark_data or {}).items())
    }
    da_sig_payload: dict[str, Any] = {"rows": 0, "hash": "empty"}
    if isinstance(da_frame, pd.DataFrame) and not da_frame.empty:
        da_cols = [col for col in ["Ticker", "Tipo", "Quote", "Prezzo", "PMC", "Controvalore", "Costo", "P/L €", "P/L %"] if col in da_frame.columns]
        da_slice = da_frame[da_cols].copy() if da_cols else da_frame.copy()
        da_sig_payload = {
            "rows": len(da_slice),
            "hash": hashlib.md5(da_slice.to_json(orient="split", date_format="iso", default_handler=str).encode()).hexdigest()[:16],
        }
    dfh_sig_payload: dict[str, Any] = {"rows": 0, "hash": "empty"}
    if isinstance(dfh, pd.DataFrame) and not dfh.empty:
        dfh_cols = [col for col in ["Data", "Valore", "Capitale"] if col in dfh.columns]
        dfh_slice = dfh[dfh_cols].copy() if dfh_cols else dfh.copy()
        dfh_sig_payload = {
            "rows": len(dfh_slice),
            "hash": hashlib.md5(dfh_slice.to_json(orient="split", date_format="iso", default_handler=str).encode()).hexdigest()[:16],
        }
    proventi_payload = []
    for item in proventi or []:
        if not isinstance(item, dict):
            continue
        proventi_payload.append({
            "ticker": str(item.get("ticker", "") or ""),
            "data": str(item.get("data", "") or item.get("date", "") or ""),
            "tipo": str(item.get("tipo", "") or item.get("tipo_evento", "") or ""),
            "lordo": item.get("importo_lordo", None),
            "netto": item.get("importo_netto", None),
        })
    payload = {
        "da": da_sig_payload,
        "dfh": dfh_sig_payload,
        "proventi": proventi_payload,
        "benchmark_state": benchmark_state,
    }
    return hashlib.md5(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:16]


def build_summary_dataset_signature(
    *,
    data: dict[str, Any],
    da_frame: pd.DataFrame,
    dfh: pd.DataFrame,
    proventi: list[dict[str, Any]] | None,
    settings: dict[str, Any] | None,
    last_quotes_update: Any,
    logic_version: str,
    charts_settings_sig: str,
) -> str:
    """Firma logica dei dataset derivati Summary.

    Include i contatori base, le impostazioni rilevanti e la versione di logica
    per invalidazioni esplicite e controllate.
    """
    settings = settings or {}
    runtime_ui_settings = get_runtime_ui_settings(settings)
    effective_summary_settings = get_effective_summary_settings(settings)
    relevant_settings = {
        "portfolio_identity": settings.get("portfolio_identity", {}),
        "portfolio_benchmark": settings.get("portfolio_benchmark", {}),
        "reporting_export": settings.get("reporting_export", {}),
        "ui_page_mode": runtime_ui_settings.get("page_mode"),
        "portfolio_objective": settings.get("portfolio_objective", {}),
        "sator_settings": settings.get("sator", {}),
        "ui_summary_include_methodology": effective_summary_settings.get("include_methodology"),
        "ui_summary_include_holdings_table": effective_summary_settings.get("include_holdings_export"),
        "ui_summary_include_benchmark": effective_summary_settings.get("include_benchmark"),
        "ui_summary_layout": effective_summary_settings.get("summary_layout"),
        "ui_show_explanations": effective_summary_settings.get("show_explanations"),
        "ui_summary_show_commentary": effective_summary_settings.get("show_commentary"),
        "ui_summary_show_advanced_metrics": effective_summary_settings.get("show_advanced_metrics"),
        "ui_preferences": settings.get("ui_preferences", {}),
    }
    summary_input_sig = _summary_payload_input_signature(
        data=data,
        da_frame=da_frame,
        dfh=dfh,
        proventi=proventi,
    )
    payload = {
        "settings": relevant_settings,
        "summary_input_sig": summary_input_sig,
        "logic_version": logic_version,
        "chart_settings_sig": str(charts_settings_sig or "n/d"),
    }
    return hashlib.md5(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _build_summary_payload_data(
    data: dict[str, Any],
    da_frame: pd.DataFrame,
    portfolio_df: pd.DataFrame,
    liquidita: float,
    settings: dict[str, Any] | None,
    last_quotes_update: Any,
    proventi: list[dict[str, Any]] | None,
    dfh: pd.DataFrame,
) -> dict[str, Any]:
    return build_portfolio_summary_payload(
        data,
        da_frame,
        settings,
        last_quotes_update,
        proventi,
        dfh=dfh,
        portfolio_df=portfolio_df,
        liquidita=liquidita,
    )


def get_summary_payload_bundle(
    *,
    data: dict[str, Any],
    da_frame: pd.DataFrame,
    portfolio_df: pd.DataFrame,
    liquidita: float,
    settings: dict[str, Any] | None,
    last_quotes_update: Any,
    proventi: list[dict[str, Any]] | None,
    dfh: pd.DataFrame,
    data_sig: str,
    charts_settings_sig: str,
    render_mode: str,
    logic_version: str,
) -> SummaryPayloadBundle:
    """Restituisce il payload condiviso della Summary, senza costruire figure UI."""
    bundle_sig = build_summary_dataset_signature(
        data=data,
        da_frame=da_frame,
        dfh=dfh,
        proventi=proventi,
        settings=settings,
        last_quotes_update=last_quotes_update,
        logic_version=logic_version,
        charts_settings_sig=charts_settings_sig,
    )

    spec = get_cache_artifact_spec("summary.dashboard_payload")
    artifact_sig = build_cache_artifact_signature(
        "summary.dashboard_payload",
        inputs={"bundle_sig": bundle_sig},
    )
    with profile_step("Summary", "load/build summary payload", detail=f"sig={artifact_sig[-24:]}", count=len(dfh)):
        payload_artifact = get_or_build_registered_artifact(
            artifact_id=spec.artifact_id,
            signature=artifact_sig,
            builder=lambda: _build_summary_payload_data(
                data,
                da_frame,
                portfolio_df,
                liquidita,
                settings,
                last_quotes_update,
                proventi,
                dfh,
            ),
            clone_on_read=True,
            disk_codec="pickle",
        )
        payload = payload_artifact.value if _summary_payload_cache_is_valid(payload_artifact.value) else {}

    return SummaryPayloadBundle(
        payload=payload,
        data_sig=data_sig,
        payload_sig=bundle_sig,
        render_mode=render_mode,
    )


def _build_analysis_category_datasets_payload(
    _da: pd.DataFrame,
    _data: dict[str, Any],
    _visible_categories: tuple[str, ...],
) -> list[AnalysisCategoryDataset]:
    category_payloads: list[tuple[str, pd.DataFrame, dict[str, Any], str, str]] = []
    for cat in _visible_categories:
        if cat == "GOV":
            cat_df, cat_summary = build_gov_dashboard_data(_da, _data)
            intro_text = "Vista compatta del comparto GOV: dimensione, peso e risultato aggregato."
        else:
            cat_df, cat_summary = build_category_dashboard_data(_da, cat)
            intro_text = f"Vista compatta del comparto {cat}: peso interno e risultato dei singoli strumenti."
        category_payloads.append((
            cat,
            cat_df,
            cat_summary,
            f"Cruscotto {cat}",
            intro_text,
        ))

    from core.finance import build_tutto_portfolio_dashboard_data
    tutto_df, tutto_summary = build_tutto_portfolio_dashboard_data(_da)
    category_payloads.append((
        "Tutto",
        tutto_df,
        tutto_summary,
        "Portafoglio Completo",
        "Vista aggregata di tutti gli strumenti: allocazione totale e risultato complessivo.",
    ))

    return [
        AnalysisCategoryDataset(
            category=cat,
            df=cat_df,
            summary=cat_summary,
            title=title,
            intro_text=intro_text,
        )
        for cat, cat_df, cat_summary, title, intro_text in category_payloads
    ]


def get_analysis_category_datasets(
    *,
    da: pd.DataFrame,
    data: dict[str, Any],
    data_sig: str,
    settings: dict[str, Any] | None = None,
) -> list[AnalysisCategoryDataset]:
    """Costruisce i dataset condivisi della dashboard categoria per Cruscotti."""
    visible_categories = _resolve_dataset_category_codes(settings)
    category_sig = "|".join(visible_categories)
    effective_sig = f"{data_sig}|cats={category_sig}"
    with profile_step("Cruscotti", "build dashboard categoria datasets", detail=f"sig={effective_sig}", count=len(da) if da is not None else 0):
        return _build_analysis_category_datasets_payload(
            da,
            data,
            tuple(visible_categories),
        )


def _build_quotazioni_category_ticker_bundles_payload(
    category: str,
    _data: dict[str, Any],
    _dh_hist: pd.DataFrame,
    _is_complete_view: bool,
    _include_ticker_detail_charts: bool,
    _closed_tickers: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Dati "ticker detail chart" (serie normalizzata + benchmark) per UNA sola macro-categoria.

    Estratta da _build_quotazioni_dataset_bundle_payload (V5-ROADMAP.md,
    Parte 2, item 2.7): la firma e' scoped alla categoria via
    build_category_data_signature, cosi' un aggiornamento quotazioni su
    ETF non invalida piu' anche i ticker_bundles di GOV/FND/ETC.
    """
    info_map = {s["ticker"]: s for s in _data.get("strumenti", [])}
    _master_map = _data.get("instrument_master", {})
    _master_map = _master_map if isinstance(_master_map, dict) else {}
    _closed_set = frozenset(_closed_tickers) if _closed_tickers else None
    valid_tickers = get_valid_quote_tickers_by_category(_data, _dh_hist, closed_tickers=_closed_set)
    category_tickers = [
        tk for tk in valid_tickers
        if macro_cat(info_map.get(tk, {}).get("tipo", "")) == category
    ]

    ticker_bundles: list[dict[str, Any]] = []
    if not (_is_complete_view and _include_ticker_detail_charts) or not category_tickers:
        return {"category_tickers": category_tickers, "ticker_bundles": ticker_bundles}

    benchmark_runtime_cache: dict[str, dict[str, Any]] = {}
    normalized_benchmark_cache: dict[tuple[str, str], tuple[str, list[pd.Timestamp], list[float]] | None] = {}

    benchmark_tickers = []
    for tk in category_tickers:
        bench_assignment = resolve_instrument_benchmark(
            info_map.get(tk, {}), master_entry=_master_map.get(tk), prefer_master=True,
        )
        if bench_assignment.ticker:
            benchmark_tickers.append(bench_assignment.ticker)
    benchmark_runtime_cache = _prefetch_benchmark_data(_data, benchmark_tickers)

    _positions = calc_positions(_data)
    _position_starts = get_current_position_start_dates(_data, _positions)
    _auto_fallback_changed = [False]

    for tk in category_tickers:
        series = _dh_hist[tk].dropna()
        if len(series) < 1:
            continue
        _purchase_date = _position_starts.get(tk)
        # Task V-diciottesima (2026-09-06): bug reale segnalato dall'utente -
        # per gli strumenti SENZA una data di acquisto sulla posizione
        # corrente, il benchmark copriva sempre l'intero periodo visibile
        # (_bench_start = inizio storico). Per quelli CON una posizione
        # riaperta di recente, _bench_start veniva invece spostato alla data
        # di riapertura, tagliando fuori tutto il resto: su un grafico che
        # copre anni, un benchmark di poche settimane risulta impercettibile
        # (segnalato come "il benchmark non appare"). _bench_start ora resta
        # sempre l'inizio storico completo, per coerenza col caso senza
        # acquisto: solo il prezzo base dello strumento (non il benchmark)
        # si ribasa alla data di acquisto, cosi' la curva propria continua a
        # leggersi come "rendimento % da quando ho comprato" mentre il
        # benchmark resta confrontabile sull'intero arco storico (la linea
        # verticale tratteggiata "Acquisto" gia' presente nel grafico segna
        # comunque dove inizia la posizione attuale).
        _bench_start = series.index[0]
        # Task V-ventesima (2026-09-06): richiesta esplicita dell'utente -
        # quando esiste una data di acquisto, il benchmark deve avere lo
        # STESSO ancoraggio a 100 dello strumento (non piu' sempre l'inizio
        # storico come base): _bench_base_date porta questo ancoraggio a
        # _get_runtime_normalized_benchmark_series, che continua pero' a
        # mostrare l'intera curva da _bench_start (V-diciottesima resta
        # valido: il range visibile non si accorcia).
        _bench_base_date = None
        if _purchase_date is not None:
            _from_purchase = series.loc[series.index >= _purchase_date]
            if not _from_purchase.empty:
                _base_price = float(_from_purchase.iloc[0])
                norm = (series / _base_price) * 100
                _bench_base_date = _from_purchase.index[0]
            else:
                norm = (series / series.iloc[0]) * 100
        else:
            norm = (series / series.iloc[0]) * 100
        benchmark_series = None
        bench_assignment = resolve_instrument_benchmark(
            info_map.get(tk, {}), master_entry=_master_map.get(tk), prefer_master=True,
        )
        if bench_assignment.ticker:
            bd = _get_cached_benchmark_data(_data, bench_assignment.ticker, benchmark_runtime_cache)
            # Task V-diciannovesima (2026-09-06): controllo periodico
            # richiesto dall'utente - se la sorgente e' ferma da settimane
            # (vedi _benchmark_source_is_stale) ED esiste gia' un'alternativa
            # ufficiale nota nel motore di risoluzione (fallback_fetchable_series,
            # diversa dal ticker corrente), e quell'alternativa e' a sua volta
            # sana, si registra il passaggio automatico per il prossimo giro
            # (letto da resolve_instrument_benchmark). Nessuna scelta
            # "inventata": solo alternative gia' presenti nell'archivio del
            # motore di risoluzione, mai un ETF proxy improvvisato.
            if _benchmark_source_is_stale(bd):
                fallback_ticker = str(bench_assignment.fallback_fetchable_series or "").strip()
                effective_to: tuple[str, str] | None = None
                if fallback_ticker and fallback_ticker != bench_assignment.ticker:
                    fallback_bd = _get_cached_benchmark_data(_data, fallback_ticker, benchmark_runtime_cache)
                    if fallback_bd and not _benchmark_source_is_stale(fallback_bd):
                        effective_to = (fallback_ticker, bench_assignment.fallback_fetchable_label)
                if effective_to is None:
                    # Task V-ventunesima: il fallback "vincente" e' anch'esso
                    # fermo (o non esiste) - prova gli altri membri noti
                    # della stessa famiglia (es. ^SPGSCI per COMMODITY,
                    # ^GSPC per ENERGY) prima di arrendersi.
                    effective_to = _find_alive_family_fallback(_data, bench_assignment, benchmark_runtime_cache)
                if effective_to is not None:
                    if _record_auto_benchmark_fallback(_master_map, tk, bench_assignment, *effective_to):
                        _auto_fallback_changed[0] = True
            benchmark_series = _get_runtime_normalized_benchmark_series(
                normalized_benchmark_cache,
                _data,
                bench_assignment.ticker,
                bench_assignment.label,
                bd,
                _bench_start,
                base_date=_bench_base_date,
            )
        ticker_bundles.append({
            "category": category,
            "ticker": tk,
            "instrument_info": info_map.get(tk, {}),
            "normalized_series": norm,
            "benchmark_series": benchmark_series,
            "purchase_date": _purchase_date,
        })

    if _auto_fallback_changed[0]:
        _data["instrument_master"] = _master_map
        save_data(_data, include_storico=False)
        # _find_alive_family_fallback puo' aver scaricato e messo in
        # memoria un nuovo ticker candidato (es. ^SPGSCI): save_data non
        # tocca benchmark_data (file separato), va salvato anche qui.
        save_benchmark_data(_data)

    return {"category_tickers": category_tickers, "ticker_bundles": ticker_bundles}


def _build_quotazioni_dataset_bundle_payload(
    _data: dict[str, Any],
    _dh_hist: pd.DataFrame,
    _dh_flow: pd.DataFrame,
    _visible_categories: tuple[str, ...],
    _is_complete_view: bool,
    _include_ticker_detail_charts: bool,
    _include_instrument_flow_chart: bool,
    _closed_tickers: tuple[str, ...] = (),
) -> dict[str, Any]:
    info_map = {s["ticker"]: s for s in _data.get("strumenti", [])}
    _closed_set = frozenset(_closed_tickers) if _closed_tickers else None
    valid_tickers = get_valid_quote_tickers_by_category(_data, _dh_hist, closed_tickers=_closed_set)

    category_groups: dict[str, list[str]] = {}
    for tk in valid_tickers:
        cat = macro_cat(info_map.get(tk, {}).get("tipo", ""))
        if cat in _visible_categories:
            category_groups.setdefault(cat, []).append(tk)

    ticker_bundles: list[QuotazioniTickerBundle] = []

    cat_groups = {}
    for tk in valid_tickers:
        cat = macro_cat(info_map.get(tk, {}).get("tipo", ""))
        if cat in _visible_categories:
            cat_groups.setdefault(cat, []).append(tk)

    instrument_flow_index_df = pd.DataFrame()
    portfolio_flow_index_series = pd.Series(dtype=float)
    category_flow_index_df = pd.DataFrame()
    if _is_complete_view and _include_instrument_flow_chart:
        instrument_key_map = {f"__ticker__:{tk}": [tk] for tk in valid_tickers}
        portfolio_key = "__portfolio__"
        combined_group_map = {**instrument_key_map, portfolio_key: valid_tickers, **cat_groups}
        combined_index_df, combined_returns_df, combined_values_df, combined_flows_df = build_group_cashflow_indices(_data, _dh_flow, combined_group_map)
        if not combined_index_df.empty:
            instrument_columns = [key for key in instrument_key_map if key in combined_index_df.columns]
            if portfolio_key in combined_index_df.columns:
                portfolio_flow_index_series = combined_index_df[portfolio_key].dropna()
            category_columns = [key for key in cat_groups if key in combined_index_df.columns]
            instrument_value_columns = [key for key in instrument_key_map if key in combined_values_df.columns]
            category_value_columns = [key for key in cat_groups if key in combined_values_df.columns]
            if instrument_columns:
                instrument_flow_index_df = combined_index_df[instrument_columns].rename(
                    columns={key: key.replace("__ticker__:", "", 1) for key in instrument_columns}
                )
                instrument_returns_df = combined_returns_df[instrument_columns].rename(
                    columns={key: key.replace("__ticker__:", "", 1) for key in instrument_columns}
                )
                instrument_values_df = combined_values_df[instrument_value_columns].rename(
                    columns={key: key.replace("__ticker__:", "", 1) for key in instrument_value_columns}
                )
                instrument_flows_df = combined_flows_df[instrument_value_columns].rename(
                    columns={key: key.replace("__ticker__:", "", 1) for key in instrument_value_columns}
                )
                seed_group_cashflow_indices_cache(
                    _data,
                    _dh_flow,
                    {tk: [tk] for tk in valid_tickers},
                    (instrument_flow_index_df, instrument_returns_df, instrument_values_df, instrument_flows_df),
                )
            if category_columns:
                category_flow_index_df = combined_index_df[category_columns]
                seed_group_cashflow_indices_cache(
                    _data,
                    _dh_flow,
                    cat_groups,
                    (
                        category_flow_index_df,
                        combined_returns_df[category_columns],
                        combined_values_df[category_value_columns],
                        combined_flows_df[category_value_columns],
                    ),
                )
    elif cat_groups:
        category_flow_index_df, _, _, _ = build_group_cashflow_indices(_data, _dh_flow, cat_groups)

    return {
        "valid_tickers": valid_tickers,
        "info_map": info_map,
        "category_groups": category_groups,
        "ticker_bundles": [],
        "instrument_flow_index_df": instrument_flow_index_df,
        "portfolio_flow_index_series": portfolio_flow_index_series,
        "category_flow_index_df": category_flow_index_df,
    }


def get_quotazioni_dataset_bundle(
    *,
    data: dict[str, Any],
    dh_hist: pd.DataFrame,
    dh_flow: pd.DataFrame,
    is_complete_view: bool,
    include_ticker_detail_charts: bool,
    include_instrument_flow_chart: bool,
    quotes_data_sig: str,
    flow_data_sig: str,
    settings: dict[str, Any] | None = None,
    closed_tickers: tuple[str, ...] = (),
    app_version: str = "n/d",
    schema_version: str = "n/d",
) -> QuotazioniDatasetBundle:
    """Bundle shared per la pagina Quotazioni."""
    visible_categories = _resolve_dataset_category_codes(settings)
    category_sig = "|".join(visible_categories)
    closed_tickers_sig = "|".join(sorted(closed_tickers)) if closed_tickers else ""
    bundle_sig = (
        f"v3|quotes={quotes_data_sig}|flow={flow_data_sig}|complete={int(bool(is_complete_view))}"
        f"|ticker_details={int(bool(include_ticker_detail_charts))}"
        f"|instrument_flow={int(bool(include_instrument_flow_chart))}"
        f"|cats={category_sig}|closed={closed_tickers_sig}"
    )
    bundle_spec = get_cache_artifact_spec("quotazioni.dataset_bundle")
    bundle_artifact_sig = build_cache_artifact_signature(
        "quotazioni.dataset_bundle",
        inputs={"bundle_sig": bundle_sig},
    )
    with profile_step("Quotazioni", "load/build cached bundle shared", detail=f"sig={bundle_sig}", count=len(getattr(dh_hist, "columns", []))):
        cached_bundle_artifact = get_or_build_registered_artifact(
            artifact_id=bundle_spec.artifact_id,
            signature=bundle_artifact_sig,
            builder=lambda: _build_quotazioni_dataset_bundle_payload(
                data,
                dh_hist,
                dh_flow,
                tuple(visible_categories),
                bool(is_complete_view),
                bool(include_ticker_detail_charts),
                bool(include_instrument_flow_chart),
                tuple(closed_tickers),
            ),
            clone_on_read=False,
            disk_codec="pickle",
        )
        cached_bundle = cached_bundle_artifact.value
        record_render_event(
            "Quotazioni",
            "cached bundle shared source",
            0.0,
            detail=f"source={cached_bundle_artifact.source}; sig={bundle_artifact_sig}",
            count=len(getattr(dh_hist, "columns", [])),
        )

    merged_ticker_bundles: list[dict[str, Any]] = []
    category_ticker_spec = get_cache_artifact_spec("quotazioni.category_ticker_bundles")
    for category in visible_categories:
        cat_sig = build_category_data_signature(
            data, category, app_version=app_version, schema_version=schema_version,
            # I grafici per-ticker (benchmark incluso) esistono solo quando
            # is_complete_view+include_ticker_detail_charts sono entrambi veri
            # (vedi early-return in _build_quotazioni_category_ticker_bundles_payload)
            # - il costo di un hash piu' ampio va pagato solo quando serve davvero.
            include_benchmark_data=bool(is_complete_view and include_ticker_detail_charts),
        )
        category_bundle_sig = (
            f"v1|cat={category}|catsig={cat_sig}"
            f"|complete={int(bool(is_complete_view))}"
            f"|ticker_details={int(bool(include_ticker_detail_charts))}"
            f"|closed={closed_tickers_sig}"
        )
        category_artifact_sig = build_cache_artifact_signature(
            "quotazioni.category_ticker_bundles",
            inputs={"category_bundle_sig": category_bundle_sig},
        )
        with profile_step("Quotazioni", "load/build ticker_bundles categoria", detail=f"cat={category}|sig={category_artifact_sig[-24:]}"):
            cached_category_artifact = get_or_build_registered_artifact(
                artifact_id=category_ticker_spec.artifact_id,
                signature=category_artifact_sig,
                builder=lambda current_category=category: _build_quotazioni_category_ticker_bundles_payload(
                    current_category,
                    data,
                    dh_hist,
                    bool(is_complete_view),
                    bool(include_ticker_detail_charts),
                    tuple(closed_tickers),
                ),
                clone_on_read=False,
                disk_codec="pickle",
            )
            cached_category = cached_category_artifact.value if isinstance(cached_category_artifact.value, dict) else {}
        merged_ticker_bundles.extend(cached_category.get("ticker_bundles", []) or [])

    return QuotazioniDatasetBundle(
        valid_tickers=list(cached_bundle.get("valid_tickers", []) or []),
        info_map=dict(cached_bundle.get("info_map", {}) or {}),
        category_groups=dict(cached_bundle.get("category_groups", {}) or {}),
        ticker_bundles=[
            QuotazioniTickerBundle(
                category=str(item.get("category", "") or ""),
                ticker=str(item.get("ticker", "") or ""),
                instrument_info=dict(item.get("instrument_info", {}) or {}),
                normalized_series=item.get("normalized_series"),
                benchmark_series=item.get("benchmark_series"),
                purchase_date=item.get("purchase_date"),
            )
            for item in merged_ticker_bundles
        ],
        instrument_flow_index_df=cached_bundle.get("instrument_flow_index_df", pd.DataFrame()),
        portfolio_flow_index_series=cached_bundle.get("portfolio_flow_index_series", pd.Series(dtype=float)),
        category_flow_index_df=cached_bundle.get("category_flow_index_df", pd.DataFrame()),
    )
