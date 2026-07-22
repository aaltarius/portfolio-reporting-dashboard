"""Dataset condivisi per le pagine dashboard.

Primo step del refactor centralizzato:
- separa i dati raw dalle derivazioni condivise
- concentra firme/cache di payload e figure fuori dalle pagine UI
- offre un punto unico di invalidazione e osservazione
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any

import pandas as pd
import streamlit as st

from core.asset_categories import ACTIVE_CATEGORY_CODES, get_selected_category_codes
from core.cashflow_indices import build_group_cashflow_indices, seed_group_cashflow_indices_cache
from core.settings_profiles import get_effective_summary_settings, get_runtime_ui_settings
from core.services import get_valid_quote_tickers_by_category
from core.finance import build_category_dashboard_data, build_gov_dashboard_data
from core.finance import build_portfolio_summary_payload, get_cached_benchmark_series, calc_positions
from core.series_utils import get_current_position_start_dates
from core.series_resample import downsample_for_display
from core.render_profiler import profile_step, record_render_event
from persistence.storage import DATA_DIR, macro_cat, save_benchmark_data
from core.benchmark_registry import resolve_instrument_benchmark
import yfinance as yf

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
    category_flow_index_df: pd.DataFrame


def _resolve_dataset_category_codes(settings: dict[str, Any] | None = None) -> list[str]:
    if settings is None:
        return list(ACTIVE_CATEGORY_CODES)
    return list(get_selected_category_codes(settings))


def _latest_valid_benchmark_date(existing: dict[str, Any]) -> str:
    last_valid = ""
    for raw_date, raw_value in existing.items():
        if raw_value is None or pd.isna(raw_value):
            continue
        raw_date = str(raw_date or "")
        if len(raw_date) == 10 and raw_date > last_valid:
            last_valid = raw_date
    return last_valid


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
            bd = yf.Ticker(benchmark_ticker).history(period="2y")
            if not bd.empty:
                fresh = {str(d.date()): float(v) for d, v in bd["Close"].items()}
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
    cache: dict[tuple[str, str], tuple[str, list[pd.Timestamp], list[float]] | None],
    data: dict[str, Any],
    benchmark_ticker: str,
    benchmark_label: str,
    benchmark_data: dict[str, Any],
    start_date: pd.Timestamp,
) -> tuple[str, list[pd.Timestamp], list[float]] | None:
    start_key = str(pd.to_datetime(start_date).date())
    cache_key = (benchmark_ticker, start_key)
    if cache_key in cache:
        return cache[cache_key]
    os.makedirs(_BENCHMARK_NORMALIZED_CACHE_DIR, exist_ok=True)
    benchmark_latest = max(benchmark_data.keys(), default="") if isinstance(benchmark_data, dict) else ""
    persist_sig = hashlib.md5(
        json.dumps(
            {
                "ticker": benchmark_ticker,
                "label": benchmark_label,
                "start": start_key,
                "points": len(benchmark_data) if isinstance(benchmark_data, dict) else 0,
                "latest": benchmark_latest,
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
    base_value = float(sliced.iloc[0])
    if base_value == 0 or pd.isna(base_value):
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


@st.cache_data(show_spinner=False, persist="disk")
def _build_summary_payload_cached(
    bundle_sig: str,
    _data: dict[str, Any],
    _da_frame: pd.DataFrame,
    _portfolio_df: pd.DataFrame,
    _liquidita: float,
    _settings: dict[str, Any] | None,
    _last_quotes_update: Any,
    _proventi: list[dict[str, Any]] | None,
    _dfh: pd.DataFrame,
) -> dict[str, Any]:
    _ = bundle_sig
    return build_portfolio_summary_payload(
        _data,
        _da_frame,
        _settings,
        _last_quotes_update,
        _proventi,
        dfh=_dfh,
        portfolio_df=_portfolio_df,
        liquidita=_liquidita,
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

    payload_key = "dashboard_datasets.summary.payload"
    payload_sig_key = "dashboard_datasets.summary.payload_sig"

    cached_payload = st.session_state.get(payload_key)
    must_rebuild_payload = (
        st.session_state.get(payload_sig_key) != bundle_sig
        or not _summary_payload_cache_is_valid(cached_payload)
    )
    if must_rebuild_payload:
        with profile_step("Summary", "load/build cached payload", detail=f"sig={bundle_sig}", count=len(dfh)):
            payload = _build_summary_payload_cached(
                bundle_sig,
                data,
                da_frame,
                portfolio_df,
                liquidita,
                settings,
                last_quotes_update,
                proventi,
                dfh,
            )
        st.session_state[payload_key] = payload
        st.session_state[payload_sig_key] = bundle_sig
        for key in (
            "dashboard_datasets.summary.figures.fast",
            "dashboard_datasets.summary.figures.complete",
            "dashboard_datasets.summary.figures_sig.fast",
            "dashboard_datasets.summary.figures_sig.complete",
        ):
            st.session_state.pop(key, None)
    else:
        with profile_step("Summary", "cache hit payload", detail=f"sig={bundle_sig}"):
            payload = cached_payload

    return SummaryPayloadBundle(
        payload=payload,
        data_sig=data_sig,
        payload_sig=bundle_sig,
        render_mode=render_mode,
    )


@st.cache_data(show_spinner=False, persist="disk")
def _build_analysis_category_datasets_cached(
    effective_sig: str,
    _da: pd.DataFrame,
    _data: dict[str, Any],
    _visible_categories: tuple[str, ...],
) -> list[AnalysisCategoryDataset]:
    _ = effective_sig
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
    with profile_step("Cruscotti", "load/build cached dashboard categoria", detail=f"sig={effective_sig}", count=len(da) if da is not None else 0):
        return _build_analysis_category_datasets_cached(
            effective_sig,
            da,
            data,
            tuple(visible_categories),
        )


@st.cache_data(show_spinner=False, persist="disk")
def _build_quotazioni_dataset_bundle_cached(
    bundle_sig: str,
    _data: dict[str, Any],
    _dh_hist: pd.DataFrame,
    _dh_flow: pd.DataFrame,
    _visible_categories: tuple[str, ...],
    _is_complete_view: bool,
    _include_ticker_detail_charts: bool,
    _include_instrument_flow_chart: bool,
    _closed_tickers: tuple[str, ...] = (),
) -> dict[str, Any]:
    _ = bundle_sig
    info_map = {s["ticker"]: s for s in _data.get("strumenti", [])}
    _closed_set = frozenset(_closed_tickers) if _closed_tickers else None
    valid_tickers = get_valid_quote_tickers_by_category(_data, _dh_hist, closed_tickers=_closed_set)

    category_groups: dict[str, list[str]] = {}
    for tk in valid_tickers:
        cat = macro_cat(info_map.get(tk, {}).get("tipo", ""))
        if cat in _visible_categories:
            category_groups.setdefault(cat, []).append(tk)

    benchmark_runtime_cache: dict[str, dict[str, Any]] = {}
    normalized_benchmark_cache: dict[tuple[str, str], tuple[str, list[pd.Timestamp], list[float]] | None] = {}
    ticker_bundles: list[QuotazioniTickerBundle] = []

    if _is_complete_view and _include_ticker_detail_charts:
        benchmark_tickers = []
        for tk in valid_tickers:
            bench_assignment = resolve_instrument_benchmark(info_map.get(tk, {}), prefer_master=False)
            bench_ticker = bench_assignment.ticker
            if bench_ticker:
                benchmark_tickers.append(bench_ticker)
        benchmark_runtime_cache = _prefetch_benchmark_data(_data, benchmark_tickers)

        # Data di primo acquisto per ogni strumento in portafoglio
        _positions = calc_positions(_data)
        _position_starts = get_current_position_start_dates(_data, _positions)

        for category in _visible_categories:
            for tk in category_groups.get(category, []):
                series = _dh_hist[tk].dropna()
                if len(series) < 1:
                    continue
                # Option B: serie completa normalizzata al prezzo di acquisto.
                # Se lo strumento non è in portafoglio usa iloc[0] (comportamento originale).
                _purchase_date = _position_starts.get(tk)
                _bench_start = series.index[0]
                if _purchase_date is not None:
                    _from_purchase = series.loc[series.index >= _purchase_date]
                    if not _from_purchase.empty:
                        _base_price = float(_from_purchase.iloc[0])
                        norm = (series / _base_price) * 100
                        _bench_start = _from_purchase.index[0]
                    else:
                        norm = (series / series.iloc[0]) * 100
                else:
                    norm = (series / series.iloc[0]) * 100
                benchmark_series = None
                bench_assignment = resolve_instrument_benchmark(info_map.get(tk, {}), prefer_master=False)
                if bench_assignment.ticker:
                    bd = _get_cached_benchmark_data(_data, bench_assignment.ticker, benchmark_runtime_cache)
                    benchmark_series = _get_runtime_normalized_benchmark_series(
                        normalized_benchmark_cache,
                        _data,
                        bench_assignment.ticker,
                        bench_assignment.label,
                        bd,
                        _bench_start,
                    )
                ticker_bundles.append(
                    QuotazioniTickerBundle(
                        category=category,
                        ticker=tk,
                        instrument_info=info_map.get(tk, {}),
                        normalized_series=norm,
                        benchmark_series=benchmark_series,
                        purchase_date=_purchase_date,
                    )
                )

    cat_groups = {}
    for tk in valid_tickers:
        cat = macro_cat(info_map.get(tk, {}).get("tipo", ""))
        if cat in _visible_categories:
            cat_groups.setdefault(cat, []).append(tk)

    instrument_flow_index_df = pd.DataFrame()
    category_flow_index_df = pd.DataFrame()
    if _is_complete_view and _include_instrument_flow_chart:
        instrument_key_map = {f"__ticker__:{tk}": [tk] for tk in valid_tickers}
        combined_group_map = {**instrument_key_map, **cat_groups}
        combined_index_df, combined_returns_df, combined_values_df, combined_flows_df = build_group_cashflow_indices(_data, _dh_flow, combined_group_map)
        if not combined_index_df.empty:
            instrument_columns = [key for key in instrument_key_map if key in combined_index_df.columns]
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
        "ticker_bundles": [
            {
                "category": item.category,
                "ticker": item.ticker,
                "instrument_info": item.instrument_info,
                "normalized_series": item.normalized_series,
                "benchmark_series": item.benchmark_series,
                "purchase_date": item.purchase_date,
            }
            for item in ticker_bundles
        ],
        "instrument_flow_index_df": instrument_flow_index_df,
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
) -> QuotazioniDatasetBundle:
    """Bundle shared per la pagina Quotazioni."""
    visible_categories = _resolve_dataset_category_codes(settings)
    category_sig = "|".join(visible_categories)
    closed_tickers_sig = "|".join(sorted(closed_tickers)) if closed_tickers else ""
    bundle_sig = (
        f"v2|quotes={quotes_data_sig}|flow={flow_data_sig}|complete={int(bool(is_complete_view))}"
        f"|ticker_details={int(bool(include_ticker_detail_charts))}"
        f"|instrument_flow={int(bool(include_instrument_flow_chart))}"
        f"|cats={category_sig}|closed={closed_tickers_sig}"
    )
    with profile_step("Quotazioni", "load/build cached bundle shared", detail=f"sig={bundle_sig}", count=len(getattr(dh_hist, "columns", []))):
        cached_bundle = _build_quotazioni_dataset_bundle_cached(
            bundle_sig,
            data,
            dh_hist,
            dh_flow,
            tuple(visible_categories),
            bool(is_complete_view),
            bool(include_ticker_detail_charts),
            bool(include_instrument_flow_chart),
            tuple(closed_tickers),
        )
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
            for item in list(cached_bundle.get("ticker_bundles", []) or [])
        ],
        instrument_flow_index_df=cached_bundle.get("instrument_flow_index_df", pd.DataFrame()),
        category_flow_index_df=cached_bundle.get("category_flow_index_df", pd.DataFrame()),
    )
