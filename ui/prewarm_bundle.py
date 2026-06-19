from __future__ import annotations

import time
from typing import Any

import pandas as pd

from core.render_profiler import persist_pre_render_event, record_render_event


def run_prewarm_bundle(
    *,
    ctx: Any,
    theme: Any,
    settings: dict,
    figure_cache: Any,
    strategy: Any,
    prewarm_signature: str,
    data_sig: str,
    theme_sig: str,
    charts_settings_sig: str,
    write_state,
) -> dict:
    from ui.dashboard_bundles import get_analitica_bundle
    from ui.charts.home import build_concentration_chart
    from ui.charts.settings import apply_settings

    data = ctx.data
    dfh = ctx.dfh_top
    dfmt = ctx.dfmt
    stats = {"attempted": 0, "built": 0, "cache_hits": 0, "skipped": 0, "errors": 0}

    def _record(step: str, elapsed: float, *, status: str = "OK", detail: str = "", count: int | None = None) -> None:
        try:
            record_render_event("PreRender", step, elapsed, status=status, detail=detail, count=count)
        except Exception:
            pass
        try:
            persist_pre_render_event(prewarm_signature, "PreRender", step, elapsed, status=status, detail=detail, count=count)
        except Exception:
            return

    if dfh is None or dfh.empty:
        stats["skipped"] += 1
        _record("skipped", 0.0, status="SKIP", detail="dfh_top vuoto")
        write_state(time.time(), prewarm_signature)
        return stats

    # Pre-warma tutte le figure del bundle Analitica (cruscotti tab).
    # Usando DISK_ONLY strategy le figure vengono salvate su disco con le stesse
    # chiavi che get_analitica_bundle cercherà al primo accesso alla tab.
    # In precedenza il prewarm costruiva figure con firme diverse (data_sig globale
    # vs cat_data_sig per drawdown/monthly_returns) oppure figure di pagine rimosse
    # dal codebase (andamento.py) — nessuna di quelle veniva trovata dal render normale.
    stats["attempted"] += 1
    started_at = time.perf_counter()
    try:
        get_analitica_bundle(
            dfh_top=dfh,
            da=getattr(ctx, "da", pd.DataFrame()),
            data=data,
            settings=settings,
            data_sig=data_sig,
            theme_sig=theme_sig,
            charts_settings_sig=charts_settings_sig,
            cache_strategy=strategy,
            theme=theme,
            dfmt=dfmt,
            pl_color=getattr(ctx, "pl_color", "#2ECC71"),
            pl_totale=float(getattr(ctx, "pl_totale", 0.0) or 0.0),
            radar_payload=getattr(ctx, "portfolio_radar_payload", None),
            dh_hist=getattr(ctx, "_dh_hist_shared", None),
            dh_flow=getattr(ctx, "_dh_flow_shared", None),
            proventi=getattr(ctx, "proventi", None),
            schema_version=str(getattr(ctx, "schema_version", "n/d")),
            app_version=str(getattr(ctx, "app_version", "n/d")),
        )
        elapsed = time.perf_counter() - started_at
        stats["built"] += 1
        _record("built", elapsed, detail=f"scope=analitica_bundle | sig={prewarm_signature}")
    except Exception as exc:
        elapsed = time.perf_counter() - started_at
        stats["errors"] += 1
        _record("error", elapsed, status="ERRORE", detail=f"get_analitica_bundle: {type(exc).__name__}: {exc}")

    # Pre-warma home_concentration (altrimenti sempre miss: reason=cache_mai_popolata)
    da = getattr(ctx, "da", pd.DataFrame())
    if not isinstance(da, pd.DataFrame):
        da = pd.DataFrame()
    tv = float(da["Controvalore"].sum()) if (not da.empty and "Controvalore" in da.columns) else 0.0
    _da_snap, _tv_snap = da, tv
    figure_cache.get_or_build(
        chart_id="home_concentration",
        data_sig=data_sig,
        theme_sig=theme_sig,
        charts_settings_sig=charts_settings_sig,
        builder=lambda: apply_settings(
            build_concentration_chart(_da_snap, _tv_snap, theme, settings=settings),
            "home_concentration",
        ),
        extra_params={"items": len(da), "tv": round(tv, 2)},
        strategy=strategy,
    )

    write_state(time.time(), prewarm_signature)
    return stats
