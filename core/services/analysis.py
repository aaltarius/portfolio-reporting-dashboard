"""
core/services/analysis.py — Analysis and charting services.

Functions for building analysis data, returns series, and performance charts.
Pure functions - no Streamlit dependencies, no side effects.
"""
from typing import Any, List, Dict
import numpy as np
import pandas as pd
from core.asset_categories import ACTIVE_CATEGORY_CODES, get_selected_category_codes
from core.data_models import ThemeConfig


def build_pl_delta_series(df_history: pd.DataFrame, theme: ThemeConfig) -> dict[str, list[Any]]:
    """
    Builds P/L delta series for the home daily bar chart.

    Uses per-instrument PL_ columns to compute the daily delta, including only
    instruments that have valid (non-NaN) values in BOTH the current and previous
    row. This excludes the price-jump caused by instrument closings (RIMBORSO A
    SCADENZA / VENDITA) between the last storico entry and today's synthetic row.

    Falls back to df_history["P/L"].diff() when no PL_ columns exist.
    """
    from core.formatting import fmt_num_it

    if df_history.empty or "P/L" not in df_history.columns:
        return {"deltas": [], "colors": [], "delta_text": []}

    pl_cols = [c for c in df_history.columns if c.startswith("PL_")]
    n = len(df_history)

    if pl_cols:
        deltas: list[float] = [float("nan")] * n
        for i in range(1, n):
            curr = df_history.iloc[i]
            prev = df_history.iloc[i - 1]
            # Only count instruments open (non-NaN) in BOTH rows.
            # Instruments that closed between prev and curr have NaN in curr → skipped.
            delta = sum(
                float(curr[col]) - float(prev[col])
                for col in pl_cols
                if pd.notna(curr[col]) and pd.notna(prev[col])
            )
            deltas[i] = delta
        delta_prev = pd.Series(deltas, index=df_history.index, dtype=float)
    else:
        delta_prev = df_history["P/L"].diff()

    colors = [
        theme.color_green if (pd.isna(v) or v >= 0) else theme.color_red
        for v in delta_prev
    ]
    delta_text = [
        "" if pd.isna(v) else fmt_num_it(v, 0, signed=True)
        for v in delta_prev
    ]

    return {
        "deltas": delta_prev.tolist(),
        "colors": colors,
        "delta_text": delta_text,
    }


def build_weekly_pl_table(
    da: pd.DataFrame, dfh_top: pd.DataFrame, data: dict[str, Any], max_days: int = 7
) -> dict[str, Any] | None:
    """Per-instrument daily P/L deltas for the last `max_days` real trading days.

    Same PL_<ticker> delta methodology as build_pl_delta_series, broken out
    per instrument (rows of `da`) instead of summed across the portfolio.
    Drops a trailing synthetic "today" row (added by build_portfolio_history_df
    on non-trading days) that isn't backed by a real storico_prezzi date.
    """
    if da is None or da.empty or dfh_top is None or len(dfh_top) < 2:
        return None

    window_source = dfh_top
    real_dates = set((data or {}).get("storico_prezzi", {}).keys())
    if real_dates:
        last_date_str = pd.to_datetime(window_source.iloc[-1]["Data"]).strftime("%Y-%m-%d")
        if last_date_str not in real_dates:
            window_source = window_source.iloc[:-1]
    if len(window_source) < 2:
        return None

    window = window_source.tail(max_days + 1).reset_index(drop=True)
    n_days = len(window) - 1
    if n_days < 1:
        return None

    days = [
        pd.to_datetime(window.iloc[i + 1]["Data"]).strftime("%d/%m")
        for i in range(n_days)
    ]

    rows: list[dict[str, Any]] = []
    day_totals = [0.0] * n_days
    grand_total = 0.0
    for _, pos in da.iterrows():
        tk = str(pos.get("Ticker", ""))
        col = f"PL_{tk}"
        deltas: list[float | None] = []
        totale = 0.0
        for i in range(n_days):
            if col not in window.columns:
                deltas.append(None)
                continue
            prev_v = window.iloc[i].get(col)
            curr_v = window.iloc[i + 1].get(col)
            if pd.notna(prev_v) and pd.notna(curr_v):
                delta = float(curr_v) - float(prev_v)
                deltas.append(delta)
                totale += delta
                day_totals[i] += delta
            else:
                deltas.append(None)
        grand_total += totale
        rows.append({
            "ticker": tk,
            "strumento": str(pos.get("Strumento", tk)),
            "tipo": str(pos.get("Tipo", "")),
            "quote": float(pos.get("Quote", 0) or 0),
            "deltas": deltas,
            "totale": totale,
        })

    return {
        "days": days,
        "rows": rows,
        "day_totals": day_totals,
        "grand_total": grand_total,
    }


def build_percentage_return_series(df_history: pd.DataFrame, data=None) -> dict[str, Any]:
    """
    Calculates percentage return series relative to net capital and cost.

    FORMULA CORRETTA: (Valore - Capitale) / Capitale × 100
    Non dipende dai versamenti PAC.

    Args:
        df_history: DataFrame with columns: Data, Valore, Capitale, Costo
        data: portafoglio data (optional, per compatibilità)

    Returns:
        Dict con:
        - pct_cap: rendimento % rispetto al capitale netto versato
        - pct_cost: rendimento % rispetto al costo totale
        - dates: date serializzate come stringhe
    """
    if df_history is None or df_history.empty:
        return {
            "pct_cap": [],
            "pct_cost": [],
            "dates": [],
        }

    df = df_history.copy()
    # CORREZIONE: (Valore - Capitale) / Capitale, non Valore / Capitale
    pct_cap = ((df["Valore"] - df["Capitale"]) / df["Capitale"].replace(0, np.nan)) * 100
    pct_cost = ((df["Valore"] - df["Costo"]) / df["Costo"].replace(0, np.nan)) * 100
    dates = [d.strftime("%Y-%m-%d") if hasattr(d, 'strftime') else str(d) for d in df["Data"]]

    return {
        "pct_cap": pct_cap.fillna(0).tolist(),
        "pct_cost": pct_cost.fillna(0).tolist(),
        "dates": dates,
    }


def build_drawdown_series(values: List[float]) -> List[float]:
    """
    Calculates maximum drawdown at each point in portfolio history.

    Args:
        values: List of portfolio rendimento percentuale (ad es [-2.97, -3.44, ..., +2.07])
                oppure valori assoluti (lista di numeri).
                Se i numeri sono piccoli (-10 a +10) si interpreta come percentuale decimale.

    Returns:
        List of drawdown percentages (sempre ≤ 0) at each point
    """
    if not values or len(values) == 0:
        return []

    s = pd.Series(values)
    s_clean = s.replace(0, np.nan)
    if s_clean.dropna().empty:
        return [0.0] * len(values)

    # Interpreta i valori come rendimenti percentuali decimali (-2.97 = -2,97%)
    # e converte in equity curve: eq = 1.0 + (r / 100)
    # Poi calcola drawdown normalizzato: (eq - eq_max) / eq_max
    equity_curve = 1.0 + (s / 100.0)
    eq_running_max = equity_curve.expanding().max()
    drawdown = ((equity_curve - eq_running_max) / eq_running_max) * 100

    return drawdown.fillna(0).tolist()


def build_monthly_returns(df_history: pd.DataFrame, data=None) -> dict[str, list[Any]]:
    """
    Calculates monthly returns grouped by calendar month.

    FORMULA: (Valore_fine_mese - Valore_inizio_mese) / Valore_inizio_mese × 100
    Esclude l'effetto dei versamenti PAC.

    Args:
        df_history: DataFrame with columns: Data, Valore, Capitale
        data: portafoglio data (optional, per compatibilità)

    Returns:
        Dict con:
        - months: mesi nel formato "YYYY-MM"
        - returns: rendimenti mensili percentuali
    """
    if df_history is None or df_history.empty:
        return {
            "months": [],
            "returns": [],
        }

    df = df_history.copy()
    df["Data"] = pd.to_datetime(df["Data"])
    df = df.sort_values("Data").reset_index(drop=True)
    df["Mese"] = df["Data"].dt.to_period("M")

    # Curva del rendimento netto cumulato: (Valore - Capitale) / Capitale.
    # Rendimento del singolo mese: (1 + r_fine) / (1 + r_inizio) - 1
    # con r_inizio = ultimo punto del mese precedente (0 per il primo mese del portafoglio).
    # Garantisce che il prodotto composto dei rendimenti mensili coincida con il TWR totale.
    cap_s = pd.to_numeric(df["Capitale"], errors="coerce")
    val_s = pd.to_numeric(df["Valore"], errors="coerce")
    df["_rcum"] = ((val_s - cap_s) / cap_s.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)

    monthly_returns = []
    for mese, grp in df.groupby("Mese"):
        if grp.empty:
            continue
        rcum_end = grp["_rcum"].iloc[-1]
        if pd.isna(rcum_end):
            continue
        pos_first = grp.index[0]
        if pos_first > 0:
            rcum_prev = df["_rcum"].iloc[pos_first - 1]
            if pd.isna(rcum_prev):
                rcum_prev = 0.0
        else:
            rcum_prev = 0.0
        denom = 1.0 + float(rcum_prev)
        if denom == 0:
            continue
        ret_m = ((1.0 + float(rcum_end)) / denom - 1.0) * 100
        monthly_returns.append({
            "mese": str(mese),
            "ret": ret_m,
        })

    months = [m["mese"] for m in monthly_returns]
    returns = [m["ret"] for m in monthly_returns]

    return {
        "months": months,
        "returns": returns,
    }


def build_category_drawdown_series(
    dfh: pd.DataFrame, category: str, category_tickers: list[str],
    category_df: pd.DataFrame = None, first_op_date=None
) -> list[float]:
    """Calcola il drawdown per una categoria dai rendimenti percentuali."""
    if dfh is None or dfh.empty or not category_tickers:
        return []

    # Filtra i dati da first_op_date se fornito
    dfh_work = dfh.copy()
    if first_op_date is not None:
        dates = pd.to_datetime(dfh_work.get("Data", []), errors="coerce")
        mask = dates >= pd.Timestamp(first_op_date)
        dfh_work = dfh_work[mask].copy()

    if dfh_work.empty:
        return []

    # Somma il P/L della categoria per ogni data
    pl_cols = [col for col in dfh_work.columns if col.startswith("PL_") and col[3:] in category_tickers]
    if not pl_cols:
        return []

    pl_series = pd.to_numeric(dfh_work[pl_cols].fillna(0).sum(axis=1), errors="coerce")

    # Calcola il costo totale della categoria (base per rendimento percentuale)
    category_cost = 0.0
    if category_df is not None and "Costo" in category_df.columns:
        category_cost = float(pd.to_numeric(category_df["Costo"], errors="coerce").fillna(0).sum())

    if category_cost <= 0:
        return []

    # Calcola i rendimenti percentuali: P/L / costo × 100
    pct_returns = (pl_series / category_cost) * 100

    # Calcola il drawdown dai rendimenti percentuali
    return build_drawdown_series(pct_returns.tolist())


def build_category_monthly_returns(
    dfh: pd.DataFrame, category: str, category_tickers: list[str],
    category_df: pd.DataFrame = None, first_op_date=None
) -> dict[str, list]:
    """Calcola i rendimenti mensili percentuali per una categoria."""
    if dfh is None or dfh.empty or not category_tickers:
        return {"months": [], "returns": []}

    # Filtra i dati da first_op_date se fornito
    dfh_work = dfh.copy()
    if first_op_date is not None:
        dates = pd.to_datetime(dfh_work.get("Data", []), errors="coerce")
        mask = dates >= pd.Timestamp(first_op_date)
        dfh_work = dfh_work[mask].copy()

    if dfh_work.empty:
        return {"months": [], "returns": []}

    # Calcola il costo totale della categoria (base per rendimento percentuale)
    category_cost = 0.0
    if category_df is not None and "Costo" in category_df.columns:
        category_cost = float(pd.to_numeric(category_df["Costo"], errors="coerce").fillna(0).sum())

    if category_cost <= 0:
        return {"months": [], "returns": []}

    # Somma il P/L della categoria per ogni data
    pl_cols = [col for col in dfh_work.columns if col.startswith("PL_") and col[3:] in category_tickers]
    if not pl_cols:
        return {"months": [], "returns": []}

    pl_series = pd.to_numeric(dfh_work[pl_cols].fillna(0).sum(axis=1), errors="coerce")

    # Calcola i rendimenti percentuali: P/L / costo × 100
    pct_returns = (pl_series / category_cost) * 100

    # Raggruppa per mese e calcola i rendimenti mensili
    dfh_work["Data"] = pd.to_datetime(dfh_work["Data"])
    dfh_work["Mese"] = dfh_work["Data"].dt.to_period("M")
    dfh_work["pct_ret"] = pct_returns.values

    monthly_returns = []

    for mese, grp in dfh_work.groupby("Mese"):
        if grp.empty:
            continue

        # Rendimento alla fine del mese vs. inizio del mese
        pct_end = grp["pct_ret"].iloc[-1]
        pct_start = grp["pct_ret"].iloc[0]

        if pd.isna(pct_end) or pd.isna(pct_start):
            pct_end = grp["pct_ret"].iloc[-1] if not pd.isna(grp["pct_ret"].iloc[-1]) else 0.0
            pct_start = 0.0 if grp.index[0] == 0 else 0.0

        # Rendimento mensile come differenza percentuale
        ret_m = pct_end - pct_start

        monthly_returns.append({
            "mese": str(mese),
            "ret": float(ret_m),
        })

    months = [m["mese"] for m in monthly_returns]
    returns = [m["ret"] for m in monthly_returns]

    return {
        "months": months,
        "returns": returns,
    }


def build_advanced_analysis_data(
    data: dict[str, Any],
    da: pd.DataFrame,
    dh: pd.DataFrame,
    dh_flow: pd.DataFrame,
    proventi: list[dict[str, Any]],
    settings: dict[str, Any] | None = None,
    recent_window: int = 92,
) -> dict[str, Any]:
    """
    Prepara i dataset analitici avanzati usati dalla tab Analisi.

    Centralizza selezione strumenti, metriche rischio/rendimento, IRR,
    rendimenti normalizzati, correlazioni e contributo al rischio.

    Returns:
        Dict con:
        - positions/info_map/ta per il mapping strumenti
        - dfstats e irr_results per le metriche sintetiche
        - analysis_returns, cat_flow_returns, corr, corr_cat per i rendimenti
        - risk_df e cat_index_analysis per le viste di rischio e categoria
    """
    from persistence.storage import macro_cat
    from core.cashflow_indices import build_group_cashflow_indices
    from core.series_utils import build_category_return_index, slice_recent, get_current_position_start_dates
    from core.finance import (
        calc_positions,
        build_analysis_returns,
        compute_instrument_stats,
        build_risk_contribution_table,
        compute_xirr,
        build_xirr_flows,
    )
    empty_result = {
        "positions": {},
        "info_map": {},
        "ta": [],
        "dfstats": pd.DataFrame(),
        "irr_results": {},
        "analysis_returns": pd.DataFrame(),
        "cat_flow_returns": pd.DataFrame(),
        "risk_df": pd.DataFrame(),
        "cat_index_analysis": pd.DataFrame(),
        "corr": pd.DataFrame(),
        "corr_cat": pd.DataFrame(),
    }
    recent_window = max(30, int(recent_window))
    if dh is None or dh.empty or len(dh) < 3:
        return empty_result

    strumenti = data.get("strumenti", [])
    positions = calc_positions(data)
    position_starts = get_current_position_start_dates(data, positions)
    info_map = {s["ticker"]: s for s in strumenti}
    ta = [
        s["ticker"] for s in strumenti
        if s["ticker"] in dh.columns
        and dh[s["ticker"]].notna().sum() >= 3
        and positions.get(s["ticker"], {}).get("qty", 0) > 0.0001
    ]

    if not ta:
        return {**empty_result, "positions": positions, "info_map": info_map}

    stats = []
    for tk in ta:
        p = dh[tk].dropna()
        metrics = compute_instrument_stats(p, start_date=position_starts.get(tk))
        if not metrics:
            continue
        stats.append({
            "Ticker": tk,
            "Strumento": info_map.get(tk, {}).get("nome", tk),
            "Tipologia": macro_cat(info_map.get(tk, {}).get("tipo", "")),
            **metrics,
        })
    dfstats = pd.DataFrame(stats) if stats else pd.DataFrame()

    irr_cat_tickers: dict[str, list[str]] = {}
    for tk in ta:
        cat = macro_cat(info_map.get(tk, {}).get("tipo", ""))
        irr_cat_tickers.setdefault(cat, []).append(tk)

    visible_categories = list(get_selected_category_codes(settings)) if settings is not None else list(ACTIVE_CATEGORY_CODES)
    irr_results = {}
    f_tot, d_tot = build_xirr_flows(data, da, proventi, tickers=None)
    irr_results["Portafoglio"] = compute_xirr(f_tot, d_tot)
    for cat in visible_categories:
        tks_cat = irr_cat_tickers.get(cat, [])
        if tks_cat:
            f_c, d_c = build_xirr_flows(data, da, proventi, tickers=tks_cat)
            irr_results[cat] = compute_xirr(f_c, d_c)
        else:
            irr_results[cat] = None

    analysis_returns = build_analysis_returns(dh, ta)
    corr = (
        analysis_returns.corr(min_periods=2)
        if not analysis_returns.empty and len(analysis_returns.columns) > 1
        else pd.DataFrame()
    )

    cat_map = {tk: macro_cat(info_map[tk]["tipo"]) for tk in ta}
    cat_group_map: Dict[str, List[str]] = {}
    for tk in ta:
        cat = cat_map[tk]
        cat_group_map.setdefault(cat, []).append(tk)

    _, cat_flow_returns, _, _ = build_group_cashflow_indices(data, dh_flow, cat_group_map)
    cat_flow_returns = (
        slice_recent(cat_flow_returns.dropna(how="all"), recent_window)
        if not cat_flow_returns.empty
        else pd.DataFrame()
    )
    if not cat_flow_returns.empty:
        available_visible_categories = [
            cat for cat in visible_categories
            if cat in cat_flow_returns.columns
        ]
        cat_flow_returns = cat_flow_returns.loc[:, available_visible_categories]
    corr_cat = (
        cat_flow_returns.corr(min_periods=2)
        if not cat_flow_returns.empty and cat_flow_returns.shape[1] > 1
        else pd.DataFrame()
    )

    risk_df = build_risk_contribution_table(da, analysis_returns)
    cat_index_analysis = build_category_return_index(dh, data, settings=settings, positions=positions)

    return {
        "positions": positions,
        "info_map": info_map,
        "ta": ta,
        "dfstats": dfstats,
        "irr_results": irr_results,
        "analysis_returns": analysis_returns,
        "cat_flow_returns": cat_flow_returns,
        "risk_df": risk_df,
        "cat_index_analysis": cat_index_analysis,
        "corr": corr,
        "corr_cat": corr_cat,
    }

# build_analysis_overview_html rimossa il 2026-07-07: nessun chiamante nell'app
# (il suo unico consumatore, ui/runtime_context.py, era gia' stato ripulito in
# precedenza — vedi tests/test_dead_code_removal.py — ma la funzione stessa e
# il suo re-export in core/services/__init__.py erano rimasti).
