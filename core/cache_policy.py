from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class CacheArtifactSpec:
    """Contratto centrale per un artefatto cache 5.0.

    Il registry non costruisce payload e non dipende da Streamlit: descrive
    cosa esiste, da cosa dipende e come deve essere tracciato.
    """

    artifact_id: str
    page_id: str
    layer: str
    level: str
    owner: str
    storage: str
    version: str
    dependencies: tuple[str, ...]
    clear_group: str
    stale_policy: str
    log_page: str
    description: str
    prebuild: bool = False
    status: str = "planned"
    trigger: str = "navigation"
    rerun_policy: str = "no_extra_rerun"
    action_scope: str = "ordinary_render"


_CACHE_ARTIFACT_REGISTRY: dict[str, CacheArtifactSpec] = {}


def register_cache_artifact(spec: CacheArtifactSpec) -> CacheArtifactSpec:
    """Registra un artefatto nel contratto cache centrale."""

    artifact_id = str(spec.artifact_id or "").strip()
    if not artifact_id:
        raise ValueError("artifact_id mancante")
    if artifact_id in _CACHE_ARTIFACT_REGISTRY:
        raise ValueError(f"Cache artifact gia' registrato: {artifact_id}")
    _CACHE_ARTIFACT_REGISTRY[artifact_id] = spec
    return spec


def get_cache_artifact_spec(artifact_id: str) -> CacheArtifactSpec:
    """Restituisce la specifica registry per un artefatto."""

    key = str(artifact_id or "").strip()
    try:
        return _CACHE_ARTIFACT_REGISTRY[key]
    except KeyError as exc:
        raise KeyError(f"Cache artifact non registrato: {key}") from exc


def iter_cache_artifact_specs(*, status: str | None = None) -> Iterable[CacheArtifactSpec]:
    """Itera le specifiche registrate, opzionalmente filtrate per stato."""

    specs = tuple(_CACHE_ARTIFACT_REGISTRY.values())
    if status is None:
        return specs
    wanted = str(status or "").strip()
    return tuple(spec for spec in specs if spec.status == wanted)


def iter_prebuild_artifact_specs() -> Iterable[CacheArtifactSpec]:
    """Restituisce gli artefatti che il prewarm puo' preparare prima della UI."""

    return tuple(spec for spec in _CACHE_ARTIFACT_REGISTRY.values() if spec.prebuild)


def build_cache_artifact_signature(
    artifact_id: str,
    *,
    inputs: dict[str, Any],
    version: str | None = None,
) -> str:
    """Costruisce una firma usando il registry come fonte del contratto."""

    spec = get_cache_artifact_spec(artifact_id)
    from core.page_cache import build_page_artifact_signature

    return build_page_artifact_signature(
        page_id=spec.page_id,
        layer=spec.layer,
        version=version or spec.version,
        inputs={
            "artifact_id": spec.artifact_id,
            "dependencies": spec.dependencies,
            **(inputs or {}),
        },
    )


register_cache_artifact(
    CacheArtifactSpec(
        artifact_id="quotazioni.diagnostic_table",
        page_id="quotazioni",
        layer="diagnostic_table",
        level="L3",
        owner="core.quotes_runtime.build_quotes_diagnostic_table",
        storage="page_artifact",
        version="quotes-diagnostic-table-v1",
        dependencies=(
            "market_data_signature",
            "quotes_log.last_refresh",
            "quotes_log.items",
            "quotes_refresh_df",
            "closed_tickers",
        ),
        clear_group="quotazioni",
        stale_policy="rebuild_on_quotes_or_instrument_change",
        log_page="Quotazioni",
        description="Tabella diagnostica Ultime quotazioni aggiornata e pronta per la UI.",
        prebuild=True,
        status="registered_provider",
    )
)

register_cache_artifact(
    CacheArtifactSpec(
        artifact_id="quotazioni.dataset_bundle",
        page_id="quotazioni",
        layer="dataset_bundle",
        level="L3",
        owner="core.dashboard_datasets.get_quotazioni_dataset_bundle",
        storage="page_artifact",
        version="quotazioni-dataset-bundle-v1",
        dependencies=(
            "market_data_signature",
            "cashflow_data_signature",
            "selected_categories",
            "closed_tickers",
            "quotazioni_view_contract",
        ),
        clear_group="quotazioni",
        stale_policy="rebuild_on_quotes_history_cashflow_category_or_closed_change",
        log_page="Quotazioni",
        description="Bundle shared Quotazioni con ticker validi, gruppi categoria e indici cashflow per confronto performance.",
        prebuild=True,
        status="registered_provider",
    )
)

register_cache_artifact(
    CacheArtifactSpec(
        artifact_id="quotazioni.category_ticker_bundles",
        page_id="quotazioni",
        layer="category_ticker_bundles",
        level="L2",
        owner="core.dashboard_datasets.get_quotazioni_dataset_bundle",
        storage="page_artifact",
        version="quotazioni-category-ticker-bundles-v1",
        dependencies=(
            "category_data_signature",
            "closed_tickers",
            "quotazioni_view_contract",
            "benchmark_series_cache",
        ),
        clear_group="quotazioni",
        stale_policy="rebuild_on_category_signature_or_view_contract_change",
        log_page="Quotazioni",
        description="Serie normalizzate e benchmark dei ticker Quotazioni per singola categoria, senza st.cache_data locale.",
        prebuild=True,
        status="registered_provider",
    )
)

register_cache_artifact(
    CacheArtifactSpec(
        artifact_id="dati.quality_table",
        page_id="dati",
        layer="quality_table",
        level="L2",
        owner="core.services.instrument_quality.build_instrument_quality_dataset",
        storage="page_artifact",
        version="quality-light-v2",
        dependencies=("portfolio_data_signature", "instrument_registry", "price_history", "privacy_filter", "asof_date"),
        clear_group="dati",
        stale_policy="rebuild_on_data_or_history_change",
        log_page="Dati",
        description="Dataset qualita dati strumenti, senza metriche finanziarie pesanti nella vista Dati.",
        prebuild=True,
        status="registered_provider",
    )
)

register_cache_artifact(
    CacheArtifactSpec(
        artifact_id="dati.cache_diagnostics",
        page_id="dati",
        layer="cache_diagnostics",
        level="L3",
        owner="ui.pages.gestione_dati._get_cached_cache_diagnostics",
        storage="page_artifact",
        version="cache-diagnostics-v1",
        dependencies=("cache_action_log", "figure_cache_manifest", "page_artifact_manifest"),
        clear_group="dati",
        stale_policy="rebuild_on_explicit_cache_action_only",
        log_page="Dati",
        description="Payload diagnostico cache per la pagina Dati basato su manifest, senza invalidazione temporale all'avvio.",
        prebuild=False,
        status="registered_provider",
        trigger="navigation",
        rerun_policy="no_global_rebuild",
        action_scope="diagnostics_light",
    )
)

register_cache_artifact(
    CacheArtifactSpec(
        artifact_id="dati.remote_php_export",
        page_id="dati",
        layer="remote_php_export",
        level="L2",
        owner="ui.pages.gestione_dati._get_remote_quotes_php",
        storage="page_artifact",
        version="remote-php-export-v1",
        dependencies=("portfolio_data_signature", "instrument_registry", "remote_php_template"),
        clear_group="dati",
        stale_policy="rebuild_on_instrument_or_template_change",
        log_page="Dati",
        description="Export aggiorna_remoto.php generato da Dati tramite registry/page-cache, senza st.cache_data locale.",
        prebuild=False,
        trigger="navigation",
        rerun_policy="no_extra_rerun",
        action_scope="data_tools",
        status="registered_provider",
    )
)

register_cache_artifact(
    CacheArtifactSpec(
        artifact_id="portafoglio.positions_table",
        page_id="portafoglio",
        layer="positions_table",
        level="L3",
        owner="ui.pages.home._build_positions_table_payload",
        storage="page_artifact",
        version="positions-table-v1",
        dependencies=(
            "portfolio_data_signature",
            "latest_quotes",
            "portfolio_table_settings",
            "sator_decisions_file",
            "portfolio_alerts",
            "maturity_alerts",
        ),
        clear_group="portafoglio",
        stale_policy="rebuild_on_position_or_price_change",
        log_page="Portafoglio",
        description="Payload posizioni, frecce giornaliere e insight usato dalla tabella Controvalore del Portafoglio.",
        prebuild=True,
        status="registered_provider",
    )
)

register_cache_artifact(
    CacheArtifactSpec(
        artifact_id="cruscotti.category_dashboard_bundles",
        page_id="cruscotti",
        layer="category_dashboard_bundles",
        level="L3",
        owner="ui.dashboard_bundles.get_analysis_category_dashboard_bundles",
        storage="page_artifact",
        version="category-dashboard-bundles-v1",
        dependencies=(
            "portfolio_data_signature",
            "theme_signature",
            "charts_settings_signature",
            "selected_categories",
            "figure_cache_strategy",
        ),
        clear_group="cruscotti",
        stale_policy="rebuild_on_data_theme_chart_or_category_change",
        log_page="Cruscotti",
        description="Bundle categorie Cruscotti gia' pronto per tab GOV/ETF/FND/Tutto.",
        prebuild=True,
        status="registered_provider",
    )
)

register_cache_artifact(
    CacheArtifactSpec(
        artifact_id="cruscotti.analitica_bundle",
        page_id="cruscotti",
        layer="analitica_bundle",
        level="L3",
        owner="ui.dashboard_bundles.get_analitica_bundle",
        storage="page_artifact_plus_figure_cache",
        version="analitica-bundle-v1",
        dependencies=(
            "portfolio_data_signature",
            "theme_signature",
            "charts_settings_signature",
            "portfolio_objective",
            "summary_payload",
            "radar_payload",
        ),
        clear_group="cruscotti",
        stale_policy="rebuild_on_data_theme_chart_or_target_change",
        log_page="Cruscotti",
        description="Bundle Analitica con figure e payload gia' pronti per il render.",
        prebuild=True,
        status="registered_provider",
    )
)

register_cache_artifact(
    CacheArtifactSpec(
        artifact_id="cruscotti.advanced_analysis_data",
        page_id="cruscotti",
        layer="advanced_analysis_data",
        level="L2",
        owner="ui.dashboard_bundles.get_advanced_analysis_dataset_bundle",
        storage="page_artifact",
        version="advanced-analysis-data-v1",
        dependencies=(
            "portfolio_data_signature",
            "selected_categories",
            "historical_price_frame",
            "cashflow_price_frame",
            "proventi",
            "recent_window_full",
        ),
        clear_group="cruscotti",
        stale_policy="rebuild_on_analysis_data_signature_change",
        log_page="Analisi",
        description="Dataset finanziari avanzati di Analitica governati dal registry, senza st.cache_data locale.",
        prebuild=True,
        status="registered_provider",
    )
)

register_cache_artifact(
    CacheArtifactSpec(
        artifact_id="cruscotti.category_metrics",
        page_id="cruscotti",
        layer="category_metrics",
        level="L2",
        owner="ui.dashboard_bundles._build_category_dashboard_metrics_payload",
        storage="page_artifact",
        version="category-dashboard-metrics-v1",
        dependencies=(
            "category_data_signature",
            "portfolio_data_signature",
            "category",
            "dh_flow",
            "proventi",
        ),
        clear_group="cruscotti",
        stale_policy="rebuild_on_category_metrics_signature_change",
        log_page="Cruscotti",
        description="Metriche KPI per singola categoria Cruscotti, governate dal registry invece che da st.cache_data locale.",
        prebuild=True,
        status="registered_provider",
    )
)

register_cache_artifact(
    CacheArtifactSpec(
        artifact_id="mercati.live_snapshot",
        page_id="mercati",
        layer="live_snapshot",
        level="L1",
        owner="core.infrastructure.market_auto_refresh",
        storage="benchmark_cache_file",
        version="market-live-snapshot-v1",
        dependencies=("market_registry", "benchmark_cache_file", "market_live_data"),
        clear_group="mercati",
        stale_policy="manual_or_background_refresh_only",
        log_page="Mercati",
        description="Snapshot live Mercati opzionale, fuori dal costo base dell'app.",
        prebuild=False,
        trigger="explicit_action_or_background",
        rerun_policy="no_forced_rerun",
        action_scope="mercati_only",
        status="pilot",
    )
)

register_cache_artifact(
    CacheArtifactSpec(
        artifact_id="mercati.overview_rows",
        page_id="mercati",
        layer="overview_rows",
        level="L2",
        owner="ui.pages.mercati.build_market_overview_rows",
        storage="page_artifact",
        version="market-overview-rows-v1",
        dependencies=("market_registry", "benchmark_cache_file", "market_live_data", "market_data_signature"),
        clear_group="mercati",
        stale_policy="rebuild_on_market_data_signature_change",
        log_page="Mercati",
        description="Righe derivate della pagina Mercati: valori, ritorni e fonte dati. Stato aperto/chiuso aggiornato live dopo la lettura cache.",
        prebuild=False,
        status="registered_provider",
    )
)

register_cache_artifact(
    CacheArtifactSpec(
        artifact_id="mercati.base100_frame",
        page_id="mercati",
        layer="base100_frame",
        level="L2",
        owner="ui.pages.mercati.build_market_base100_frame",
        storage="page_artifact",
        version="market-base100-frame-v1",
        dependencies=("market_registry", "benchmark_cache_file", "market_data_signature", "observations"),
        clear_group="mercati",
        stale_policy="rebuild_on_market_data_signature_or_period_change",
        log_page="Mercati",
        description="DataFrame base 100 Mercati per il confronto comparato, cacheato per periodo.",
        prebuild=False,
        status="registered_provider",
    )
)

register_cache_artifact(
    CacheArtifactSpec(
        artifact_id="summary.dashboard_payload",
        page_id="summary",
        layer="dashboard_payload",
        level="L2",
        owner="core.dashboard_datasets.get_summary_payload_bundle",
        storage="page_artifact",
        version="summary-dashboard-payload-v1",
        dependencies=(
            "portfolio_data_signature",
            "charts_settings_signature",
            "summary_runtime_settings",
            "summary_input_signature",
            "logic_version",
        ),
        clear_group="summary",
        stale_policy="rebuild_on_summary_payload_signature_change",
        log_page="Summary",
        description="Payload condiviso Summary governato dal registry/page-cache invece che da st.cache_data locale.",
        prebuild=True,
        status="registered_provider",
    )
)

register_cache_artifact(
    CacheArtifactSpec(
        artifact_id="summary.report_payload",
        page_id="summary",
        layer="report_payload",
        level="L3",
        owner="core.services.report_builder.build_portfolio_report_html",
        storage="report_archive_plus_page_artifact",
        version="summary-report-payload-v1",
        dependencies=(
            "portfolio_data_signature",
            "report_options",
            "theme_signature",
            "operations_report",
            "reporting_settings",
        ),
        clear_group="reports",
        stale_policy="rebuild_on_explicit_generate_or_signature_change",
        log_page="Summary",
        description="Report Summary generato da pulsante: deve essere archiviato e ripreso senza rebuild se firma e opzioni non cambiano.",
        prebuild=False,
        trigger="explicit_action",
        rerun_policy="same_run_result_no_global_invalidation",
        action_scope="summary_report_only",
        status="pilot",
    )
)

register_cache_artifact(
    CacheArtifactSpec(
        artifact_id="confronto.comparison_report",
        page_id="confronto",
        layer="comparison_report",
        level="L3",
        owner="core.services.comparison_report.build_comparison_report_html",
        storage="page_artifact",
        version="comparison-report-v1",
        dependencies=(
            "snapshot_ids",
            "portfolio_data_signature",
            "comparison_options",
            "reporting_settings",
        ),
        clear_group="reports",
        stale_policy="rebuild_on_explicit_compare_or_snapshot_change",
        log_page="Confronto",
        description="Confronto snapshot generato da pulsante: azione esplicita isolata, non invalidazione globale del portafoglio.",
        prebuild=False,
        trigger="explicit_action",
        rerun_policy="same_run_result_no_global_invalidation",
        action_scope="comparison_only",
        status="registered_provider",
    )
)

register_cache_artifact(
    CacheArtifactSpec(
        artifact_id="cruscotti.benchmark_frozen_analysis",
        page_id="cruscotti",
        layer="benchmark_frozen_analysis",
        level="L3",
        owner="ui.pages.cruscotti_benchmark.render_benchmark",
        storage="page_artifact_plus_figure_cache",
        version="benchmark-frozen-analysis-v1",
        dependencies=(
            "portfolio_data_signature",
            "benchmark_options",
            "theme_signature",
            "charts_settings_signature",
        ),
        clear_group="cruscotti",
        stale_policy="rebuild_on_explicit_benchmark_analysis_only",
        log_page="Cruscotti",
        description="Analisi Benchmark congelata di Cruscotti: il click genera un artefatto riprendibile nei rerun successivi.",
        prebuild=False,
        trigger="explicit_action",
        rerun_policy="no_global_rebuild",
        action_scope="cruscotti_benchmark_only",
        status="pilot",
    )
)

register_cache_artifact(
    CacheArtifactSpec(
        artifact_id="cruscotti.accumuli_frozen_analysis",
        page_id="cruscotti",
        layer="accumuli_frozen_analysis",
        level="L3",
        owner="ui.pages.cruscotti_accumuli.render_accumuli",
        storage="page_artifact_plus_figure_cache",
        version="accumuli-frozen-analysis-v1",
        dependencies=(
            "portfolio_data_signature",
            "accumuli_options",
            "theme_signature",
            "charts_settings_signature",
        ),
        clear_group="cruscotti",
        stale_policy="rebuild_on_explicit_accumuli_analysis_only",
        log_page="Cruscotti",
        description="Analisi Accumuli/PAC congelata di Cruscotti: il click genera un artefatto riprendibile nei rerun successivi.",
        prebuild=False,
        trigger="explicit_action",
        rerun_policy="no_global_rebuild",
        action_scope="cruscotti_accumuli_only",
        status="pilot",
    )
)


# Provider non-page-artifact del governo cache 5.0.
# Non tutte le cache devono usare lo stesso storage fisico: il vincolo e' che
# ogni superficie abbia artifact_id, owner, stale policy e clear_group centrali.

register_cache_artifact(
    CacheArtifactSpec(
        artifact_id="runtime.orchestration_payload",
        page_id="runtime",
        layer="orchestration_payload",
        level="L1",
        owner="app.get_or_build_orchestration_payload",
        storage="page_artifact",
        version="orchestration-payload-v2",
        dependencies=("portfolio_data_signature", "settings_signature", "cache_bust", "schema_version"),
        clear_group="portfolio",
        stale_policy="rebuild_on_semantic_signature_or_cache_bust",
        log_page="Runtime",
        description="Payload principale dell'orchestrazione dati governato dal registry/page-cache.",
        prebuild=True,
        status="registered_provider",
    )
)

register_cache_artifact(
    CacheArtifactSpec(
        artifact_id="runtime.streamlit_resources",
        page_id="runtime",
        layer="resources",
        level="L0",
        owner="app.get_state_manager/get_app_logger",
        storage="streamlit_cache_resource",
        version="runtime-resources-v1",
        dependencies=("process_lifetime",),
        clear_group="runtime",
        stale_policy="process_lifetime_singleton",
        log_page="Runtime",
        description="Singleton Streamlit per risorse runtime. Da mantenere come eccezione documentata, non come cache dati.",
        prebuild=False,
        status="documented_exception",
    )
)

register_cache_artifact(
    CacheArtifactSpec(
        artifact_id="figures.plotly_cache_provider",
        page_id="shared",
        layer="figure_cache",
        level="L3",
        owner="core.figure_cache.FigureCache",
        storage="figure_cache_manifest_json_gzip",
        version="figure-cache-provider-v1",
        dependencies=("figure_signature", "theme_signature", "charts_settings_signature", "page_mode"),
        clear_group="figures",
        stale_policy="rebuild_on_figure_signature_change",
        log_page="cache",
        description="Provider L3 ufficiale per figure Plotly, governato dal registry e dal manifest figure.",
        prebuild=True,
        status="registered_provider",
    )
)

register_cache_artifact(
    CacheArtifactSpec(
        artifact_id="state.derived_runtime_frames",
        page_id="runtime",
        layer="derived_runtime",
        level="L1",
        owner="core.state.StateManager",
        storage="derived_runtime_pickle",
        version="state-derived-runtime-v1",
        dependencies=("portfolio_data_signature", "history_span_by_ticker", "instrument_signature"),
        clear_group="portfolio",
        stale_policy="rebuild_on_derived_token_change",
        log_page="Runtime",
        description="Cache persistente dei DataFrame derivati dello StateManager, governata da token centrali e diagnostica runtime.",
        prebuild=True,
        status="registered_provider",
    )
)

register_cache_artifact(
    CacheArtifactSpec(
        artifact_id="cashflow.intermediate_indices",
        page_id="shared",
        layer="cashflow_indices",
        level="L2",
        owner="core.cashflow_indices",
        storage="process_memory_lru",
        version="cashflow-indices-cache-v1",
        dependencies=("cashflow_data_signature", "price_frame_signature", "group_map_signature"),
        clear_group="portfolio",
        stale_policy="process_lru_rebuild_on_signature_change",
        log_page="Runtime",
        description="Cache in memoria per indici cashflow intermedi tramite core.runtime_cache.",
        prebuild=True,
        status="registered_provider",
    )
)

register_cache_artifact(
    CacheArtifactSpec(
        artifact_id="benchmark.series_cache",
        page_id="shared",
        layer="benchmark_series",
        level="L1",
        owner="core.finance.get_cached_benchmark_series",
        storage="derived_runtime_pickle",
        version="benchmark-series-cache-v1",
        dependencies=("benchmark_cache_file", "benchmark_ticker", "start_date"),
        clear_group="benchmark",
        stale_policy="rebuild_on_benchmark_signature_change",
        log_page="Runtime",
        description="Cache runtime/disco delle serie benchmark registrata come provider condiviso.",
        prebuild=True,
        status="registered_provider",
    )
)

register_cache_artifact(
    CacheArtifactSpec(
        artifact_id="market_data.lookup_cache",
        page_id="mercati",
        layer="market_lookup",
        level="L0",
        owner="core.market_data",
        storage="runtime_memory_plus_cache_file",
        version="market-lookup-cache-v1",
        dependencies=("isin", "market_registry", "btp_trade_time_cache"),
        clear_group="markets",
        stale_policy="rebuild_on_lookup_or_market_refresh",
        log_page="Mercati",
        description="Cache lookup ticker/orari BTP e dati mercato governata da core.runtime_cache e file di appoggio dedicati.",
        prebuild=False,
        status="registered_provider",
    )
)

register_cache_artifact(
    CacheArtifactSpec(
        artifact_id="analytics.frozen_payload_store",
        page_id="shared",
        layer="frozen_payload_store",
        level="L3",
        owner="core.frozen_analysis_cache/core.analytics_payload_cache",
        storage="analytics_pickle_gzip",
        version="frozen-payload-store-v1",
        dependencies=("payload_type", "analysis_signature", "action_options"),
        clear_group="reports",
        stale_policy="rebuild_on_explicit_action_or_signature_change",
        log_page="Cruscotti",
        description="Store persistente ufficiale delle analisi congelate ad azione esplicita.",
        prebuild=False,
        trigger="explicit_action",
        rerun_policy="no_global_rebuild",
        action_scope="frozen_analysis_only",
        status="registered_provider",
    )
)

register_cache_artifact(
    CacheArtifactSpec(
        artifact_id="prebuild.registry_engine",
        page_id="runtime",
        layer="prebuild",
        level="L3",
        owner="core.cache_prewarmer/ui.prewarm_bundle",
        storage="prewarm_state_plus_registered_artifacts",
        version="registry-prebuild-engine-v1",
        dependencies=("cache_registry", "portfolio_data_signature", "theme_signature", "charts_settings_signature"),
        clear_group="figures",
        stale_policy="prebuild_registered_artifacts_only",
        log_page="PreRender",
        description="Motore prebuild guidato dal registry: prepara solo artefatti dichiarati prebuild e non pesa sul render ordinario.",
        prebuild=False,
        trigger="background_or_explicit_action",
        rerun_policy="no_forced_rerun",
        action_scope="prebuild_only",
        status="pilot",
    )
)
