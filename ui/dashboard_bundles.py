from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import hashlib
import json

import numpy as np
import pandas as pd
import streamlit as st

from core.asset_categories import get_selected_category_codes
from core.cache_policy import build_cache_artifact_signature, get_cache_artifact_spec
from core.cache_orchestrator import get_or_build_registered_artifact
from core.dashboard_datasets import (
    AnalysisCategoryDataset,
    SummaryPayloadBundle,
    get_analysis_category_datasets,
    get_summary_payload_bundle,
    summary_figures_cache_is_valid,
)
from core.cache_signatures import build_category_data_signature
from core.cache_orchestrator import get_registered_figure_cache
from core.render_profiler import profile_step
from core.services import build_advanced_analysis_data, build_category_dashboard_metrics
from ui.charts.analitica import (
    build_asset_allocation_radar,
    build_performance_attribution,
    build_percentage_return_time_chart,
    build_pl_decomposition_time_chart,
    build_portfolio_simulation_chart,
    build_portfolio_value_time_chart,
    build_quality_profile_radar,
    build_risk_contribution_chart,
    build_target_gap_chart,
)
from ui.charts.cruscotti import (
    build_category_capital_pl_pie_chart,
    build_category_instrument_distribution_pie_chart,
    build_category_temporal_dual_axis,
    build_compact_category_dashboard_chart,
    build_category_invested_vs_pl_chart,
)
from ui.charts.summary import build_summary_figures
from ui.charts.runtime import empty_chart
from core.services.sator import compute_instrument_buckets
from core.services.portfolio_simulation import build_portfolio_simulation, PortfolioSimulationResult
from core.services import build_percentage_return_series
from persistence.storage import _safe_float, get_proventi_normalizzati
from ui.theme import macro_color


def _objective_cache_token(objective: dict[str, Any] | None) -> str:
    payload = dict(objective or {})
    digest = hashlib.md5(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:12]
    return digest


@dataclass(slots=True)
class SummaryDatasetBundle:
    payload: dict[str, Any]
    figures: dict[str, Any]
    data_sig: str
    payload_sig: str
    figure_sig: str
    figure_scope: str
    render_mode: str


@dataclass(slots=True)
class AnalysisCategoryDashboardBundle:
    category: str
    df: pd.DataFrame
    summary: dict[str, Any]
    title: str
    intro_text: str
    metrics: list[dict[str, Any]]
    compact_figure: Any
    temporal_figure: Any
    value_pie_figure: Any
    capital_pl_pie_figure: Any
    invested_vs_pl_figure: Any
    drawdown_figure: Any = None
    monthly_returns_figure: Any = None
    pl_horizon_table: pd.DataFrame | None = None


_CATEGORY_PL_HORIZONS: tuple[tuple[str, dict[str, int | bool]], ...] = (
    ("1D", {"rows": 1}),
    ("3D", {"rows": 3}),
    ("5D", {"rows": 5}),
    ("1M", {"months": 1}),
    ("6M", {"months": 6}),
    ("YTD", {"ytd": True}),
    ("1Y", {"years": 1}),
    ("3Y", {"years": 3}),
    ("5Y", {"years": 5}),
)


def _category_horizon_start_date(history_dates: pd.Series, spec: dict[str, int | bool]) -> pd.Timestamp | None:
    if history_dates is None or history_dates.empty:
        return None
    end_date = history_dates.iloc[-1]
    if pd.isna(end_date):
        return None
    if "rows" in spec:
        pos = max(0, len(history_dates) - 1 - int(spec["rows"]))
        return pd.Timestamp(history_dates.iloc[pos])
    if spec.get("ytd"):
        return pd.Timestamp(year=int(end_date.year), month=1, day=1)
    if "months" in spec:
        return pd.Timestamp(end_date) - pd.DateOffset(months=int(spec["months"]))
    if "years" in spec:
        return pd.Timestamp(end_date) - pd.DateOffset(years=int(spec["years"]))
    return pd.Timestamp(history_dates.iloc[0])


def _category_horizon_start_dates(history_dates: pd.Series) -> dict[str, pd.Timestamp | None]:
    """Calcola la data di inizio per ciascun orizzonte una sola volta per
    categoria: non dipende dallo strumento, prima veniva ricalcolata per
    ogni strumento del loop (fino a 17x invece di 1x)."""
    return {label: _category_horizon_start_date(history_dates, spec) for label, spec in _CATEGORY_PL_HORIZONS}


def _pl_delta_from_prepared_frame(frame: pd.DataFrame, start_date: pd.Timestamp | None) -> tuple[float | None, bool]:
    """Come la vecchia _pl_delta_from_series, ma riceve un frame gia'
    convertito/pulito/ordinato (colonne 'Data','P/L') cosi' che il chiamante
    lo prepari una sola volta per strumento invece che una volta per
    ciascuno dei 9 orizzonti."""
    if start_date is None:
        return None, False
    if len(frame) < 2:
        return None, True
    end_value = float(frame["P/L"].iloc[-1])
    first_available_date = pd.Timestamp(frame["Data"].iloc[0])
    is_partial = first_available_date > pd.Timestamp(start_date)
    start_candidates = frame[frame["Data"] >= start_date]
    if start_candidates.empty:
        start_value = float(frame["P/L"].iloc[0])
    else:
        start_value = float(start_candidates["P/L"].iloc[0])
    return end_value - start_value, is_partial


def _build_category_pl_horizon_table(dfh: pd.DataFrame, category_df: pd.DataFrame) -> pd.DataFrame:
    if dfh is None or dfh.empty or category_df is None or category_df.empty:
        return pd.DataFrame()
    if "Data" not in dfh.columns or "Ticker" not in category_df.columns:
        return pd.DataFrame()

    work = dfh.copy()
    work["_Data"] = pd.to_datetime(work["Data"], errors="coerce")
    work = work.dropna(subset=["_Data"]).sort_values("_Data")
    if work.empty:
        return pd.DataFrame()

    horizon_start_dates = _category_horizon_start_dates(work["_Data"])

    tickers = [str(t).strip() for t in category_df["Ticker"].dropna().astype(str).tolist() if str(t).strip()]
    rows: list[dict[str, Any]] = []
    for ticker in tickers:
        pl_col = f"PL_{ticker}"
        if pl_col not in work.columns:
            continue
        frame = pd.DataFrame({
            "Data": work["_Data"],
            "P/L": pd.to_numeric(work[pl_col], errors="coerce"),
        }).dropna(subset=["Data", "P/L"]).sort_values("Data")

        row: dict[str, Any] = {"Ticker": ticker}
        for label, _spec in _CATEGORY_PL_HORIZONS:
            delta, is_partial = _pl_delta_from_prepared_frame(frame, horizon_start_dates[label])
            row[label] = delta
            row[f"_{label}_partial"] = is_partial
        rows.append(row)

    if not rows:
        return pd.DataFrame()

    table = pd.DataFrame(rows)
    horizon_cols = [label for label, _spec in _CATEGORY_PL_HORIZONS]
    sort_col = "3D" if "3D" in table.columns else horizon_cols[0]
    table = table.sort_values(sort_col, na_position="last").reset_index(drop=True)
    total_row: dict[str, Any] = {"Ticker": "TOTALE"}
    for col in horizon_cols:
        total_row[col] = pd.to_numeric(table[col], errors="coerce").sum(min_count=1)
        partial_col = f"_{col}_partial"
        if partial_col in table.columns:
            total_row[partial_col] = bool(table[partial_col].fillna(False).any())
    return pd.concat([table, pd.DataFrame([total_row])], ignore_index=True)


def _combine_category_pl_horizon_tables(tables: list[pd.DataFrame | None]) -> pd.DataFrame:
    """Costruisce la tabella P/L horizon di 'Tutto' sommando le tabelle
    per-categoria gia' calcolate nello stesso giro (GOV/ETF/FND/...),
    invece di ricalcolarla da zero rileggendo lo storico prezzi di ogni
    strumento una seconda volta.

    Sicuro perche' il P/L in euro per orizzonte e' additivo tra categorie
    che partizionano lo stesso universo di strumenti (ogni ticker
    appartiene a UNA sola categoria) - a differenza di drawdown/rendimenti
    mensili (non additivi: dipendono dalla serie storica combinata, non
    dalla somma delle serie per categoria), che restano calcolati
    sull'aggregato reale e non sono toccati da questa ottimizzazione.
    """
    per_ticker_frames = [
        table[table["Ticker"] != "TOTALE"]
        for table in tables
        if table is not None and not table.empty
    ]
    if not per_ticker_frames:
        return pd.DataFrame()

    combined = pd.concat(per_ticker_frames, ignore_index=True)
    horizon_cols = [label for label, _spec in _CATEGORY_PL_HORIZONS]
    sort_col = "3D" if "3D" in combined.columns else horizon_cols[0]
    combined = combined.sort_values(sort_col, na_position="last").reset_index(drop=True)

    total_row: dict[str, Any] = {"Ticker": "TOTALE"}
    for col in horizon_cols:
        total_row[col] = pd.to_numeric(combined[col], errors="coerce").sum(min_count=1)
        partial_col = f"_{col}_partial"
        if partial_col in combined.columns:
            total_row[partial_col] = bool(combined[partial_col].fillna(False).any())
    return pd.concat([combined, pd.DataFrame([total_row])], ignore_index=True)


@dataclass(slots=True)
class AdvancedAnalysisDatasetBundle:
    info_map: dict[str, dict[str, Any]]
    ta: list[str]
    dfstats: pd.DataFrame
    irr_results: dict[str, float | None]
    analysis_returns: pd.DataFrame
    cat_flow_returns: pd.DataFrame
    risk_df: pd.DataFrame
    cat_index_analysis: pd.DataFrame
    corr: pd.DataFrame
    corr_cat: pd.DataFrame


@dataclass(slots=True)
class AnaliticaBundle:
    portfolio_value_figure: Any
    pl_decomposition_figure: Any
    percentage_return_figure: Any
    target_gap_figure: Any
    risk_contribution_figure: Any
    performance_attribution_figure: Any
    asset_allocation_radar_figure: Any
    quality_profile_radar_figure: Any
    radar_payload: dict[str, Any] | None = None
    summary_payload: dict[str, Any] | None = None
    reporting_pack: dict[str, Any] | None = None
    reporting_pack_md: str = ""
    i18n_profile: dict[str, Any] | None = None
    schema_version: str = "n/d"
    app_version: str = "n/d"
    show_advanced_metrics: bool = True
    show_commentary: bool = True
    show_explanations: bool = False
    layout_full: bool = True
    layout_analytic: bool = True
    include_methodology: bool = True
    include_benchmark: bool = True
    theme: Any = None
    analysis_bundle: AdvancedAnalysisDatasetBundle | None = None
    monte_carlo_figure: Any = None
    monte_carlo_result: PortfolioSimulationResult | None = None


def _build_market_only_history(
    dfh: pd.DataFrame,
    *,
    data: dict[str, Any] | None = None,
    proventi: list[dict[str, Any]] | None = None,
) -> pd.DataFrame:
    """Local market-only view for Analitica charts that should exclude coupon/dividend cash."""
    if dfh is None or dfh.empty:
        return dfh

    income_items = list(proventi or [])
    if not income_items and isinstance(data, dict):
        income_items = list(get_proventi_normalizzati(data))
    if not income_items:
        return dfh

    income_by_date: dict[str, float] = {}
    for item in income_items:
        try:
            date_key = str(pd.to_datetime(item.get("data"), errors="coerce").date())
        except Exception:
            date_key = ""
        if not date_key:
            continue
        netto = _safe_float(item.get("importo_netto", 0.0))
        if abs(netto) <= 1e-12:
            continue
        income_by_date[date_key] = income_by_date.get(date_key, 0.0) + netto

    if not income_by_date:
        return dfh

    adjusted = dfh.copy()
    adjusted_dates = pd.to_datetime(adjusted["Data"], errors="coerce").dt.date.astype(str)
    cumulative_income = 0.0
    cumulative_series: list[float] = []
    for date_key in adjusted_dates:
        cumulative_income += float(income_by_date.get(date_key, 0.0) or 0.0)
        cumulative_series.append(cumulative_income)

    cumulative_income_series = pd.Series(cumulative_series, index=adjusted.index, dtype="float64")
    for column in ("P/L", "Valore", "Liquidità", "Liquidita"):
        if column in adjusted.columns:
            adjusted[column] = pd.to_numeric(adjusted[column], errors="coerce").sub(cumulative_income_series, fill_value=0.0)
    return adjusted


def _build_category_dashboard_metrics_payload(
    category: str,
    data: dict[str, Any],
    category_df: pd.DataFrame,
    dh_flow: pd.DataFrame | None,
    proventi: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    return build_category_dashboard_metrics(
        category=category,
        data=data,
        category_df=category_df,
        dh_flow=dh_flow,
        proventi=proventi,
    )


def get_summary_dataset_bundle(
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
    theme_sig: str,
    charts_settings_sig: str,
    render_mode: str,
    include_advanced: bool,
    cache_strategy: Any,
    logic_version: str,
    build_figures: bool = True,
) -> SummaryDatasetBundle:
    payload_bundle: SummaryPayloadBundle = get_summary_payload_bundle(
        data=data,
        da_frame=da_frame,
        portfolio_df=portfolio_df,
        liquidita=liquidita,
        settings=settings,
        last_quotes_update=last_quotes_update,
        proventi=proventi,
        dfh=dfh,
        data_sig=data_sig,
        charts_settings_sig=charts_settings_sig,
        render_mode=render_mode,
        logic_version=logic_version,
    )
    bundle_sig = payload_bundle.payload_sig
    figure_scope = "complete" if include_advanced else "fast"
    if build_figures:
        figures_key = f"dashboard_datasets.summary.figures.{figure_scope}"
        figures_sig_key = f"dashboard_datasets.summary.figures_sig.{figure_scope}"

        cached_figures = st.session_state.get(figures_key)
        must_rebuild_figures = (
            st.session_state.get(figures_sig_key) != bundle_sig
            or not summary_figures_cache_is_valid(cached_figures, include_advanced)
        )
        if must_rebuild_figures:
            with profile_step("Summary", "build_summary_figures", detail=f"figure Plotly Summary | modalità={render_mode}"):
                figures = build_summary_figures(
                    payload_bundle.payload,
                    settings,
                    include_advanced=include_advanced,
                    data_sig=data_sig,
                    theme_sig=theme_sig,
                    charts_settings_sig=charts_settings_sig,
                    page_mode=render_mode,
                    cache_strategy=cache_strategy,
                )
            st.session_state[figures_key] = figures
            st.session_state[figures_sig_key] = bundle_sig
        else:
            with profile_step("Summary", "cache hit figures", detail=f"scope={figure_scope}; sig={bundle_sig}"):
                figures = cached_figures
    else:
        figure_scope = "payload_only"
        with profile_step("Summary", "skip_summary_figures", detail=f"scope={figure_scope}; sig={bundle_sig}"):
            figures = {}

    return SummaryDatasetBundle(
        payload=payload_bundle.payload,
        figures=figures,
        data_sig=payload_bundle.data_sig,
        payload_sig=bundle_sig,
        figure_sig=bundle_sig,
        figure_scope=figure_scope,
        render_mode=payload_bundle.render_mode,
    )


def _build_analysis_category_dashboard_bundles(
    *,
    dfh_top: pd.DataFrame,
    da: pd.DataFrame,
    data: dict[str, Any],
    settings: dict[str, Any] | None,
    dh_flow: pd.DataFrame,
    proventi: list[dict[str, Any]] | None,
    data_sig: str,
    theme_sig: str,
    charts_settings_sig: str,
    cache_strategy: Any,
    theme: Any = None,
    app_version: str = "n/d",
    schema_version: str = "n/d",
) -> list[AnalysisCategoryDashboardBundle]:
    with profile_step("Cruscotti", "build dashboard categoria completo", detail="source=builder", count=len(da) if da is not None else 0):
        pass

    datasets: list[AnalysisCategoryDataset] = get_analysis_category_datasets(
        da=da,
        data=data,
        data_sig=data_sig,
        settings=settings,
    )
    fcache = get_registered_figure_cache()
    bundles: list[AnalysisCategoryDashboardBundle] = []
    for dataset in datasets:
        # Per-category signature: only instruments in this category change → only
        # this category's figures miss in FigureCache on a targeted price refresh.
        cat_data_sig = build_category_data_signature(
            data,
            dataset.category,
            app_version=app_version,
            schema_version=schema_version,
        )
        metrics_sig = build_cache_artifact_signature(
            "cruscotti.category_metrics",
            inputs={
                "category": dataset.category,
                "category_data_sig": cat_data_sig,
                "data_sig": str(data_sig or ""),
                "dh_flow_rows": int(len(dh_flow)) if dh_flow is not None else 0,
                "proventi_count": int(len(proventi or [])),
                "metrics_version": "metrics_v2",
            },
        )
        metrics_spec = get_cache_artifact_spec("cruscotti.category_metrics")
        with profile_step("Cruscotti/CategoryDashboard", f"{dataset.category} - load/build metrics", count=len(dataset.df) if dataset.df is not None else 0, detail=f"sig={metrics_sig[-24:]}"):
            metrics_artifact = get_or_build_registered_artifact(
                artifact_id=metrics_spec.artifact_id,
                signature=metrics_sig,
                builder=lambda current_category=dataset.category, current_df=dataset.df: _build_category_dashboard_metrics_payload(
                    current_category,
                    data,
                    current_df,
                    dh_flow,
                    proventi,
                ),
                clone_on_read=True,
            )
            metrics = metrics_artifact.value if isinstance(metrics_artifact.value, list) else []
        with profile_step("Cruscotti/CategoryDashboard", f"{dataset.category} - build grafico compatto", count=len(dataset.df) if dataset.df is not None else 0):
            compact_figure = fcache.get_or_build(
                chart_id="cruscotti_compact_category_dashboard",
                data_sig=cat_data_sig,
                theme_sig=theme_sig,
                charts_settings_sig=charts_settings_sig,
                builder=lambda current_df=dataset.df, current_cat=dataset.category: build_compact_category_dashboard_chart(
                    current_df,
                    macro_color(current_cat),
                ),
                page_mode="Completa",
                extra_params={"category": dataset.category, "items": len(dataset.df) if dataset.df is not None else 0},
                strategy=cache_strategy,
            )
        with profile_step("Cruscotti/CategoryDashboard", f"{dataset.category} - build temporale comparto", count=len(dfh_top) if dfh_top is not None else 0):
            # Estrai la data della prima operazione dai metrics
            first_op_date = None
            for metric in metrics:
                if metric.get("label") == "Prima operazione":
                    first_op_date = metric.get("value")
                    break
            temporal_figure = fcache.get_or_build(
                chart_id=f"cruscotti_category_temporal_{dataset.category}",
                data_sig=cat_data_sig,
                theme_sig=theme_sig,
                charts_settings_sig=charts_settings_sig,
                builder=lambda current_cat=dataset.category, start_d=first_op_date: build_category_temporal_dual_axis(dfh_top, da, current_cat, data, start_date=start_d),
                page_mode="Completa",
                extra_params={"category": dataset.category, "start_date": str(first_op_date), "current_alignment": "v2"},
                strategy=cache_strategy,
            )
        with profile_step("Cruscotti/CategoryDashboard", f"{dataset.category} - build value pie", count=len(dataset.df) if dataset.df is not None else 0):
            value_pie_figure = fcache.get_or_build(
                chart_id="cruscotti_category_value_pie",
                data_sig=cat_data_sig,
                theme_sig=theme_sig,
                charts_settings_sig=charts_settings_sig,
                builder=lambda current_df=dataset.df: build_category_instrument_distribution_pie_chart(current_df),
                page_mode="Completa",
                extra_params={"category": dataset.category, "items": len(dataset.df) if dataset.df is not None else 0},
                strategy=cache_strategy,
            )
        with profile_step("Cruscotti/CategoryDashboard", f"{dataset.category} - build capital pl pie", count=len(dataset.df) if dataset.df is not None else 0):
            capital_pl_pie_figure = fcache.get_or_build(
                chart_id="cruscotti_category_capital_pl_pie",
                data_sig=cat_data_sig,
                theme_sig=theme_sig,
                charts_settings_sig=charts_settings_sig,
                builder=lambda current_df=dataset.df, current_cat=dataset.category: build_category_capital_pl_pie_chart(current_df, current_cat),
                page_mode="Completa",
                extra_params={"category": dataset.category, "items": len(dataset.df) if dataset.df is not None else 0},
                strategy=cache_strategy,
            )
        with profile_step("Cruscotti/CategoryDashboard", f"{dataset.category} - build invested vs pl", count=len(dataset.df) if dataset.df is not None else 0):
            invested_vs_pl_figure = fcache.get_or_build(
                chart_id="cruscotti_category_invested_vs_pl_v6",
                data_sig=cat_data_sig,
                theme_sig=theme_sig,
                charts_settings_sig=charts_settings_sig,
                builder=lambda current_df=dataset.df, current_cat=dataset.category: build_category_invested_vs_pl_chart(
                    current_df,
                    macro_color(current_cat),
                ),
                page_mode="Completa",
                extra_params={
                    "category": dataset.category,
                    "items": len(dataset.df) if dataset.df is not None else 0,
                    "cache_bust": "cruscotti_invested_vs_pl_v9",
                },
                strategy=cache_strategy,
            )

        # Costruisci drawdown figure
        from core.services import build_category_drawdown_series
        from ui.charts.andamento import build_category_drawdown_time_chart

        tickers_list = list(dataset.df["Ticker"].astype(str)) if dataset.df is not None and "Ticker" in dataset.df.columns else []
        with profile_step("Cruscotti/CategoryDashboard", f"{dataset.category} - build drawdown data", count=len(dfh_top) if dfh_top is not None else 0):
            drawdown_series = build_category_drawdown_series(dfh_top, dataset.category, tickers_list, dataset.df, first_op_date)
        drawdown_figure = None
        if drawdown_series:
            dfh_filtered = dfh_top if first_op_date is None else dfh_top[pd.to_datetime(dfh_top.get("Data", []), errors="coerce") >= pd.Timestamp(first_op_date)]
            with profile_step("Cruscotti/CategoryDashboard", f"{dataset.category} - build drawdown figure", count=len(dfh_filtered) if dfh_filtered is not None else 0):
                drawdown_figure = fcache.get_or_build(
                    chart_id="andamento_drawdown",
                    data_sig=cat_data_sig,
                    theme_sig=theme_sig,
                    charts_settings_sig=charts_settings_sig,
                    builder=lambda dd_series=drawdown_series, dfh_f=dfh_filtered: build_category_drawdown_time_chart(
                        dfh_f,
                        dd_series,
                        "andamento_drawdown",
                        "%d/%m/%Y",
                        theme
                    ),
                    page_mode="Completa",
                    extra_params={"category": dataset.category, "type": "category"},
                    strategy=cache_strategy,
                )

        # Costruisci monthly returns figure
        from core.services import build_category_monthly_returns
        from ui.charts.andamento import build_category_monthly_returns_time_chart

        with profile_step("Cruscotti/CategoryDashboard", f"{dataset.category} - build monthly returns data", count=len(dfh_top) if dfh_top is not None else 0):
            monthly_data = build_category_monthly_returns(dfh_top, dataset.category, tickers_list, dataset.df, first_op_date)
        monthly_returns_figure = None
        if monthly_data.get("months"):
            with profile_step("Cruscotti/CategoryDashboard", f"{dataset.category} - build monthly returns figure", count=len(monthly_data.get('months', []))):
                monthly_returns_figure = fcache.get_or_build(
                    chart_id="andamento_monthly_returns",
                    data_sig=cat_data_sig,
                    theme_sig=theme_sig,
                    charts_settings_sig=charts_settings_sig,
                    builder=lambda m_data=monthly_data: build_category_monthly_returns_time_chart(m_data, "andamento_monthly_returns", theme),
                    page_mode="Completa",
                    extra_params={"category": dataset.category, "type": "category"},
                    strategy=cache_strategy,
                )

        with profile_step("Cruscotti/CategoryDashboard", f"{dataset.category} - build P/L horizon table", count=len(dfh_top) if dfh_top is not None else 0):
            if dataset.category == "Tutto" and bundles:
                # "Tutto" e' sempre l'ultimo dataset del giro (appeso in coda
                # da _build_analysis_category_datasets_payload): le tabelle
                # per-categoria sono gia' tutte in bundles a questo punto.
                pl_horizon_table = _combine_category_pl_horizon_tables([b.pl_horizon_table for b in bundles])
            else:
                pl_horizon_table = _build_category_pl_horizon_table(dfh_top, dataset.df)

        bundles.append(
            AnalysisCategoryDashboardBundle(
                category=dataset.category,
                df=dataset.df,
                summary=dataset.summary,
                title=dataset.title,
                intro_text=dataset.intro_text,
                metrics=metrics,
                compact_figure=compact_figure,
                temporal_figure=temporal_figure,
                value_pie_figure=value_pie_figure,
                capital_pl_pie_figure=capital_pl_pie_figure,
                invested_vs_pl_figure=invested_vs_pl_figure,
                drawdown_figure=drawdown_figure,
                monthly_returns_figure=monthly_returns_figure,
                pl_horizon_table=pl_horizon_table,
            )
        )
    return bundles


def get_analysis_category_dashboard_bundles(
    *,
    dfh_top: pd.DataFrame,
    da: pd.DataFrame,
    data: dict[str, Any],
    settings: dict[str, Any] | None,
    dh_flow: pd.DataFrame,
    proventi: list[dict[str, Any]] | None,
    data_sig: str,
    theme_sig: str,
    charts_settings_sig: str,
    cache_strategy: Any,
    theme: Any = None,
    app_version: str = "n/d",
    schema_version: str = "n/d",
) -> list[AnalysisCategoryDashboardBundle]:
    spec = get_cache_artifact_spec("cruscotti.category_dashboard_bundles")
    try:
        visible_categories = tuple(get_selected_category_codes(settings))
    except Exception:
        visible_categories = tuple()
    strategy_name = getattr(cache_strategy, "name", str(cache_strategy))
    signature = build_cache_artifact_signature(
        "cruscotti.category_dashboard_bundles",
        inputs={
            "data_sig": str(data_sig or ""),
            "theme_sig": str(theme_sig or ""),
            "charts_settings_sig": str(charts_settings_sig or ""),
            "visible_categories": visible_categories,
            "cache_strategy": str(strategy_name or ""),
            "app_version": str(app_version or "n/d"),
            "schema_version": str(schema_version or "n/d"),
        },
    )
    artifact = get_or_build_registered_artifact(
        artifact_id=spec.artifact_id,
        signature=signature,
        builder=lambda: _build_analysis_category_dashboard_bundles(
            dfh_top=dfh_top,
            da=da,
            data=data,
            settings=settings,
            dh_flow=dh_flow,
            proventi=proventi,
            data_sig=data_sig,
            theme_sig=theme_sig,
            charts_settings_sig=charts_settings_sig,
            cache_strategy=cache_strategy,
            theme=theme,
            app_version=app_version,
            schema_version=schema_version,
        ),
        clone_on_read=False,
        disk_codec="pickle",
    )
    value = artifact.value
    return value if isinstance(value, list) else []


def _build_advanced_analysis_data_payload(
    data: dict[str, Any],
    da: pd.DataFrame,
    dh: pd.DataFrame,
    dh_flow: pd.DataFrame,
    proventi: list[dict[str, Any]],
    settings: dict[str, Any] | None,
    full_window: int,
) -> dict[str, Any]:
    return build_advanced_analysis_data(
        data,
        da,
        dh,
        dh_flow,
        proventi,
        settings=settings,
        recent_window=full_window,
    )


def get_advanced_analysis_dataset_bundle(
    *,
    data: dict[str, Any],
    da: pd.DataFrame,
    dh: pd.DataFrame,
    dh_flow: pd.DataFrame,
    proventi: list[dict[str, Any]],
    data_sig: str,
    recent_window: int,
    settings: dict[str, Any] | None = None,
) -> AdvancedAnalysisDatasetBundle:
    from core.asset_categories import get_selected_category_codes
    from core.series_utils import slice_recent

    selected_categories = ",".join(get_selected_category_codes(settings))
    bundle_sig = f"{data_sig}|recent_window={int(recent_window)}|cats={selected_categories}|open_position_window_return_index_v3"
    base_sig = f"{data_sig}|recent_window=full|cats={selected_categories}|open_position_window_return_index_v3"
    full_window = max(int(recent_window or 92), len(dh.index) if dh is not None else 0, len(dh_flow.index) if dh_flow is not None else 0)
    spec = get_cache_artifact_spec("cruscotti.advanced_analysis_data")
    signature = build_cache_artifact_signature(
        "cruscotti.advanced_analysis_data",
        inputs={
            "base_sig": base_sig,
            "data_sig": str(data_sig or ""),
            "selected_categories": selected_categories,
            "dh_rows": int(len(dh.index)) if dh is not None else 0,
            "dh_cols": tuple(str(col) for col in getattr(dh, "columns", [])),
            "dh_flow_rows": int(len(dh_flow.index)) if dh_flow is not None else 0,
            "dh_flow_cols": tuple(str(col) for col in getattr(dh_flow, "columns", [])),
            "proventi_count": int(len(proventi or [])),
            "full_window": int(full_window),
        },
    )
    with profile_step("Analisi", "load/build advanced analysis data", detail=f"sig={signature[-24:]}"):
        artifact = get_or_build_registered_artifact(
            artifact_id=spec.artifact_id,
            signature=signature,
            builder=lambda: _build_advanced_analysis_data_payload(
                data,
                da,
                dh,
                dh_flow,
                proventi,
                settings,
                full_window,
            ),
            clone_on_read=True,
            disk_codec="pickle",
        )
        analysis_data = artifact.value if isinstance(artifact.value, dict) else {}

    cat_flow_returns = analysis_data["cat_flow_returns"]
    if isinstance(cat_flow_returns, pd.DataFrame) and not cat_flow_returns.empty:
        cat_flow_returns = slice_recent(cat_flow_returns.dropna(how="all"), max(30, int(recent_window)))
    else:
        cat_flow_returns = pd.DataFrame()
    corr_cat = (
        cat_flow_returns.corr(min_periods=2)
        if not cat_flow_returns.empty and cat_flow_returns.shape[1] > 1
        else pd.DataFrame()
    )
    bundle = AdvancedAnalysisDatasetBundle(
        info_map=analysis_data["info_map"],
        ta=analysis_data["ta"],
        dfstats=analysis_data["dfstats"],
        irr_results=analysis_data["irr_results"],
        analysis_returns=analysis_data["analysis_returns"],
        cat_flow_returns=cat_flow_returns,
        risk_df=analysis_data["risk_df"],
        cat_index_analysis=analysis_data["cat_index_analysis"],
        corr=analysis_data["corr"],
        corr_cat=corr_cat,
    )
    return bundle


def _build_bucket_gap_macro_df(da_frame: pd.DataFrame, bucket_of_ticker: dict[str, str], objective: dict[str, float]) -> pd.DataFrame:
    cats = ["Core", "Difensivo", "Satellite"]
    if da_frame is None or da_frame.empty:
        return pd.DataFrame()
    work = da_frame.copy()
    work = work[pd.to_numeric(work["Controvalore"], errors="coerce").fillna(0) > 0].copy()
    if work.empty:
        return pd.DataFrame()
    total_value = float(pd.to_numeric(work["Controvalore"], errors="coerce").fillna(0).sum())
    if total_value <= 0:
        return pd.DataFrame()
    work["Categoria"] = work["Ticker"].astype(str).map(lambda t: bucket_of_ticker.get(t, "Satellite"))
    macro = work.groupby("Categoria", as_index=False).agg(Controvalore=("Controvalore", "sum"))
    macro = macro.set_index("Categoria").reindex(cats, fill_value=0.0).reset_index()
    macro["Peso attuale"] = macro["Controvalore"] / total_value
    target_map = {"Core": objective.get("core", 0.0), "Difensivo": objective.get("difensivo", 0.0), "Satellite": objective.get("satellite", 0.0)}
    macro["Peso target"] = macro["Categoria"].map(target_map)
    macro["Scostamento %"] = macro["Peso attuale"] - macro["Peso target"]
    macro["Da riallocare €"] = (macro["Peso target"] - macro["Peso attuale"]) * total_value
    return macro


def _build_analitica_bundle(
    *,
    dfh_top: pd.DataFrame,
    da: pd.DataFrame,
    data: dict[str, Any],
    settings: dict[str, Any] | None,
    data_sig: str,
    theme_sig: str,
    charts_settings_sig: str,
    cache_strategy: Any,
    theme: Any,
    dfmt: str,
    pl_color: str,
    pl_totale: float,
    radar_payload: dict[str, Any] | None = None,
    dh_hist: pd.DataFrame | None = None,
    dh_flow: pd.DataFrame | None = None,
    proventi: list[dict[str, Any]] | None = None,
    summary_bundle: SummaryDatasetBundle | None = None,
    schema_version: str = "n/d",
    app_version: str = "n/d",
    show_advanced_metrics: bool = True,
    show_commentary: bool = True,
    show_explanations: bool = False,
    layout_full: bool = True,
    layout_analytic: bool = True,
    include_methodology: bool = True,
    include_benchmark: bool = True,
    i18n_profile: dict[str, Any] | None = None,
) -> AnaliticaBundle:
    fcache = get_registered_figure_cache()
    dfh_market_only = _build_market_only_history(
        dfh_top,
        data=data,
        proventi=proventi,
    )

    with profile_step("Cruscotti/Analitica", "build portfolio value figure"):
        if dfh_top is None or dfh_top.empty:
            portfolio_value_fig = empty_chart("andamento_portfolio_value")
        else:
            portfolio_value_fig = fcache.get_or_build(
                chart_id="andamento_portfolio_value",
                data_sig=data_sig,
                theme_sig=theme_sig,
                charts_settings_sig=charts_settings_sig,
                builder=lambda: build_portfolio_value_time_chart(dfh_top, dfmt, theme),
                page_mode="Completa",
                strategy=cache_strategy,
            )

    with profile_step("Cruscotti/Analitica", "build PL decomposition figure"):
        pl_cols = [c for c in dfh_market_only.columns if c.startswith("PL_")]
        pl_decomposition_fig = fcache.get_or_build(
            chart_id="andamento_pl_decomp_stacked",
            data_sig=data_sig,
            theme_sig=theme_sig,
            charts_settings_sig=charts_settings_sig,
            builder=lambda: build_pl_decomposition_time_chart(dfh_market_only, pl_cols, "Stacked", dfmt, theme),
            page_mode="Completa",
            extra_params={"viz_mode": "Stacked", "palette": "instrument_based_v3", "income_mode": "market_only_v1"},
            strategy=cache_strategy,
        )

    with profile_step("Cruscotti/Analitica", "build percentage return figure"):
        pct_data = build_percentage_return_series(dfh_market_only, data)
        pct_cap = pct_data["pct_cap"]
        pct_cost = pct_data["pct_cost"]
        pl_total_market_only = float(pd.to_numeric(dfh_market_only["P/L"], errors="coerce").iloc[-1] or 0.0) if dfh_market_only is not None and not dfh_market_only.empty else float(pl_totale or 0.0)
        if dfh_market_only is None or dfh_market_only.empty:
            percentage_return_fig = empty_chart("andamento_percentage_return")
        else:
            percentage_return_fig = fcache.get_or_build(
                chart_id="andamento_percentage_return",
                data_sig=data_sig,
                theme_sig=theme_sig,
                charts_settings_sig=charts_settings_sig,
                builder=lambda: build_percentage_return_time_chart(dfh_market_only, pct_cap, pct_cost, pl_color, pl_total_market_only, dfmt, theme),
                page_mode="Completa",
                extra_params={"return_alignment": "current_pl_v2", "income_mode": "market_only_v1"},
                strategy=cache_strategy,
            )

    with profile_step("Cruscotti/Analitica", "build target gap figure"):
        if da is None or da.empty:
            target_gap_fig = empty_chart("analisi_target_gap")
        else:
            objective = settings.get("portfolio_objective", {"core": 0.55, "difensivo": 0.25, "satellite": 0.20}) if isinstance(settings, dict) else {}
            objective_token = _objective_cache_token(objective)
            bucket_of_ticker = compute_instrument_buckets(data)
            macro_target_df = _build_bucket_gap_macro_df(da, bucket_of_ticker, objective)
            target_gap_fig = fcache.get_or_build(
                chart_id="analisi_target_gap",
                data_sig=data_sig,
                theme_sig=theme_sig,
                charts_settings_sig=charts_settings_sig,
                builder=lambda: build_target_gap_chart(macro_target_df) if not macro_target_df.empty else empty_chart("analisi_target_gap"),
                page_mode="Completa",
                extra_params={"objective": objective_token, "bucket_model": "sator_bucket_v1"},
                strategy=cache_strategy,
            )

    with profile_step("Cruscotti/Analitica", "build risk contribution figure"):
        analysis_bundle = None
        if da is None or da.empty:
            risk_df = pd.DataFrame()
        else:
            _dh_flow = dh_flow if dh_flow is not None else pd.DataFrame()
            _proventi = proventi if proventi is not None else []
            dh_hist_effective = dh_hist if dh_hist is not None else pd.DataFrame()
            if dh_hist_effective is None or dh_hist_effective.empty:
                from core.finance import build_hist_df
                dh_hist_effective = build_hist_df(data)
            analysis_bundle = get_advanced_analysis_dataset_bundle(
                data=data,
                da=da,
                dh=dh_hist_effective,
                dh_flow=_dh_flow,
                proventi=_proventi,
                data_sig=data_sig,
                recent_window=252,
                settings=settings,
            )
            risk_df = analysis_bundle.risk_df

        def _build_risk_contrib():
            if risk_df.empty:
                import plotly.graph_objects as go
                from ui.charts.settings import apply_settings
                fig = go.Figure()
                fig.add_annotation(
                    text="Dati insufficienti: sono necessari almeno 3 quotazioni per almeno 2 strumenti per l'analisi del rischio.",
                    xref="paper", yref="paper",
                    x=0.5, y=0.5,
                    showarrow=False,
                    font=dict(size=12)
                )
                return apply_settings(fig, "analisi_risk_contribution2")

            prepared_df = risk_df.copy()
            if "Rapporto rischio/peso" in prepared_df.columns:
                risk_ratio = pd.to_numeric(prepared_df["Rapporto rischio/peso"], errors="coerce").fillna(0.0)
                prepared_df["Semaforo"] = np.where(risk_ratio <= 1.0, "🟢", np.where(risk_ratio <= 1.20, "🟡", "🔴"))
            else:
                prepared_df["Semaforo"] = "🟡"
            prepared_df["Etichetta"] = prepared_df["Ticker"].astype(str) + " " + prepared_df["Semaforo"].astype(str)
            return build_risk_contribution_chart(prepared_df)

        risk_contribution_fig = fcache.get_or_build(
            chart_id="analisi_risk_contribution2_v3",
            data_sig=data_sig,
            theme_sig=theme_sig,
            charts_settings_sig=charts_settings_sig,
            builder=_build_risk_contrib,
            page_mode="Completa",
            extra_params={"risk_scope": "all_instruments_v2"},
            strategy=cache_strategy,
        )

    with profile_step("Cruscotti/Analitica", "build monte carlo figure"):
        if analysis_bundle is None:
            monte_carlo_result = build_portfolio_simulation(pd.DataFrame(), pd.DataFrame())
        else:
            monte_carlo_result = build_portfolio_simulation(
                dh_hist_effective,
                analysis_bundle.risk_df,
                n_scenarios=2000,
                seed=20260808,
            )
        monte_carlo_fig = fcache.get_or_build(
            chart_id="analisi_monte_carlo",
            data_sig=data_sig,
            theme_sig=theme_sig,
            charts_settings_sig=charts_settings_sig,
            builder=lambda: build_portfolio_simulation_chart(monte_carlo_result, theme),
            page_mode="Completa",
            extra_params={"monte_carlo_scenarios": 2000, "monte_carlo_seed": 20260808},
            strategy=cache_strategy,
        )

    with profile_step("Cruscotti/Analitica", "build performance attribution figure"):
        performance_attribution_fig = fcache.get_or_build(
            chart_id="analisi_performance_attribution",
            data_sig=data_sig,
            theme_sig=theme_sig,
            charts_settings_sig=charts_settings_sig,
            builder=lambda: build_performance_attribution(da, dfh_top),
            page_mode="Completa",
            strategy=cache_strategy,
        )

    with profile_step("Cruscotti/Analitica", "build asset allocation radar figure"):
        _radar_payload = radar_payload or {}
        asset_allocation_radar_fig = fcache.get_or_build(
            chart_id="home_radar_allocation",
            data_sig=data_sig,
            theme_sig=theme_sig,
            charts_settings_sig=charts_settings_sig,
            builder=lambda rp=_radar_payload: build_asset_allocation_radar(rp, theme),
            page_mode="Completa",
            strategy=cache_strategy,
        )

    with profile_step("Cruscotti/Analitica", "build quality profile radar figure"):
        quality_profile_radar_fig = fcache.get_or_build(
            chart_id="home_radar_quality",
            data_sig=data_sig,
            theme_sig=theme_sig,
            charts_settings_sig=charts_settings_sig,
            builder=lambda rp=_radar_payload: build_quality_profile_radar(rp, theme),
            page_mode="Completa",
            strategy=cache_strategy,
        )

    _summary_payload = summary_bundle.payload if summary_bundle else {}
    _reporting_pack = summary_bundle.figures.get("reporting_pack", {}) if summary_bundle else {}
    _reporting_pack_md = summary_bundle.figures.get("reporting_pack_md", "") if summary_bundle else ""

    return AnaliticaBundle(
        portfolio_value_figure=portfolio_value_fig,
        pl_decomposition_figure=pl_decomposition_fig,
        percentage_return_figure=percentage_return_fig,
        target_gap_figure=target_gap_fig,
        risk_contribution_figure=risk_contribution_fig,
        performance_attribution_figure=performance_attribution_fig,
        asset_allocation_radar_figure=asset_allocation_radar_fig,
        quality_profile_radar_figure=quality_profile_radar_fig,
        radar_payload=radar_payload,
        summary_payload=_summary_payload,
        reporting_pack=_reporting_pack,
        reporting_pack_md=_reporting_pack_md,
        i18n_profile=i18n_profile,
        schema_version=schema_version,
        app_version=app_version,
        show_advanced_metrics=show_advanced_metrics,
        show_commentary=show_commentary,
        show_explanations=show_explanations,
        layout_full=layout_full,
        layout_analytic=layout_analytic,
        include_methodology=include_methodology,
        include_benchmark=include_benchmark,
        theme=theme,
        analysis_bundle=analysis_bundle,
        monte_carlo_figure=monte_carlo_fig,
        monte_carlo_result=monte_carlo_result,
    )


def get_analitica_bundle(
    *,
    dfh_top: pd.DataFrame,
    da: pd.DataFrame,
    data: dict[str, Any],
    settings: dict[str, Any] | None,
    data_sig: str,
    theme_sig: str,
    charts_settings_sig: str,
    cache_strategy: Any,
    theme: Any,
    dfmt: str,
    pl_color: str,
    pl_totale: float,
    radar_payload: dict[str, Any] | None = None,
    dh_hist: pd.DataFrame | None = None,
    dh_flow: pd.DataFrame | None = None,
    proventi: list[dict[str, Any]] | None = None,
    summary_bundle: SummaryDatasetBundle | None = None,
    schema_version: str = "n/d",
    app_version: str = "n/d",
    show_advanced_metrics: bool = True,
    show_commentary: bool = True,
    show_explanations: bool = False,
    layout_full: bool = True,
    layout_analytic: bool = True,
    include_methodology: bool = True,
    include_benchmark: bool = True,
    i18n_profile: dict[str, Any] | None = None,
) -> AnaliticaBundle:
    spec = get_cache_artifact_spec("cruscotti.analitica_bundle")
    objective = settings.get("portfolio_objective", {}) if isinstance(settings, dict) else {}
    try:
        visible_categories = tuple(get_selected_category_codes(settings))
    except Exception:
        visible_categories = tuple()
    strategy_name = getattr(cache_strategy, "name", str(cache_strategy))
    signature = build_cache_artifact_signature(
        "cruscotti.analitica_bundle",
        inputs={
            "data_sig": str(data_sig or ""),
            "theme_sig": str(theme_sig or ""),
            "charts_settings_sig": str(charts_settings_sig or ""),
            "cache_strategy": str(strategy_name or ""),
            "visible_categories": visible_categories,
            "objective": objective,
            "summary_payload_sig": getattr(summary_bundle, "payload_sig", ""),
            "summary_figure_scope": getattr(summary_bundle, "figure_scope", ""),
            "radar_payload": radar_payload or {},
            "dfmt": str(dfmt or ""),
            "pl_color": str(pl_color or ""),
            "pl_totale": round(float(pl_totale or 0.0), 6),
            "schema_version": str(schema_version or "n/d"),
            "app_version": str(app_version or "n/d"),
            "show_advanced_metrics": bool(show_advanced_metrics),
            "show_commentary": bool(show_commentary),
            "show_explanations": bool(show_explanations),
            "layout_full": bool(layout_full),
            "layout_analytic": bool(layout_analytic),
            "include_methodology": bool(include_methodology),
            "include_benchmark": bool(include_benchmark),
        },
    )
    artifact = get_or_build_registered_artifact(
        artifact_id=spec.artifact_id,
        signature=signature,
        builder=lambda: _build_analitica_bundle(
            dfh_top=dfh_top,
            da=da,
            data=data,
            settings=settings,
            data_sig=data_sig,
            theme_sig=theme_sig,
            charts_settings_sig=charts_settings_sig,
            cache_strategy=cache_strategy,
            theme=theme,
            dfmt=dfmt,
            pl_color=pl_color,
            pl_totale=pl_totale,
            radar_payload=radar_payload,
            dh_hist=dh_hist,
            dh_flow=dh_flow,
            proventi=proventi,
            summary_bundle=summary_bundle,
            schema_version=schema_version,
            app_version=app_version,
            show_advanced_metrics=show_advanced_metrics,
            show_commentary=show_commentary,
            show_explanations=show_explanations,
            layout_full=layout_full,
            layout_analytic=layout_analytic,
            include_methodology=include_methodology,
            include_benchmark=include_benchmark,
            i18n_profile=i18n_profile,
        ),
        clone_on_read=False,
        disk_codec="pickle",
    )
    value = artifact.value
    if isinstance(value, AnaliticaBundle):
        return value
    return _build_analitica_bundle(
        dfh_top=dfh_top,
        da=da,
        data=data,
        settings=settings,
        data_sig=data_sig,
        theme_sig=theme_sig,
        charts_settings_sig=charts_settings_sig,
        cache_strategy=cache_strategy,
        theme=theme,
        dfmt=dfmt,
        pl_color=pl_color,
        pl_totale=pl_totale,
        radar_payload=radar_payload,
        dh_hist=dh_hist,
        dh_flow=dh_flow,
        proventi=proventi,
        summary_bundle=summary_bundle,
        schema_version=schema_version,
        app_version=app_version,
        show_advanced_metrics=show_advanced_metrics,
        show_commentary=show_commentary,
        show_explanations=show_explanations,
        layout_full=layout_full,
        layout_analytic=layout_analytic,
        include_methodology=include_methodology,
        include_benchmark=include_benchmark,
        i18n_profile=i18n_profile,
    )
