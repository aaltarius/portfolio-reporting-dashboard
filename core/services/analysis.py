"""
core/services/analysis.py — Analysis and charting services.

Functions for building analysis data, returns series, and performance charts.
Pure functions - no Streamlit dependencies, no side effects.
"""
from typing import Any, List, Dict
import numpy as np
import pandas as pd
from core.asset_categories import ACTIVE_CATEGORY_CODES, get_selected_category_codes
from core.constants import QTY_ZERO_EPS
from core.data_models import ThemeConfig
from core.domain.risk import build_drawdown_series, build_category_drawdown_series


def split_eligible_and_excluded_tickers(
    strumenti: list[dict[str, Any]],
    dh: pd.DataFrame,
    positions: dict[str, dict[str, float]],
) -> tuple[list[str], list[str]]:
    """Separa i ticker posseduti in idonei/esclusi per il calcolo statistico.

    Idoneo: posseduto (qty > 0), presente in dh, con almeno 3 quotazioni
    valide — sotto questa soglia volatilita'/correlazione non sono
    calcolabili in modo significativo (non e' un bug da correggere
    abbassando la soglia).

    Escluso-per-storico-insufficiente: posseduto ma non idoneo. Va sempre
    segnalato all'utente (bug reale, 2026-08-20: uno strumento appena
    acquistato spariva in silenzio da tabella metriche avanzate e grafico
    contributo al rischio senza alcuna indicazione del perche').

    Ritorna (ta, excluded_insufficient_history), entrambi ordinati.
    """
    ta = [
        s["ticker"] for s in strumenti
        if s["ticker"] in dh.columns
        and dh[s["ticker"]].notna().sum() >= 3
        and positions.get(s["ticker"], {}).get("qty", 0) > QTY_ZERO_EPS
    ]
    ta_set = set(ta)
    excluded_insufficient_history = sorted(
        s["ticker"] for s in strumenti
        if positions.get(s["ticker"], {}).get("qty", 0) > QTY_ZERO_EPS
        and s["ticker"] not in ta_set
    )
    return ta, excluded_insufficient_history


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
        pl_values = df_history[pl_cols].apply(pd.to_numeric, errors="coerce")
        valid_pair = pl_values.notna() & pl_values.shift(1).notna()
        # Stessa regola del vecchio loop, ma vettoriale: uno strumento contribuisce
        # solo se ha P/L valido sia nel giorno corrente sia nel precedente.
        delta_prev = pl_values.diff().where(valid_pair).sum(axis=1, min_count=0)
        delta_prev.iloc[0] = np.nan
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


_WEEKDAY_INITIALS_IT = {0: "L", 1: "M", 2: "M", 3: "G", 4: "V", 5: "S", 6: "D"}


def build_weekly_pl_table(
    da: pd.DataFrame, dfh_top: pd.DataFrame, data: dict[str, Any], max_days: int = 7
) -> dict[str, Any] | None:
    """Per-instrument daily P/L deltas for the last `max_days` real trading days.

    Same PL_<ticker> delta methodology as build_pl_delta_series, broken out
    per instrument instead of summed across the portfolio. Drops a trailing
    synthetic "today" row (added by build_portfolio_history_df on non-trading
    days) that isn't backed by a real storico_prezzi date.

    `da` (posizioni APERTE oggi) da' nome/tipo/quote per la maggior parte
    delle righe, ma NON basta da sola per i totali: uno strumento chiuso
    (venduto o rimborsato) DENTRO la finestra osservata ha comunque generato
    P/L nei giorni in cui era ancora aperto, e quel contributo deve restare
    nel totale — altrimenti "Andamento dell'ultima settimana" mostrerebbe un
    totale che non include un movimento reale avvenuto in quei giorni. Per
    questo si aggiunge una riga anche per ogni ticker con una colonna
    PL_<ticker> valida nella finestra ma assente da `da` (chiuso durante o
    poco prima della finestra), pescando nome/tipo da data["strumenti"]."""
    if da is None or dfh_top is None or len(dfh_top) < 2:
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

    day_dates = [pd.to_datetime(window.iloc[i + 1]["Data"]) for i in range(n_days)]
    days = [
        f"{_WEEKDAY_INITIALS_IT[d.weekday()]} {d.strftime('%d/%m')}"
        for d in day_dates
    ]
    week_gap_before = [
        i > 0 and day_dates[i - 1].weekday() == 4 and day_dates[i].weekday() == 0
        for i in range(n_days)
    ]

    def _compute_deltas(col: str) -> tuple[list[float | None], float]:
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
            else:
                deltas.append(None)
        return deltas, totale

    rows: list[dict[str, Any]] = []
    day_totals = [0.0] * n_days
    grand_total = 0.0
    open_tickers: set[str] = set()
    if da is not None and not da.empty:
        for _, pos in da.iterrows():
            tk = str(pos.get("Ticker", ""))
            open_tickers.add(tk)
            deltas, totale = _compute_deltas(f"PL_{tk}")
            for i, delta in enumerate(deltas):
                if delta is not None:
                    day_totals[i] += delta
            grand_total += totale
            rows.append({
                "ticker": tk,
                "strumento": str(pos.get("Strumento", tk)),
                "tipo": str(pos.get("Tipo", "")),
                "quote": float(pos.get("Quote", 0) or 0),
                "chiuso": False,
                "deltas": deltas,
                "totale": totale,
            })

    info_map = {str(s.get("ticker") or ""): s for s in (data or {}).get("strumenti", []) or []}
    pl_cols_in_window = [c for c in window.columns if c.startswith("PL_")]
    for col in pl_cols_in_window:
        tk = col[len("PL_"):]
        if not tk or tk in open_tickers:
            continue
        deltas, totale = _compute_deltas(col)
        if not any(d is not None for d in deltas):
            continue
        strumento_info = info_map.get(tk, {})
        for i, delta in enumerate(deltas):
            if delta is not None:
                day_totals[i] += delta
        grand_total += totale
        rows.append({
            "ticker": tk,
            "strumento": str(strumento_info.get("nome") or tk),
            "tipo": str(strumento_info.get("tipo") or ""),
            "quote": 0.0,
            "chiuso": True,
            "deltas": deltas,
            "totale": totale,
        })

    if not rows:
        return None

    return {
        "days": days,
        "week_gap_before": week_gap_before,
        "rows": rows,
        "day_totals": day_totals,
        "grand_total": grand_total,
    }


def build_percentage_return_series(df_history: pd.DataFrame, data=None) -> dict[str, Any]:
    """
    Calculates percentage return series relative to net capital and cost.

    FORMULA CORRETTA: (Valore - Capitale) / Capitale × 100
    Non dipende dai versamenti PAC.

    pct_cost usa "ValoreAperto" (solo posizioni aperte) al numeratore, non
    "Valore" (che include tutta la liquidita', anche quella incassata da
    vendite passate): "Costo" al denominatore e' gia' il costo delle sole
    posizioni aperte, quindi il numeratore deve restare comparabile. Usare
    "Valore" avrebbe fatto schizzare il rapporto dopo qualunque vendita,
    perche' il ricavato resta in "Valore" mentre il relativo costo esce da
    "Costo" — due quantita' non piu' confrontabili tra loro.

    Args:
        df_history: DataFrame with columns: Data, Valore, ValoreAperto,
            Capitale, Costo (ValoreAperto assente su dati storici molto
            vecchi: fallback su Valore per compatibilita')
        data: portafoglio data (optional, per compatibilità)

    Returns:
        Dict con:
        - pct_cap: rendimento % rispetto al capitale netto versato
        - pct_cost: rendimento % (non realizzato) rispetto al costo delle
          sole posizioni ancora aperte
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
    valore_aperto = df["ValoreAperto"] if "ValoreAperto" in df.columns else df["Valore"]
    pct_cost = ((valore_aperto - df["Costo"]) / df["Costo"].replace(0, np.nan)) * 100
    dates = [d.strftime("%Y-%m-%d") if hasattr(d, 'strftime') else str(d) for d in df["Data"]]

    return {
        "pct_cap": pct_cap.fillna(0).tolist(),
        "pct_cost": pct_cost.fillna(0).tolist(),
        "dates": dates,
    }


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
        "excluded_insufficient_history": [],
    }
    recent_window = max(30, int(recent_window))
    if dh is None or dh.empty or len(dh) < 3:
        return empty_result

    strumenti = data.get("strumenti", [])
    positions = calc_positions(data)
    position_starts = get_current_position_start_dates(data, positions)
    info_map = {s["ticker"]: s for s in strumenti}
    ta, excluded_insufficient_history = split_eligible_and_excluded_tickers(strumenti, dh, positions)

    if not ta:
        return {
            **empty_result,
            "positions": positions,
            "info_map": info_map,
            "excluded_insufficient_history": excluded_insufficient_history,
        }

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
        "excluded_insufficient_history": excluded_insufficient_history,
    }

# build_analysis_overview_html rimossa il 2026-07-07: nessun chiamante nell'app
# (il suo unico consumatore, ui/runtime_context.py, era gia' stato ripulito in
# precedenza — vedi tests/test_dead_code_removal.py — ma la funzione stessa e
# il suo re-export in core/services/__init__.py erano rimasti).
