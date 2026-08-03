"""
core/services — Service layer.

Backward compatibility shim and service layer modules.
Some functions have been migrated to subdirectory modules (reporting, analysis, alerts,
quotes, cruscotti). Legacy functions awaiting migration are defined here.

Pure functions layer - no Streamlit dependencies, no side effects.
"""

# Re-export from subdirectory modules (Phase 2 migrated functions)
from core.services.reporting import (
    build_reporting_compliance_pack,
    render_reporting_compliance_markdown,
)
from core.services.analysis import (
    build_advanced_analysis_data,
    build_pl_delta_series,
    build_weekly_pl_table,
    build_percentage_return_series,
    build_drawdown_series,
    build_monthly_returns,
    build_category_drawdown_series,
    build_category_monthly_returns,
)
from core.services.alerts import build_portfolio_alerts
from core.services.quotes import (
    get_quotazioni_stats,
    get_valid_quote_tickers_by_category,
)
from core.services.instrument_quality import (
    build_instrument_quality_dataset,
    build_price_frame_from_storico,
    compute_trailing_risk_return_metrics,
)
from core.services.accumuli import (
    build_accumuli_analysis,
    simulate_next_installment,
    IMPATTO_RATA_ALTO_PCT,
    IMPATTO_RATA_BASSO_PCT,
    DISTANZA_PAREGGIO_SOGLIA_PCT,
)
from core.services.benchmark import (
    build_benchmark_transparency_payload,
    build_instrument_benchmark_matrix,
    benchmark_explanation,
    resolve_effective_benchmark_components,
)
from core.services.cruscotti import (
    build_portfolio_radar_payload,
    build_category_dashboard_metrics,
    get_portfolio_operations,
    get_cash_movements,
    build_monthly_purchase_spending,
    calcola_proventi_netti,
    build_operations_report,
    estrai_posizioni_aperte_chiuse,
    build_macro_summary_report,
    get_category_allocation_breakdown,
    category_value_pl_items,
)


__all__ = [
    # Re-exported from subdirectories
    "build_reporting_compliance_pack",
    "render_reporting_compliance_markdown",
    "build_portfolio_radar_payload",
    "build_advanced_analysis_data",
    "build_pl_delta_series",
    "build_weekly_pl_table",
    "build_percentage_return_series",
    "build_drawdown_series",
    "build_monthly_returns",
    "build_category_drawdown_series",
    "build_category_monthly_returns",
    "build_portfolio_alerts",
    "get_quotazioni_stats",
    "get_valid_quote_tickers_by_category",
    "build_instrument_quality_dataset",
    "build_price_frame_from_storico",
    "compute_trailing_risk_return_metrics",
    "build_category_dashboard_metrics",
    "get_portfolio_operations",
    "get_cash_movements",
    "build_monthly_purchase_spending",
    "calcola_proventi_netti",
    "build_operations_report",
    "estrai_posizioni_aperte_chiuse",
    "build_macro_summary_report",
    "get_category_allocation_breakdown",
    "category_value_pl_items",
    "build_accumuli_analysis",
    "simulate_next_installment",
    "IMPATTO_RATA_ALTO_PCT",
    "IMPATTO_RATA_BASSO_PCT",
    "DISTANZA_PAREGGIO_SOGLIA_PCT",
    "build_benchmark_transparency_payload",
    "build_instrument_benchmark_matrix",
    "benchmark_explanation",
    "resolve_effective_benchmark_components",
]
