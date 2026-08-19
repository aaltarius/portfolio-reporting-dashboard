"""Confronto multi-strumento normalizzato per Pianificazione: estrae serie
da storico_prezzi/benchmark_data, allinea le date, normalizza con
core.domain.returns.normalize_to_first, risolve opzionalmente il benchmark
di un singolo strumento tramite core.benchmark_registry.

Non fa rendering (nessun plotly qui): produce ComparisonSeries pronte per
ui/charts/pianificazione.py::build_instrument_comparison_chart.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date as _date
from typing import Any

import pandas as pd
from dateutil.relativedelta import relativedelta

from core.benchmark_registry import resolve_instrument_benchmark
from core.domain.positions import held_tickers
from core.domain.returns import normalize_to_first
from core.services.benchmark import benchmark_price_history, instrument_price_history
from persistence.storage import macro_cat


@dataclass(frozen=True)
class ComparisonSeries:
    ticker: str
    label: str
    dates: list[str]
    values: list[float]
    is_benchmark: bool = False
    # True se il ticker e' attualmente posseduto (held_tickers), False se lo
    # storico e' solo osservato/non piu' in portafoglio. Irrilevante per le
    # serie benchmark (is_benchmark=True), che hanno il proprio stile fisso
    # indipendentemente da questo flag — vedi build_instrument_comparison_chart.
    is_held: bool = True


_PERIOD_DELTAS: dict[str, relativedelta | None] = {
    "1M": relativedelta(months=1),
    "3M": relativedelta(months=3),
    "6M": relativedelta(months=6),
    "1A": relativedelta(years=1),
    "3A": relativedelta(years=3),
    "Tutto": None,
}


def resolve_period_start_date(sorted_dates: list[str], period: str) -> str:
    """Calcola la start_date sottraendo il periodo dalla data piu' recente
    nello storico. Spostata qui da ui/charts/benchmark.py insieme al resto
    della sezione "Confronto strumenti"."""
    if not sorted_dates:
        return ""
    first = sorted_dates[0][:10]
    last = sorted_dates[-1][:10]
    delta = _PERIOD_DELTAS.get(period)
    if delta is None:
        return first
    ref = _date.fromisoformat(last) - delta
    computed = ref.strftime("%Y-%m-%d")
    return computed if computed >= first else first


def get_all_historical_tickers(
    data: dict[str, Any], *, exclude_tickers: frozenset[str] = frozenset()
) -> list[dict[str, Any]]:
    """Ritorna tutti i ticker mai presenti in storico_prezzi, con flag
    active = "possiedo quote ora" (da held_tickers, non dal campo stato).

    exclude_tickers: ticker omessi del tutto dalle opzioni selezionabili nel
    Confronto strumenti (toggle "Escludi BTP/GOV" della pagina Pianificazione)."""
    storico: dict[str, dict[str, float]] = data.get("storico_prezzi") or {}
    active_set = held_tickers(data)
    all_tickers: set[str] = set()
    for prices in storico.values():
        all_tickers.update(prices.keys())
    return [
        {"ticker": tk, "active": tk in active_set}
        for tk in sorted(all_tickers)
        if tk not in exclude_tickers
    ]


def _normalized_series(
    price_df: pd.DataFrame, price_col: str, *, start_date: str | None, align_starts: bool
) -> tuple[list[str], list[float]] | None:
    if price_df is None or price_df.empty:
        return None
    df = price_df.copy()
    if not align_starts and start_date:
        df = df[df["date"] >= pd.to_datetime(start_date)]
    if df.empty:
        return None
    normalized = normalize_to_first(df[price_col].reset_index(drop=True), as_pct=True)
    if normalized.empty:
        return None
    dates = (
        [str(i) for i in range(len(normalized))]
        if align_starts
        else df["date"].dt.strftime("%Y-%m-%d").tolist()
    )
    return dates, normalized.tolist()


def build_comparison_frame(
    data: dict[str, Any],
    tickers: list[str],
    *,
    start_date: str | None = None,
    align_starts: bool = False,
    benchmark_for: str | None = None,
    exclude_tickers: frozenset[str] = frozenset(),
) -> list[ComparisonSeries]:
    """Costruisce le serie normalizzate per il confronto multi-strumento di
    Pianificazione, con overlay opzionale del benchmark assegnato a un
    singolo strumento (benchmark_for).

    exclude_tickers: filtro difensivo (toggle "Escludi BTP/GOV" della pagina
    Pianificazione) - le opzioni selezionabili sono gia' filtrate a monte da
    get_all_historical_tickers, questo e' un secondo filtro sulla stessa
    fonte nel caso `tickers` contenga comunque un ticker escluso."""
    result: list[ComparisonSeries] = []
    # Stesso segnale "active" gia' calcolato da get_all_historical_tickers
    # (held_tickers da core.domain.positions): non reimplementarlo qui.
    active_set = held_tickers(data)
    for ticker in tickers:
        if ticker in exclude_tickers:
            continue
        price_df = instrument_price_history(data, ticker)
        series = _normalized_series(price_df, "strumento", start_date=start_date, align_starts=align_starts)
        if series is None:
            continue
        dates, values = series
        result.append(
            ComparisonSeries(
                ticker=ticker, label=ticker, dates=dates, values=values, is_held=ticker in active_set,
            )
        )

    if benchmark_for:
        instrument = next(
            (s for s in (data.get("strumenti") or []) if str(s.get("ticker") or "") == benchmark_for),
            None,
        )
        if instrument is not None:
            raw_type = str(instrument.get("tipo") or "")
            master_all = data.get("instrument_master", {})
            master_all = master_all if isinstance(master_all, dict) else {}
            master_entry = master_all.get(benchmark_for)
            assignment = resolve_instrument_benchmark(
                instrument, raw_type=raw_type, category=macro_cat(raw_type),
                master_entry=master_entry, prefer_master=True,
            )
            if assignment.has_benchmark:
                bench_df = benchmark_price_history(data, assignment.ticker)
                bench_series = _normalized_series(
                    bench_df, "benchmark", start_date=start_date, align_starts=align_starts
                )
                if bench_series is not None:
                    bench_dates, bench_values = bench_series
                    result.append(
                        ComparisonSeries(
                            ticker=assignment.ticker,
                            label=f"{assignment.label} (benchmark)",
                            dates=bench_dates,
                            values=bench_values,
                            is_benchmark=True,
                        )
                    )
    return result
