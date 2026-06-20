from __future__ import annotations

import time
from datetime import date
from typing import Any

import pandas as pd

from core.domain.calendar import build_btp_calendar
from core.models import get_registro_eventi, get_proventi_normalizzati
from core.asset_categories import filter_data_by_selected_categories
from core.finance import build_hist_df, build_portfolio_history_df, compute_portfolio_state
from core.price_frames import build_expanded_price_frame
from core.portfolio_metrics import (
    calcola_flussi_capitale,
    calcola_kpi_principali,
    calcola_total_return,
)
from core.quotes_runtime import build_quotes_refresh_df
from core.services import (
    build_macro_summary_report,
    build_operations_report,
    build_portfolio_alerts,
    build_portfolio_radar_payload,
    calcola_proventi_netti,
    category_value_pl_items,
    estrai_posizioni_aperte_chiuse,
    get_category_allocation_breakdown,
    get_quotazioni_stats,
)
from persistence.storage import macro_cat
from ui.formatting import fmt_dt_it, fmtd, fmtds


def build_runtime_context_data(
    *,
    data: dict[str, Any],
    settings: dict[str, Any],
    state_manager,
    theme,
    quotes_log,
    snapshots_state,
    meta_state,
    calculations_settings: dict[str, Any],
    app_version: str,
    schema_version: str,
    logger=None,
) -> dict[str, Any]:
    _t_total = time.perf_counter()
    data = filter_data_by_selected_categories(data, settings)
    if state_manager is not None:
        _t = time.perf_counter()
        state_top = state_manager.get_portfolio_state_for(data)
        if logger: logger.info("[TIMING] get_portfolio_state_for: %.2fs", time.perf_counter() - _t)
        _t = time.perf_counter()
        dfh = state_manager.get_history_df_for(data)
        if logger: logger.info("[TIMING] get_history_df_for: %.2fs", time.perf_counter() - _t)
        _t = time.perf_counter()
        dh_hist = state_manager.get_hist_df_for(data)
        if logger: logger.info("[TIMING] get_hist_df_for: %.2fs", time.perf_counter() - _t)
        _t = time.perf_counter()
        dh_flow = state_manager.get_expanded_price_frame_for(data)
        if logger: logger.info("[TIMING] get_expanded_price_frame_for: %.2fs", time.perf_counter() - _t)
    else:
        state_top = compute_portfolio_state(data, include_closed=True)
        dfh = build_portfolio_history_df(data)
        dh_hist = build_hist_df(data)
        dh_flow = build_expanded_price_frame(data)
    df = state_top.get("df", pd.DataFrame())
    liquidita = float(state_top.get("liquidita", 0.0))

    liquidita = round(liquidita, 2)
    if liquidita == -0.0 or abs(liquidita) < 0.001:
        liquidita = 0.0

    da, dc = estrai_posizioni_aperte_chiuse(df)
    if not da.empty:
        da["Categoria"] = da["Tipo"].apply(macro_cat)

    eventi = get_registro_eventi(data)
    capital_flows = calcola_flussi_capitale(eventi)
    cap_netto = capital_flows["cap_netto"]
    cap_rientrato = capital_flows["cap_rientrato"]

    kpi = calcola_kpi_principali(
        df,
        liquidita,
        capitale_investito=capital_flows["cap_investito"],
    )
    tv, tc, pl, pp, pl_totale = kpi["tv"], kpi["tc"], kpi["pl"], kpi["pp"], kpi["pl_totale"]
    tcm = da["Comm."].sum() if not da.empty else 0.0

    proventi = get_proventi_normalizzati(data)
    prov_netti = calcola_proventi_netti(proventi)
    include_proventi = bool(
        calculations_settings.get(
            "include_proventi_in_total_return",
            settings.get("include_proventi_in_total_return", True),
        )
    )
    prov_netti_for_return = prov_netti if include_proventi else 0.0
    total_ret, total_ret_pct = calcola_total_return(pl_totale, prov_netti_for_return, cap_netto)

    pl_color = theme.colors["success"] if pl_totale >= 0 else theme.colors["danger"]
    tr_color = theme.colors["success"] if total_ret >= 0 else theme.colors["danger"]

    for col in dfh.columns:
        if col.startswith("PL_") and dfh[col].dtype != "float64":
            dfh[col] = dfh[col].astype("float64")

    # chiusi = posizioni con qty=0 che hanno almeno un ACQUISTO in registro
    # (distingue "chiuso" da "osservato" che ha sempre qty=0 ma non ha ACQUISTO)
    _dc_tickers = set(dc["Ticker"].tolist()) if not dc.empty else set()
    _tickers_con_acquisto = {str(ev.get("ticker") or "") for ev in eventi if ev.get("tipo_evento") == "ACQUISTO"}
    chiusi_tickers: frozenset[str] = frozenset(_dc_tickers & _tickers_con_acquisto)

    # active_tickers = tutti gli strumenti TRANNE quelli confermati chiusi
    active_tickers = [
        str(s.get("ticker") or "")
        for s in (data.get("strumenti") or [])
        if str(s.get("ticker") or "") and str(s.get("ticker") or "") not in chiusi_tickers
    ]
    quotes_refresh_df = build_quotes_refresh_df(quotes_log, active_tickers)
    quotazioni_stats = get_quotazioni_stats(quotes_refresh_df)
    category_breakdown = get_category_allocation_breakdown(da, settings)
    category_triplet_items = category_value_pl_items(da, settings)
    portfolio_radar_payload = build_portfolio_radar_payload(
        da,
        liquidita,
        str(settings.get("target_profile_default", "Equilibrato") or "Equilibrato"),
    )
    portfolio_alerts = build_portfolio_alerts(da, settings)

    _t = time.perf_counter()
    ops = build_operations_report(data)
    if logger: logger.info("[TIMING] build_operations_report: %.2fs", time.perf_counter() - _t)
    _t = time.perf_counter()
    macro_rep = build_macro_summary_report(da, tv, settings)
    if logger: logger.info("[TIMING] build_macro_summary_report: %.2fs", time.perf_counter() - _t)
    last_upd = data.get("last_quotes_update")
    if not last_upd:
        cand = [s.get("aggiornato") for s in data.get("strumenti", []) if s.get("aggiornato")]
        if cand:
            last_upd = max(cand)
    hdr_date = f"{fmtd(date.today())} (ultimo aggiornamento quotazioni: {fmt_dt_it(last_upd)})"

    _t = time.perf_counter()
    btp_calendar_df = build_btp_calendar(data)
    if logger: logger.info("[TIMING] build_btp_calendar: %.2fs", time.perf_counter() - _t)

    result = {
        "data": data,
        "settings": settings,
        "da": da,
        "dc": dc,
        "df": df,
        "chiusi_tickers": chiusi_tickers,
        "btp_calendar_df": btp_calendar_df,
        "tv": tv,
        "tc": tc,
        "tcm": tcm,
        "pl": pl,
        "pl_totale": pl_totale,
        "pp": pp,
        "pl_color": pl_color,
        "pl_attuale_posizioni": pl,
        "pl_attuale_color": pl_color,
        "cap": cap_netto,
        "capitale_netto_versato": cap_netto,
        "capitale_rientrato": cap_rientrato,
        "proventi": proventi,
        "proventi_netti_totali": prov_netti,
        "total_return": total_ret,
        "total_return_pct": total_ret_pct,
        "total_return_color": tr_color,
        "patrimonio_totale": kpi["patrimonio_totale"],
        "liquidita_attuale": liquidita,
        "dfh_top": dfh,
        "_dh_hist_shared": dh_hist,
        "_dh_flow_shared": dh_flow,
        "last_quotes_update": last_upd,
        "header_date": hdr_date,
        "quotes_log": quotes_log,
        "quotes_refresh_df": quotes_refresh_df,
        "quotazioni_stats": quotazioni_stats,
        "snapshots_state": snapshots_state,
        "ops_report": ops,
        "macro_summary_report": macro_rep,
        "category_breakdown": category_breakdown,
        "category_triplet_items": category_triplet_items,
        "portfolio_radar_payload": portfolio_radar_payload,
        "portfolio_alerts": portfolio_alerts,
        "capital_flows": capital_flows,
        "calculations_settings": calculations_settings,
        "include_proventi_in_total_return_effective": include_proventi,
        "meta_state": meta_state,
        "app_version": app_version,
        "schema_version": schema_version,
        "dfmt": "%d/%m/%Y",
        "CHART_BG": theme.bg_chart,
        "THEME_PRIMARY": theme.primary_color,
        "FONT_COLOR": theme.font_color,
        "BLUE_ACCENT": theme.color_blue,
        "APP_BG": theme.bg_app,
        "SURFACE_BG": theme.bg_surface,
    }
    if logger is not None:
        logger.info(
            "Orchestrazione completata: strumenti=%s posizioni_aperte=%s liquidita=%.2f — totale=%.2fs",
            len(data.get("strumenti", [])),
            len(da),
            liquidita,
            time.perf_counter() - _t_total,
        )
    return result
