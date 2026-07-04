"""
core/finance.py — Logica finanziaria centrale.
"""
import hashlib
import json
import logging
import os
import re
from collections import defaultdict
from datetime import datetime, date
from typing import Any

logger = logging.getLogger(__name__)

import numpy as np
import pandas as pd
import yfinance as yf
from core.asset_categories import ACTIVE_CATEGORY_CODES, get_selected_category_codes
from core.portfolio_metrics import calcola_flussi_capitale, calcola_kpi_principali
from core.render_profiler import profile_step, record_render_event
import time

from persistence.storage import (
    DATA_DIR,
    _safe_float,
    _event_sort_key,
    get_registro_eventi,
    _serialize_df_for_cache,
    _restore_df_from_cache,
    _portfolio_state_signature,
    _rebuild_cash_ledger_from_events,
    _normalize_event_record,
    _new_event_id,
    SCHEMA_VERSION,
    BENCH,
    macro_cat,
    _normalize_macro_label,
    default_settings,
    save_data,
)
from core.validation import validate_evento_portafoglio
from core.benchmark_registry import resolve_instrument_benchmark

# ══════════════════════════════════════════════════════════════════════════════
# Re-exports from core/domain modules (backward compatibility shim)
# Functions have been migrated to domain-specific modules
# ══════════════════════════════════════════════════════════════════════════════

from core.domain.positions import (
    compute_portfolio_state,
    calc_positions,
    build_ptf_df,
    get_cash_balance,
)
from core.series_utils import build_category_return_index
from core.domain.cashflows import compute_xirr, build_xirr_flows
from core.domain.returns import (
    build_analysis_returns,
    compute_instrument_stats,
    _build_summary_return_curve,
    _period_returns_from_curve,
)
from core.domain.risk import build_drawdown_series

__all__ = [
    # Migrated to domain
    "compute_portfolio_state",
    "calc_positions",
    "build_ptf_df",
    "get_cash_balance",
    "compute_xirr",
    "build_xirr_flows",
    "build_analysis_returns",
    "compute_instrument_stats",
    "_build_summary_return_curve",
    "_period_returns_from_curve",
    "build_drawdown_series",
    # Remaining unmigrated functions
    "append_evento_portafoglio",
    "build_hist_df",
    "build_portfolio_history_df",
    "_apply_event_to_pos",
    "_fmt_dt",
]

# ══════════════════════════════════════════════════════════════════════════════
# Utilità private
# ══════════════════════════════════════════════════════════════════════════════

_EPS = 1e-12
EventDict = dict[str, Any]


def _resolve_finance_category_codes(settings: dict[str, Any] | None = None) -> list[str]:
    if settings is None:
        return list(ACTIVE_CATEGORY_CODES)
    return list(get_selected_category_codes(settings))


def _build_category_value_maps(
    da_frame: pd.DataFrame,
    total_value: float,
    categories: list[str],
) -> tuple[dict[str, float], dict[str, float]]:
    macro_alloc = {cat: 0.0 for cat in categories}
    macro_values = {cat: 0.0 for cat in categories}
    if da_frame is None or da_frame.empty or total_value <= 0:
        return macro_alloc, macro_values

    tmp = da_frame.copy()
    tmp["Categoria"] = tmp["Tipo"].apply(macro_cat)
    macro = tmp.groupby("Categoria")["Controvalore"].sum().reindex(categories).fillna(0.0)
    macro_values = {k: float(v) for k, v in macro.items()}
    macro_alloc = {k: float(v / total_value) if total_value > 0 else 0.0 for k, v in macro.items()}
    return macro_alloc, macro_values


def _build_category_history_records(cat_idx: pd.DataFrame, categories: list[str]) -> list[dict[str, Any]]:
    if cat_idx is None or cat_idx.empty:
        return []
    records: list[dict[str, Any]] = []
    for idx, row in cat_idx.sort_index().iterrows():
        payload = {"data": pd.to_datetime(idx).strftime("%d/%m/%Y")}
        for cat in categories:
            payload[cat] = float(row.get(cat)) if pd.notna(row.get(cat)) else None
        records.append(payload)
    return records


def _fmt_dt(value: Any) -> str:
    """Formattazione data per uso interno (senza dipendenza da ui.formatting)."""
    if not value:
        return "n/d"
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                value = datetime.strptime(value[:19], fmt)
                break
            except Exception:
                continue
    if hasattr(value, "day"):
        return f"{value.day:02d}/{value.month:02d}/{value.year} {getattr(value, 'hour', 0):02d}:{getattr(value, 'minute', 0):02d}"
    return str(value)


# ══════════════════════════════════════════════════════════════════════════════
# Analisi ritorni e statistiche
# ══════════════════════════════════════════════════════════════════════════════

def business_day_deltas(index: Any) -> pd.Series:
    idx = pd.DatetimeIndex(index)
    if len(idx) < 2:
        return pd.Series(dtype=float)
    deltas = []
    for prev, curr in zip(idx[:-1], idx[1:]):
        try:
            days = int(np.busday_count(prev.date(), curr.date()))
        except Exception:
            days = int((curr - prev).days)
        deltas.append(float(max(days, 1)))
    return pd.Series(deltas, index=idx[1:], dtype=float)


def build_analysis_returns(price_frame: pd.DataFrame, tickers: list[str]) -> pd.DataFrame:
    returns = {}
    for tk in tickers:
        if tk not in price_frame.columns:
            continue
        p = pd.Series(price_frame[tk]).dropna().astype(float)
        p = p[p > 0]
        if len(p) < 3:
            continue
        log_returns = np.log(p / p.shift(1)).dropna()
        if log_returns.empty:
            continue
        gaps = business_day_deltas(p.index).reindex(log_returns.index).fillna(1.0).clip(lower=1.0)
        returns[tk] = log_returns / np.sqrt(gaps)
    return pd.DataFrame(returns).sort_index() if returns else pd.DataFrame()


def compute_instrument_stats(
    price_series: pd.Series,
    bench_series: pd.Series | None = None,
    start_date: "pd.Timestamp | None" = None,
) -> dict[str, Any] | None:
    p = pd.Series(price_series).dropna().astype(float)
    p = p[p > 0]
    if start_date is not None:
        p = p.loc[p.index >= pd.Timestamp(start_date)]
    if len(p) < 3:
        return None
    first_date = pd.to_datetime(p.index[0])
    last_date = pd.to_datetime(p.index[-1])
    elapsed_days = max((last_date - first_date).days, 1)
    total_return = (p.iloc[-1] / p.iloc[0]) - 1 if p.iloc[0] > 0 else np.nan
    cagr = (p.iloc[-1] / p.iloc[0]) ** (365.25 / elapsed_days) - 1 if p.iloc[0] > 0 and elapsed_days > 0 else np.nan
    log_returns = np.log(p / p.shift(1)).dropna()
    gaps = business_day_deltas(p.index).reindex(log_returns.index).fillna(1.0).clip(lower=1.0)
    normalized_daily_log_returns = log_returns / np.sqrt(gaps)
    vol_ann = normalized_daily_log_returns.std(ddof=1) * np.sqrt(252) if len(normalized_daily_log_returns) > 1 else np.nan
    sharpe = cagr / vol_ann if pd.notna(cagr) and pd.notna(vol_ann) and vol_ann > 0 else np.nan
    dd = ((p / p.cummax()) - 1).min()

    # VaR 95% e CVaR 95%
    var_95 = np.nan
    cvar_95 = np.nan
    if len(normalized_daily_log_returns) >= 20:
        var_95 = float(np.percentile(normalized_daily_log_returns, 5))
        cvar_data = normalized_daily_log_returns[normalized_daily_log_returns <= var_95]
        cvar_95 = float(cvar_data.mean()) if len(cvar_data) > 0 else np.nan

    # Sortino Ratio (downside deviation)
    downside_dev = np.nan
    sortino = np.nan
    if len(normalized_daily_log_returns) >= 2:
        negative_returns = normalized_daily_log_returns[normalized_daily_log_returns < 0]
        if len(negative_returns) >= 2:
            downside_dev = float(negative_returns.std(ddof=1) * np.sqrt(252))
            if pd.notna(cagr) and downside_dev > 1e-9:
                sortino = float(cagr / downside_dev)

    # Calmar Ratio
    calmar = np.nan
    if pd.notna(cagr) and abs(dd) > 1e-9:
        calmar = float(cagr / abs(dd))

    # Beta vs benchmark
    beta = np.nan
    if bench_series is not None:
        b_series = pd.Series(bench_series).dropna().astype(float)
        b_aligned = b_series.reindex(p.index).dropna()
        p_aligned = p.reindex(b_aligned.index).dropna()
        if len(p_aligned) >= 10 and len(b_aligned) >= 10:
            r_instr = np.diff(np.log(p_aligned.values))
            r_bench = np.diff(np.log(b_aligned.values))
            if len(r_instr) >= 2 and np.var(r_bench) > 1e-12:
                beta = float(np.cov(r_instr, r_bench)[0, 1] / np.var(r_bench))

    return {
        "Osservazioni": int(len(p)),
        "Giorni coperti": int(elapsed_days),
        "Rend. Tot.": total_return,
        "CAGR": cagr,
        "Volatilità Ann.": vol_ann,
        "Sharpe (rf 0%)": sharpe,
        "Max Drawdown": dd,
        "VaR 95%": var_95,
        "CVaR 95%": cvar_95,
        "Sortino": sortino,
        "Calmar": calmar,
        "Beta": beta,
        "Downside Dev.": downside_dev,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Stato portafoglio
# ══════════════════════════════════════════════════════════════════════════════

def compute_portfolio_state(
    data: dict[str, Any],
    price_map: dict[str, float] | None = None,
    include_closed: bool = True,
) -> dict[str, Any]:
    price_map = price_map or {}
    signature = _portfolio_state_signature(data, price_map=price_map, include_closed=include_closed)
    cache_all = data.setdefault("cache_posizioni", {}) if isinstance(data, dict) else {}
    cache_bucket = cache_all.get("all") if include_closed else cache_all.get("open")
    if isinstance(cache_bucket, dict) and cache_bucket.get("signature") == signature:
        try:
            df_cached = _restore_df_from_cache(cache_bucket.get("rows", []))
            return {
                "df": df_cached,
                "liquidita": _safe_float(cache_bucket.get("liquidita", 0)),
                "eventi": get_registro_eventi(data),
            }
        except Exception as e:
            logger.debug("cache restore fallback: %s", e)

    eventi = get_registro_eventi(data)
    stato = {}
    liquidita = 0.0
    for ev in eventi:
        tipo = ev.get("tipo_evento")
        tk = ev.get("ticker", "")
        qty = _safe_float(ev.get("quantita", 0))
        prezzo = _safe_float(ev.get("prezzo_unitario", 0))
        comm = _safe_float(ev.get("commissioni", 0))
        imp = _safe_float(ev.get("imposte", 0))
        netto = _safe_float(ev.get("importo_netto", 0))
        if tk and tk not in stato:
            stato[tk] = {
                "qty": 0.0,
                "cost": 0.0,
                "comm": 0.0,
                "realized_gross": 0.0,
                "realized_net": 0.0,
                "tax": 0.0,
                "dividendi_net": 0.0,
                "cedole_net": 0.0,
                "ultimo_evento": ev.get("data"),
            }
        if tipo == "ACQUISTO" and tk:
            stp = stato[tk]
            stp["qty"] += qty
            stp["cost"] += qty * prezzo + comm + imp
            stp["comm"] += comm
            stp["tax"] += imp
            stp["ultimo_evento"] = ev.get("data")
            liquidita += netto
        elif tipo in {"VENDITA", "RIMBORSO A SCADENZA"} and tk:
            stp = stato[tk]
            qty_before = _safe_float(stp.get("qty", 0))
            cost_before = _safe_float(stp.get("cost", 0))
            scarico_qty = min(qty, qty_before) if qty_before > 0 else 0.0
            pmc = (cost_before / qty_before) if qty_before > _EPS else 0.0
            cost_scaricato = scarico_qty * pmc
            realiz_lordo = (scarico_qty * prezzo) - cost_scaricato
            realiz_netto = realiz_lordo - comm - imp
            stp["qty"] = max(0.0, qty_before - scarico_qty)
            stp["cost"] = max(0.0, cost_before - cost_scaricato)
            stp["comm"] += comm
            stp["tax"] += imp
            stp["realized_gross"] += realiz_lordo
            stp["realized_net"] += realiz_netto
            stp["ultimo_evento"] = ev.get("data")
            liquidita += netto
        elif tipo in {"CEDOLA", "DIVIDENDO"}:
            if tk:
                stp = stato.setdefault(tk, {
                    "qty": 0.0, "cost": 0.0, "comm": 0.0, "realized_gross": 0.0, "realized_net": 0.0,
                    "tax": 0.0, "dividendi_net": 0.0, "cedole_net": 0.0, "ultimo_evento": ev.get("data")
                })
                if tipo == "CEDOLA":
                    stp["cedole_net"] += netto
                else:
                    stp["dividendi_net"] += netto
                stp["tax"] += imp
                stp["ultimo_evento"] = ev.get("data")
            liquidita += netto
        elif tipo == "VERSAMENTO":
            liquidita += abs(netto) if netto != 0 else abs(_safe_float(ev.get("importo_lordo", 0)))
        elif tipo in {"PRELIEVO", "COMMISSIONE", "IMPOSTA"}:
            base = netto if netto != 0 else -abs(_safe_float(ev.get("importo_lordo", 0)) or comm or imp)
            liquidita += base

    rows = []
    for s in data.get("strumenti", []):
        tk = s.get("ticker", "")
        stp = stato.get(tk, {"qty": 0.0, "cost": 0.0, "comm": 0.0, "realized_gross": 0.0, "realized_net": 0.0, "tax": 0.0, "dividendi_net": 0.0, "cedole_net": 0.0})
        qty = _safe_float(stp.get("qty", 0))
        if (not include_closed) and qty <= _EPS:
            continue
        price = _safe_float((price_map or {}).get(tk, s.get("prezzo", 0)))
        val = qty * price
        cost = _safe_float(stp.get("cost", 0))
        pmc = cost / qty if qty > _EPS else 0.0
        pl = val - cost
        pct = pl / abs(cost) if abs(cost) > _EPS else 0.0
        rows.append({
            "Ticker": tk,
            "Strumento": s.get("nome", tk),
            "Tipo": s.get("tipo", ""),
            "Quote": qty,
            "Prezzo": price,
            "PMC": pmc,
            "Controvalore": val,
            "Costo": cost,
            "Comm.": _safe_float(stp.get("comm", 0)),
            "P/L €": pl,
            "P/L %": pct,
            "P/L Realizzato Lordo": _safe_float(stp.get("realized_gross", 0)),
            "P/L Realizzato Netto": _safe_float(stp.get("realized_net", 0)),
            "Imposte €": _safe_float(stp.get("tax", 0)),
            "Cedole nette": _safe_float(stp.get("cedole_net", 0)),
            "Dividendi netti": _safe_float(stp.get("dividendi_net", 0)),
            "Ultimo evento": stp.get("ultimo_evento"),
        })
    df = pd.DataFrame(rows)
    cache_all["all" if include_closed else "open"] = {
        "signature": signature,
        "liquidita": liquidita,
        "rows": _serialize_df_for_cache(df),
        "updated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    }
    return {"df": df, "liquidita": liquidita, "eventi": eventi}


def get_cash_balance(data: dict[str, Any]) -> float:
    ledger = data.get("registro_liquidita", []) or _rebuild_cash_ledger_from_events(get_registro_eventi(data))
    return float(sum(_safe_float(x.get("importo", 0)) for x in ledger))


def append_evento_portafoglio(data: dict[str, Any], evento: EventDict) -> EventDict:
    data.setdefault("registro_eventi", [])
    data.setdefault("registro_liquidita", [])
    ok, msg = validate_evento_portafoglio(data, evento)
    if not ok:
        raise ValueError(msg)
    ev = _normalize_event_record(evento)
    if not ev.get("event_id"):
        ev["event_id"] = _new_event_id(data)
    data["registro_eventi"].append(ev)
    data["registro_eventi"].sort(key=_event_sort_key)
    data["registro_liquidita"] = _rebuild_cash_ledger_from_events(data["registro_eventi"])
    tipo = ev.get("tipo_evento")
    if tipo in {"ACQUISTO", "VENDITA"}:
        data.setdefault("operazioni", []).append({
            "data": ev.get("data"), "ticker": ev.get("ticker", ""), "tipo": tipo,
            "qty": _safe_float(ev.get("quantita", 0)), "price": _safe_float(ev.get("prezzo_unitario", 0)),
            "comm": _safe_float(ev.get("commissioni", 0)), "note": ev.get("note", "")
        })
        data["operazioni"].sort(key=lambda x: x.get("data", ""))
    elif tipo in {"CEDOLA", "DIVIDENDO"}:
        lordo = _safe_float(ev.get("importo_lordo", 0))
        netto = _safe_float(ev.get("importo_netto", 0))
        aliquota = (_safe_float(ev.get("imposte", 0)) / lordo) if lordo > 0 else _safe_float(ev.get("aliquota", 0))
        data.setdefault("proventi", []).append({
            "data": ev.get("data"), "ticker": ev.get("ticker", ""), "tipo": tipo,
            "importo_lordo": lordo, "aliquota": aliquota,
            "importo_netto": netto, "note": ev.get("note", "")
        })
        data["proventi"].sort(key=lambda x: x.get("data", ""))
    data["schema_version"] = SCHEMA_VERSION
    data["cache_posizioni"] = {}
    data["cache_storico_portafoglio"] = {}
    return ev


# ══════════════════════════════════════════════════════════════════════════════
# Build DataFrame portafoglio (privati) e storico prezzi (pubblico)
# ══════════════════════════════════════════════════════════════════════════════

def calc_positions(data: dict[str, Any]) -> dict[str, dict[str, float]]:
    state = compute_portfolio_state(data, include_closed=True)
    if state["df"].empty:
        return {}
    return state["df"].set_index("Ticker").apply(lambda row: {
        "qty": _safe_float(row.get("Quote", 0)),
        "cost": _safe_float(row.get("Costo", 0)),
        "comm": _safe_float(row.get("Comm.", 0)),
        "realized_net": _safe_float(row.get("P/L Realizzato Netto", 0)),
        "realized_gross": _safe_float(row.get("P/L Realizzato Lordo", 0)),
        "tax": _safe_float(row.get("Imposte €", 0)),
    }, axis=1).to_dict()


def build_ptf_df(data: dict[str, Any]) -> pd.DataFrame:
    storico = data.get("storico_prezzi", {})
    last_known = {}
    for d in sorted(storico.keys()):
        for tk, p in storico[d].items():
            if p:
                last_known[tk] = p
    state = compute_portfolio_state(data, price_map=last_known, include_closed=True)
    return state["df"] if isinstance(state.get("df"), pd.DataFrame) else pd.DataFrame()


def build_hist_df(data: dict[str, Any]) -> pd.DataFrame:
    st = data.get("storico_prezzi", {})
    if not st:
        return pd.DataFrame()
    tks = [s["ticker"] for s in data["strumenti"]]
    sorted_dates = sorted(st.keys())
    tk_to_idx = {tk: i for i, tk in enumerate(tks)}
    arr = np.full((len(sorted_dates), len(tks)), np.nan, dtype=np.float64)
    for row_i, d in enumerate(sorted_dates):
        for tk, val in st[d].items():
            col_j = tk_to_idx.get(tk)
            if col_j is not None and val is not None:
                arr[row_i, col_j] = float(val)
    df = pd.DataFrame(arr, index=pd.to_datetime(sorted_dates), columns=tks)
    df.index.name = "Data"
    return df


def _apply_event_to_pos(
    ev: EventDict,
    pos: dict[str, dict[str, float]],
    cash: float,
    realized_gross_total: float,
    realized_net_total: float,
    taxes_total: float,
) -> tuple[float, float, float, float]:
    tipo = ev.get("tipo_evento")
    tk = ev.get("ticker", "")
    qty = _safe_float(ev.get("quantita", 0))
    prezzo = _safe_float(ev.get("prezzo_unitario", 0))
    netto = _safe_float(ev.get("importo_netto", 0))
    comm = _safe_float(ev.get("commissioni", 0))
    imp = _safe_float(ev.get("imposte", 0))
    if tk and tk not in pos:
        pos[tk] = {"qty": 0.0, "cost": 0.0, "realized_net": 0.0, "realized_gross": 0.0}
    if tipo == "ACQUISTO" and tk:
        pos[tk]["qty"] += qty
        pos[tk]["cost"] += qty * prezzo + comm + imp
        cash += netto
    elif tipo in {"VENDITA", "RIMBORSO A SCADENZA"} and tk:
        qty_before = pos[tk]["qty"]
        cost_before = pos[tk]["cost"]
        scarico_qty = min(qty, qty_before) if qty_before > 0 else 0.0
        pmc = (cost_before / qty_before) if qty_before > _EPS else 0.0
        scarico_cost = scarico_qty * pmc
        realiz_lordo = scarico_qty * prezzo - scarico_cost
        realiz_netto = realiz_lordo - comm - imp
        pos[tk]["qty"] = max(0.0, qty_before - scarico_qty)
        pos[tk]["cost"] = max(0.0, cost_before - scarico_cost)
        pos[tk]["realized_gross"] += realiz_lordo
        pos[tk]["realized_net"] += realiz_netto
        realized_gross_total += realiz_lordo
        realized_net_total += realiz_netto
        taxes_total += imp
        cash += netto
    elif tipo in {"CEDOLA", "DIVIDENDO", "VERSAMENTO", "PRELIEVO", "COMMISSIONE", "IMPOSTA"}:
        cash += netto
        taxes_total += imp
    return cash, realized_gross_total, realized_net_total, taxes_total


def build_portfolio_history_df(data: dict[str, Any]) -> pd.DataFrame:
    sto = data.get("storico_prezzi", {})
    if not sto:
        return pd.DataFrame()
    cache = data.get("cache_storico_portafoglio", {}) or {}
    event_sig = hashlib.md5(json.dumps(get_registro_eventi(data), sort_keys=True, default=str).encode()).hexdigest()
    cur_prices_sig = {s.get("ticker", ""): s.get("prezzo") for s in data.get("strumenti", [])}
    last_upd_date = str(data.get("last_quotes_update") or "")[:10]
    # today_str in firma: la cache è persistita su disco e deve invalidarsi ogni nuovo giorno
    today_date = date.today()
    today_str = today_date.strftime("%Y-%m-%d")
    price_sig = hashlib.md5(json.dumps({"sto": sto, "cur": cur_prices_sig, "lqu": last_upd_date, "td": today_str}, sort_keys=True, default=str).encode()).hexdigest()
    cache_sig = f"portfolio_history_v5|{event_sig}|{price_sig}"
    if cache.get("signature") == cache_sig and cache.get("rows"):
        try:
            df_cached = pd.DataFrame(cache.get("rows", []))
            if not df_cached.empty and "Data" in df_cached.columns:
                df_cached["Data"] = pd.to_datetime(df_cached["Data"])
                return df_cached
        except Exception as e:
            logger.debug("cache restore fallback: %s", e)
    ds = sorted(sto.keys())
    eventi = get_registro_eventi(data)
    hp = []
    pos = {}
    cash = 0.0
    capital_versato = 0.0  # capitale netto cumulato versato (al netto di prelievi)
    realized_net_total = 0.0
    realized_gross_total = 0.0
    taxes_total = 0.0
    last_valid_prices: dict[str, float] = {}
    idx = 0
    eventi_ordinati = sorted(eventi, key=_event_sort_key)
    for d in ds:
        while idx < len(eventi_ordinati) and str(eventi_ordinati[idx].get("data", "")) <= d:
            ev = eventi_ordinati[idx]
            # Traccia il capitale netto versato (versamenti meno prelievi)
            _tipo = ev.get("tipo_evento")
            if _tipo == "VERSAMENTO":
                _imp = _safe_float(ev.get("importo_netto", 0)) or _safe_float(ev.get("importo_lordo", 0))
                capital_versato += abs(_imp)
            elif _tipo == "PRELIEVO":
                _imp = _safe_float(ev.get("importo_netto", 0)) or _safe_float(ev.get("importo_lordo", 0))
                capital_versato -= abs(_imp)
            cash, realized_gross_total, realized_net_total, taxes_total = _apply_event_to_pos(
                ev, pos, cash, realized_gross_total, realized_net_total, taxes_total
            )
            idx += 1
        pd_day = sto[d]
        valore_aperto = 0.0
        costo_aperto = 0.0
        row = {"Data": pd.to_datetime(d)}
        for tk, stp in pos.items():
            prezzo_raw = _safe_float(pd_day.get(tk, None))
            if pd.notna(prezzo_raw) and prezzo_raw > 0:
                last_valid_prices[tk] = float(prezzo_raw)
                prezzo = float(prezzo_raw)
            else:
                prezzo = float(last_valid_prices.get(tk, 0.0))
            qty = _safe_float(stp.get("qty", 0))
            cost = _safe_float(stp.get("cost", 0))
            valore_aperto += qty * prezzo
            costo_aperto += cost
            if qty > 0:
                row[f"PL_{tk}"] = qty * prezzo - cost
        # Valore = posizioni aperte a mercato + liquidità residua (cash)
        # Capitale = versato netto cumulato (versamenti - prelievi)
        # P/L totale = Valore - Capitale (include realizzato + non realizzato + cedole)
        row["Valore"] = valore_aperto + cash
        row["Costo"] = costo_aperto
        row["Capitale"] = capital_versato
        row["Liquidità"] = cash
        row["P/L"] = row["Valore"] - capital_versato
        row["P/L Realizzato Netto"] = realized_net_total
        row["P/L Realizzato Lordo"] = realized_gross_total
        row["Imposte"] = taxes_total
        hp.append(row)
    # Punto sintetico "oggi" con i prezzi correnti (s["prezzo"]).
    # Su weekday: sempre aggiunto se storico non è aggiornato a oggi.
    # Su weekend: aggiunto solo se last_quotes_update > ultimo storico (prezzi freschi disponibili).
    is_weekday = today_date.weekday() < 5  # 0-4 = lunedì-venerdì, 5-6 = sabato-domenica
    has_fresh_weekend_prices = (
        not is_weekday
        and bool(last_upd_date)
        and bool(ds)
        and last_upd_date > ds[-1]
    )
    if ds and ds[-1] < today_str and (is_weekday or has_fresh_weekend_prices):
        while idx < len(eventi_ordinati):
            ev = eventi_ordinati[idx]
            _tipo = ev.get("tipo_evento")
            if _tipo == "VERSAMENTO":
                _imp = _safe_float(ev.get("importo_netto", 0)) or _safe_float(ev.get("importo_lordo", 0))
                capital_versato += abs(_imp)
            elif _tipo == "PRELIEVO":
                _imp = _safe_float(ev.get("importo_netto", 0)) or _safe_float(ev.get("importo_lordo", 0))
                capital_versato -= abs(_imp)
            cash, realized_gross_total, realized_net_total, taxes_total = _apply_event_to_pos(
                ev, pos, cash, realized_gross_total, realized_net_total, taxes_total
            )
            idx += 1
        cur_prices = {s["ticker"]: _safe_float(s.get("prezzo", 0)) for s in data.get("strumenti", [])}
        valore_aperto_t = 0.0
        costo_aperto_t = 0.0
        row_today = {"Data": pd.to_datetime(today_str)}
        for tk, stp in pos.items():
            prezzo_raw = cur_prices.get(tk, 0.0)
            if pd.notna(prezzo_raw) and prezzo_raw > 0:
                last_valid_prices[tk] = float(prezzo_raw)
                pr = float(prezzo_raw)
            else:
                pr = float(last_valid_prices.get(tk, 0.0))
            q = _safe_float(stp.get("qty", 0))
            c = _safe_float(stp.get("cost", 0))
            valore_aperto_t += q * pr
            costo_aperto_t += c
            if q > 0:
                row_today[f"PL_{tk}"] = q * pr - c
        row_today["Valore"] = valore_aperto_t + cash
        row_today["Costo"] = costo_aperto_t
        row_today["Capitale"] = capital_versato
        row_today["Liquidità"] = cash
        row_today["P/L"] = row_today["Valore"] - capital_versato
        row_today["P/L Realizzato Netto"] = realized_net_total
        row_today["P/L Realizzato Lordo"] = realized_gross_total
        row_today["Imposte"] = taxes_total
        hp.append(row_today)
    data["cache_storico_portafoglio"] = {
        "signature": cache_sig,
        "rows": [{k: (v.strftime("%Y-%m-%d") if isinstance(v, pd.Timestamp) else v) for k, v in r.items()} for r in hp]
    }
    return pd.DataFrame(hp)


# ══════════════════════════════════════════════════════════════════════════════
# Snapshot
# ══════════════════════════════════════════════════════════════════════════════

def _build_snapshot_from_data(data: dict[str, Any], label: str = "Snapshot automatico") -> dict[str, Any]:
    da = build_ptf_df(data)
    total_value = float(pd.to_numeric(da.get("Controvalore", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()) if not da.empty else 0.0
    total_cost = float(pd.to_numeric(da.get("Costo", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()) if not da.empty else 0.0
    macro_weights = {"GOV": 0.0, "ETF": 0.0, "FND": 0.0}
    holdings = []
    if not da.empty and total_value > 0:
        tmp = da.copy()
        tmp["Categoria"] = tmp["Tipo"].apply(macro_cat)
        grp = tmp.groupby("Categoria")["Controvalore"].sum()
        for k in macro_weights:
            macro_weights[k] = float(grp.get(k, 0.0)) / total_value if total_value > 0 else 0.0
        holdings = da.apply(lambda r: {
            "ticker": r["Ticker"],
            "strumento": r["Strumento"],
            "categoria": macro_cat(r["Tipo"]),
            "weight": float(r["Controvalore"]) / total_value if total_value > 0 else 0.0,
            "market_value": float(r["Controvalore"])
        }, axis=1).tolist()
    ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    return {
        "snapshot_id": f"snap_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "portfolio_id": "main",
        "label": label,
        "created_at": ts,
        "total_value": total_value,
        "total_cost": total_cost,
        "total_pl": total_value - total_cost,
        "macro_weights": macro_weights,
        "holdings": holdings,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Benchmark
# ══════════════════════════════════════════════════════════════════════════════

_BENCHMARK_SERIES_CACHE_DIR = os.path.join(DATA_DIR, "cache", "derived_runtime", "benchmark_series")


def get_cached_benchmark_series(
    data: dict[str, Any],
    bench_ticker: str,
    min_start: Any = None,
    period: str = "2y",
) -> pd.Series:
    """Restituisce la serie benchmark da cache; scarica solo se assente.

    Profilazione: registra cache hit / download yfinance per verificare se la lentezza
    deriva da benchmark riscaricati durante Summary/Analisi/Quotazioni.
    """
    t0 = time.perf_counter()
    if not bench_ticker:
        return pd.Series(dtype=float)
    bkey = f"bench_{bench_ticker}"
    had_cache = bkey in data.get("benchmark_data", {}) and bool(data.get("benchmark_data", {}).get(bkey, {}))
    if not had_cache:
        try:
            with profile_step("Core/Benchmark", "scaricamento benchmark yfinance", detail=f"ticker={bench_ticker}; period={period}"):
                bd = yf.Ticker(bench_ticker).history(period=period)
            if not bd.empty:
                data.setdefault("benchmark_data", {})[bkey] = {str(d.date()): float(v) for d, v in bd["Close"].items()}
                with profile_step("Core/Benchmark", "save_data benchmark", detail=f"ticker={bench_ticker}; punti={len(bd)}"):
                    from persistence.storage import save_benchmark_data
                    save_benchmark_data(data)
        except Exception as e:
            record_render_event(
                "Core/Benchmark",
                "download benchmark fallito",
                time.perf_counter() - t0,
                status="WARNING",
                detail=f"{bench_ticker}; {type(e).__name__}: {e}",
            )
            logger.warning("benchmark cache save failed: %s", e)
    bd = data.get("benchmark_data", {}).get(bkey, {})
    if had_cache:
        record_render_event(
            "Core/Benchmark",
            "benchmark cache hit",
            time.perf_counter() - t0,
            detail=f"ticker={bench_ticker}; punti={len(bd)}; min_start={min_start}",
            count=len(bd),
        )
    if not bd:
        return pd.Series(dtype=float)
    runtime_cache = data.setdefault("_runtime_benchmark_series_cache", {})
    cache_id = f"{bench_ticker}|{len(bd)}|{max(bd.keys(), default='')}"
    ser = runtime_cache.get(cache_id)
    if ser is None:
        os.makedirs(_BENCHMARK_SERIES_CACHE_DIR, exist_ok=True)
        persist_sig = hashlib.md5(cache_id.encode()).hexdigest()[:16]
        persist_path = os.path.join(_BENCHMARK_SERIES_CACHE_DIR, f"{bench_ticker}_{persist_sig}.pkl")
        persisted = None
        if os.path.exists(persist_path):
            try:
                persisted = pd.read_pickle(persist_path)
            except Exception:
                persisted = None
        if isinstance(persisted, dict) and persisted.get("cache_id") == cache_id:
            persisted_value = persisted.get("value")
            if isinstance(persisted_value, pd.Series):
                ser = persisted_value.sort_index()
                record_render_event(
                    "Core/Benchmark",
                    "benchmark raw persisted hit",
                    0.0,
                    detail=f"ticker={bench_ticker}; sig={persist_sig}; punti={len(ser)}",
                    count=len(ser),
                )
        if ser is None:
            with profile_step("Core/Benchmark", "conversione benchmark JSON->Series", detail=f"ticker={bench_ticker}; punti={len(bd)}", count=len(bd)):
                ser = pd.Series({pd.to_datetime(d): float(v) for d, v in bd.items()}).sort_index()
                ser = ser[ser > 0]
            try:
                pd.to_pickle({"cache_id": cache_id, "value": ser.copy()}, persist_path)
            except Exception:
                pass
        runtime_cache[cache_id] = ser
    if min_start is not None and ser is not None and not ser.empty:
        return ser[ser.index >= pd.to_datetime(min_start)]
    return ser.copy() if ser is not None else pd.Series(dtype=float)


def refresh_benchmark_cache(data: dict[str, Any], period: str = "2y", force: bool = False) -> int:
    """Aggiorna la cache benchmark per gli strumenti presenti, se mancante o stale."""
    benchmark_data = data.setdefault("benchmark_data", {})
    target_tickers = {
        resolve_instrument_benchmark(item, prefer_master=False).ticker
        for item in data.get("strumenti", [])
        if isinstance(item, dict)
    }
    target_tickers = {tk for tk in target_tickers if tk}
    if not target_tickers:
        return 0

    today = datetime.now().date()
    refreshed = 0
    changed = False
    for bench_ticker in sorted(target_tickers):
        bkey = f"bench_{bench_ticker}"
        existing = benchmark_data.get(bkey, {}) if isinstance(benchmark_data.get(bkey), dict) else {}
        valid_dates = []
        for raw_date, raw_value in existing.items():
            if raw_value is None or pd.isna(raw_value):
                continue
            try:
                valid_dates.append(pd.to_datetime(raw_date).date())
            except Exception:
                continue
        needs_refresh = force or not existing
        if valid_dates and not force:
            last_valid = max(valid_dates)
            needs_refresh = (today - last_valid).days > 1
        if not needs_refresh:
            continue
        try:
            bd = yf.Ticker(bench_ticker).history(period=period)
            if bd.empty:
                continue
            fresh = {str(d.date()): float(v) for d, v in bd["Close"].items()}
            merged = {**existing, **fresh}
            if merged != existing:
                benchmark_data[bkey] = merged
                refreshed += 1
                changed = True
        except Exception as e:
            logger.warning("benchmark refresh failed for %s: %s", bench_ticker, e)
    if changed:
        from persistence.storage import save_benchmark_data
        save_benchmark_data(data)
    return refreshed


PORTFOLIO_BENCH_OPTIONS = [
    "Blend automatico",
    "60/40 MSCI World / Bond",
    "100% MSCI World",
    "100% GOV",
]

CUSTOM_BENCHMARK_LABEL = "Benchmark personalizzato"
CUSTOM_BENCHMARK_COMPONENT_OPTIONS = {
    "MSCI World (IWDA.AS)": "IWDA.AS",
    "Bond Emergenti (EMB)": "EMB",
    "GOV proxy (EMB)": "EMB",
    "Aggregate Bond EUR Hedged (AGGH)": "AGGH",
}

BENCHMARK_TICKER_FALLBACKS = {
    "BTI.MI": "EMB",
}


def get_effective_portfolio_benchmark_label(settings: dict[str, Any] | None) -> str:
    """Restituisce l'etichetta benchmark effettivamente attiva."""
    if not isinstance(settings, dict):
        return "Blend automatico"
    benchmarking = settings.get("benchmarking", {}) if isinstance(settings.get("benchmarking", {}), dict) else {}
    custom_enabled = bool(benchmarking.get("custom_enabled", False))
    custom_components = benchmarking.get("custom_components", [])
    valid_custom = isinstance(custom_components, list) and any(
        str(item.get("ticker", "")).strip() and float(item.get("weight", 0) or 0) > 0
        for item in custom_components
        if isinstance(item, dict)
    )
    if custom_enabled and valid_custom:
        return str(benchmarking.get("custom_name") or CUSTOM_BENCHMARK_LABEL)
    return str(
        settings.get("portfolio_benchmark_default")
        or benchmarking.get("default_portfolio_benchmark")
        or "Blend automatico"
    )


def _resolve_custom_benchmark_components(settings: dict[str, Any] | None) -> list[tuple[str, float]]:
    """Normalizza i componenti del benchmark personalizzato."""
    if not isinstance(settings, dict):
        return []
    benchmarking = settings.get("benchmarking", {}) if isinstance(settings.get("benchmarking", {}), dict) else {}
    if not bool(benchmarking.get("custom_enabled", False)):
        return []
    raw_components = benchmarking.get("custom_components", [])
    if not isinstance(raw_components, list):
        return []
    normalized: list[tuple[str, float]] = []
    for item in raw_components:
        if not isinstance(item, dict):
            continue
        ticker = str(item.get("ticker", "")).strip()
        try:
            weight = float(item.get("weight", 0) or 0)
        except (TypeError, ValueError):
            weight = 0.0
        if ticker and weight > 0:
            ticker = BENCHMARK_TICKER_FALLBACKS.get(ticker, ticker)
            normalized.append((ticker, weight))
    return normalized


def get_effective_portfolio_benchmark_config(settings: dict[str, Any] | None) -> dict[str, Any]:
    """Restituisce la configurazione benchmark effettiva in forma pronta per UI/report."""
    label = get_effective_portfolio_benchmark_label(settings)
    raw_components = _resolve_custom_benchmark_components(settings)
    total_weight = sum(weight for _ticker, weight in raw_components)
    components = []
    for ticker, weight in raw_components:
        component_label = next(
            (name for name, mapped_ticker in CUSTOM_BENCHMARK_COMPONENT_OPTIONS.items() if mapped_ticker == ticker),
            ticker,
        )
        norm_weight = (weight / total_weight) if total_weight > 0 else 0.0
        components.append({
            "ticker": ticker,
            "label": component_label,
            "weight": float(norm_weight),
        })
    return {
        "label": label,
        "is_custom": bool(raw_components),
        "components": components,
    }


def build_portfolio_benchmark_series(
    data: dict[str, Any],
    bench_label: str,
    da_frame: pd.DataFrame,
    min_date: Any = None,
    settings: dict[str, Any] | None = None,
) -> pd.Series:
    """
    Costruisce una serie benchmark normalizzata a 100 alla min_date.
    """
    total = float(pd.to_numeric(da_frame["Controvalore"], errors="coerce").fillna(0).sum()) if da_frame is not None and not da_frame.empty else 0.0

    custom_components = _resolve_custom_benchmark_components(settings)
    if custom_components:
        components = custom_components
    elif bench_label == "Blend automatico":
        if total <= 0:
            return pd.Series(dtype=float)
        gov_w = float(
            pd.to_numeric(
                da_frame[da_frame["Tipo"].apply(macro_cat) == "GOV"]["Controvalore"],
                errors="coerce"
            ).fillna(0).sum()
        ) / total
        other_w = 1.0 - gov_w
        components = []
        if gov_w > 0.001:
            components.append(("EMB", gov_w))
        if other_w > 0.001:
            components.append(("IWDA.AS", other_w))
    elif bench_label == "60/40 MSCI World / Bond":
        components = [("IWDA.AS", 0.60), ("EMB", 0.40)]
    elif bench_label == "100% MSCI World":
        components = [("IWDA.AS", 1.0)]
    elif bench_label == "100% GOV":
        components = [(BENCHMARK_TICKER_FALLBACKS.get("BTI.MI", "EMB"), 1.0)]
    else:
        return pd.Series(dtype=float)

    if not components:
        return pd.Series(dtype=float)

    # Accorpa eventuali componenti duplicati dello stesso ticker.
    # Esempio reale: due righe IWDA.AS nel benchmark personalizzato non devono
    # produrre due serie distinte, ma un unico peso complessivo.
    weights_by_ticker: dict[str, float] = {}
    for ticker, weight in components:
        try:
            w = float(weight or 0.0)
        except Exception:
            w = 0.0
        if not ticker or w <= 0:
            continue
        weights_by_ticker[str(ticker)] = weights_by_ticker.get(str(ticker), 0.0) + w

    if not weights_by_ticker:
        return pd.Series(dtype=float)

    benchmark_data = data.get("benchmark_data", {}) if isinstance(data, dict) else {}
    blend_cache = data.setdefault("_runtime_portfolio_benchmark_blend_cache", {})
    component_state = {
        ticker: {
            "weight": round(float(weights_by_ticker.get(ticker, 0.0)), 10),
            "points": len(benchmark_data.get(f"bench_{ticker}", {}) or {}),
            "last_date": max((benchmark_data.get(f"bench_{ticker}", {}) or {}).keys(), default=""),
        }
        for ticker in sorted(weights_by_ticker.keys())
    }
    blend_cache_key = hashlib.md5(
        json.dumps(
            {
                "bench_label": str(bench_label or ""),
                "components": component_state,
            },
            sort_keys=True,
            default=str,
        ).encode()
    ).hexdigest()[:16]
    cached_blended = blend_cache.get(blend_cache_key)
    if isinstance(cached_blended, pd.Series) and not cached_blended.empty:
        record_render_event(
            "Core/Benchmark",
            "benchmark blend cache hit",
            0.0,
            detail=f"sig={blend_cache_key}; componenti={list(component_state.keys())}",
            count=len(cached_blended),
        )
        if min_date is not None:
            sliced_cached = cached_blended[cached_blended.index >= pd.to_datetime(min_date)]
            return sliced_cached.copy() if sliced_cached is not None else pd.Series(dtype=float)
        return cached_blended.copy()

    raw_parts: dict[str, pd.Series] = {}
    with profile_step("Core/Benchmark", "build_portfolio_benchmark_series / carica componenti", detail=f"componenti={list(weights_by_ticker.keys())}", count=len(weights_by_ticker)):
        for ticker in weights_by_ticker:
            ser = get_cached_benchmark_series(data, ticker, min_start=None)
            if ser is None or ser.empty:
                continue
            ser = pd.to_numeric(ser, errors="coerce").sort_index().dropna()
            if len(ser) < 2:
                continue
            raw_parts[ticker] = ser

    if not raw_parts:
        return pd.Series(dtype=float)

    with profile_step("Core/Benchmark", "concat/allineamento componenti benchmark", count=len(raw_parts)):
        raw_df = pd.concat(raw_parts, axis=1, sort=False).sort_index()

    # I mercati dei componenti benchmark non hanno tutti lo stesso calendario.
    # Se si sommano le serie con fill_value=0, nei giorni di chiusura di un
    # componente il benchmark crolla artificialmente del suo peso e poi rimbalza.
    # La logica corretta è mantenere l'ultima quotazione disponibile del
    # componente chiuso, senza creare rendimenti fittizi.
    with profile_step("Core/Benchmark", "ffill/dropna calendario benchmark", detail=f"shape_pre={raw_df.shape}"):
        raw_df = raw_df.ffill().dropna(how="any")
    if raw_df.empty:
        return pd.Series(dtype=float)

    weights = pd.Series(weights_by_ticker, dtype=float).reindex(raw_df.columns).fillna(0.0)
    total_w = float(weights.sum())
    if total_w <= 0:
        return pd.Series(dtype=float)
    weights = weights / total_w

    with profile_step("Core/Benchmark", "normalizzazione benchmark base100", detail=f"shape={raw_df.shape}"):
        norm_df = raw_df.divide(raw_df.iloc[0]).multiply(100.0)

    # Protezione anti-spike da singola quotazione errata.
    # Non rimuove grandi movimenti di mercato confermati, ma corregge il caso
    # tipico di un punto isolato che sale/scende molto e rientra subito il giorno
    # successivo, visivamente evidente nei benchmark.
    for col in norm_df.columns:
        s = pd.to_numeric(norm_df[col], errors="coerce").copy()
        ret_prev = s.pct_change()
        ret_next = s.shift(-1) / s - 1.0
        isolated_spike = (ret_prev.abs() > 0.10) & (ret_next.abs() > 0.10) & ((ret_prev * ret_next) < 0)
        if bool(isolated_spike.any()):
            s.loc[isolated_spike] = np.nan
            norm_df[col] = s.interpolate(method="time").ffill().bfill()

    with profile_step("Core/Benchmark", "blend benchmark pesato", detail=f"componenti={list(norm_df.columns)}"):
        blended = norm_df.mul(weights, axis=1).sum(axis=1)

    if min_date is not None:
        blended = blended[blended.index >= pd.to_datetime(min_date)]

    blended = pd.to_numeric(blended, errors="coerce").dropna()
    if blended.empty:
        return pd.Series(dtype=float)

    blend_cache[blend_cache_key] = blended.copy()
    return blended


def build_macro_benchmark_index(
    data: dict[str, Any],
    info_map: dict[str, dict[str, Any]],
    tickers: list[str],
) -> pd.DataFrame:
    macro_bench = {}
    for cat in ACTIVE_CATEGORY_CODES:
        cat_series = []
        cat_tickers = [tk for tk in tickers if macro_cat(info_map.get(tk, {}).get("tipo", "")) == cat]
        for tk in cat_tickers:
            info = info_map.get(tk, {})
            bench_assignment = resolve_instrument_benchmark(info, prefer_master=False)
            bench_tk = bench_assignment.ticker
            if not bench_tk:
                continue
            ser = get_cached_benchmark_series(data, bench_tk)
            if ser.empty:
                continue
            base = float(ser.iloc[0])
            if base <= 0:
                continue
            cat_series.append((ser / base) * 100)
        if cat_series:
            macro_bench[cat] = pd.concat(cat_series, axis=1).mean(axis=1, skipna=True)
    return pd.DataFrame(macro_bench).sort_index() if macro_bench else pd.DataFrame()


# ══════════════════════════════════════════════════════════════════════════════
# Snapshot comparison e summary
# ══════════════════════════════════════════════════════════════════════════════

def build_snapshot_comparison_df(snap_a: dict[str, Any] | None, snap_b: dict[str, Any] | None) -> pd.DataFrame:
    rows = []
    weights_a = (snap_a or {}).get("macro_weights", {})
    weights_b = (snap_b or {}).get("macro_weights", {})
    for cat in ACTIVE_CATEGORY_CODES:
        a = float(weights_a.get(cat, 0.0) or 0.0)
        b = float(weights_b.get(cat, 0.0) or 0.0)
        rows.append({
            "Categoria": cat,
            "Peso A": a,
            "Peso B": b,
            "Delta": b - a,
        })
    return pd.DataFrame(rows)


def build_snapshot_summary_df(snapshots: list[dict[str, Any]] | None) -> pd.DataFrame:
    rows = []
    for s in snapshots or []:
        rows.append({
            "ID": s.get("snapshot_id", ""),
            "Etichetta": s.get("label", ""),
            "Data": _fmt_dt(s.get("created_at")),
            "Valore": s.get("total_value", 0.0),
            "Costo": s.get("total_cost", 0.0),
            "P/L": s.get("total_pl", 0.0),
        })
    return pd.DataFrame(rows)


# ══════════════════════════════════════════════════════════════════════════════
# Target profile e gap analysis
# ══════════════════════════════════════════════════════════════════════════════

def get_default_target_profile(label: str) -> dict[str, float]:
    profiles = {
        "Prudente": {"GOV": 0.55, "ETF": 0.20, "FND": 0.25},
        "Equilibrato": {"GOV": 0.35, "ETF": 0.35, "FND": 0.30},
        "Dinamico": {"GOV": 0.20, "ETF": 0.50, "FND": 0.30},
        "Neutro": {"GOV": 1/3, "ETF": 1/3, "FND": 1/3},
    }
    return profiles.get(label, profiles["Equilibrato"]).copy()


def build_target_gap_by_instrument(
    da_frame: pd.DataFrame,
    target_weights: dict[str, float],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if da_frame is None or da_frame.empty:
        return pd.DataFrame(), pd.DataFrame()
    work = da_frame.copy()
    work = work[pd.to_numeric(work["Controvalore"], errors="coerce").fillna(0) > 0].copy()
    if work.empty:
        return pd.DataFrame(), pd.DataFrame()
    work["Categoria"] = work["Tipo"].apply(macro_cat)
    total_value = float(pd.to_numeric(work["Controvalore"], errors="coerce").fillna(0).sum())
    if total_value <= 0:
        return pd.DataFrame(), pd.DataFrame()
    cat_counts = work.groupby("Categoria")["Ticker"].count().to_dict()
    work["Peso attuale"] = pd.to_numeric(work["Controvalore"], errors="coerce").fillna(0) / total_value
    work["Peso target"] = work["Categoria"].map(lambda c: float(target_weights.get(c, 0.0)) / max(int(cat_counts.get(c, 1)), 1))
    work["Scostamento %"] = work["Peso attuale"] - work["Peso target"]
    work["Scostamento €"] = (work["Peso attuale"] - work["Peso target"]) * total_value
    work["Da aggiungere €"] = -work["Scostamento €"]
    detail = work[["Ticker", "Strumento", "Categoria", "Controvalore", "Peso attuale", "Peso target", "Scostamento %", "Scostamento €", "Da aggiungere €"]].sort_values("Scostamento €", ascending=False)

    macro = work.groupby("Categoria", as_index=False).agg(Controvalore=("Controvalore", "sum"))
    macro["Peso attuale"] = macro["Controvalore"] / total_value
    macro["Peso target"] = macro["Categoria"].map(lambda c: float(target_weights.get(c, 0.0)))
    macro["Scostamento %"] = macro["Peso attuale"] - macro["Peso target"]
    macro["Da riallocare €"] = (macro["Peso target"] - macro["Peso attuale"]) * total_value
    macro = macro.sort_values("Categoria")
    return macro, detail


def build_instrument_target_gap_table(da_frame: pd.DataFrame) -> pd.DataFrame:
    if da_frame is None or da_frame.empty:
        return pd.DataFrame()
    work = da_frame.copy()
    work = work[pd.to_numeric(work["Controvalore"], errors="coerce").fillna(0) > 0].copy()
    if work.empty:
        return pd.DataFrame()
    total_value = float(pd.to_numeric(work["Controvalore"], errors="coerce").fillna(0).sum())
    if total_value <= 0:
        return pd.DataFrame()
    n = len(work)
    work["Peso attuale"] = pd.to_numeric(work["Controvalore"], errors="coerce").fillna(0) / total_value
    work["Peso target"] = 1.0 / n
    work["Scostamento"] = work["Peso attuale"] - work["Peso target"]
    work["Importo per target"] = (work["Peso target"] * total_value) - pd.to_numeric(work["Controvalore"], errors="coerce").fillna(0)
    return work[["Ticker", "Strumento", "Tipo", "Peso attuale", "Peso target", "Scostamento", "Importo per target"]].sort_values("Scostamento", ascending=False)


def build_risk_contribution_table(da_frame: pd.DataFrame, returns_df: pd.DataFrame) -> pd.DataFrame:
    if da_frame is None or da_frame.empty or returns_df is None or returns_df.empty:
        return pd.DataFrame()
    work = da_frame.copy()
    work = work[pd.to_numeric(work["Controvalore"], errors="coerce").fillna(0) > 0].copy()
    if work.empty:
        return pd.DataFrame()
    tickers = [tk for tk in work["Ticker"] if tk in returns_df.columns]
    if len(tickers) < 2:
        return pd.DataFrame()
    ret = returns_df[tickers].dropna(how="all").copy()
    ret = ret.fillna(0.0)
    if len(ret) < 3:
        return pd.DataFrame()
    values = pd.to_numeric(work.set_index("Ticker").loc[tickers, "Controvalore"], errors="coerce").fillna(0.0)
    total_value = float(values.sum())
    if total_value <= 0:
        return pd.DataFrame()
    w = (values / total_value).astype(float)
    cov = ret.cov().values * 252.0
    wv = w.values.reshape(-1, 1)
    port_var = float((wv.T @ cov @ wv)[0, 0])
    if not np.isfinite(port_var) or port_var <= 0:
        return pd.DataFrame()
    mc_var = cov @ w.values
    rc_var = w.values * mc_var
    out = work.set_index("Ticker").loc[tickers, ["Strumento", "Tipo", "Controvalore"]].copy().reset_index()
    out["Peso %"] = w.values
    out["Contributo rischio %"] = rc_var / port_var
    out["Rapporto rischio/peso"] = out["Contributo rischio %"] / out["Peso %"].replace(0, np.nan)
    out["Volatilità stimata"] = np.sqrt(np.diag(cov))
    out["Categoria"] = out["Tipo"].apply(macro_cat)
    return out[["Ticker", "Strumento", "Categoria", "Controvalore", "Peso %", "Contributo rischio %", "Rapporto rischio/peso", "Volatilità stimata"]].sort_values("Contributo rischio %", ascending=False)


# ══════════════════════════════════════════════════════════════════════════════
# IRR / XIRR
# ══════════════════════════════════════════════════════════════════════════════

def compute_xirr(flows: list[float], dates: list[Any]) -> float | None:
    """
    Calcola XIRR (IRR con flussi irregolari) via bisection.
    flows: lista di float (negativo = uscita, positivo = entrata)
    dates: lista di date o datetime corrispondenti
    Restituisce IRR annualizzato o None se non calcolabile.
    """
    if len(flows) < 2 or len(flows) != len(dates):
        return None
    if not (any(f < 0 for f in flows) and any(f > 0 for f in flows)):
        return None
    d0 = pd.to_datetime(dates[0])
    years = [(pd.to_datetime(d) - d0).days / 365.25 for d in dates]

    def npv(rate: float) -> float:
        try:
            return sum(f / (1.0 + rate) ** y for f, y in zip(flows, years))
        except (ZeroDivisionError, OverflowError):
            return float("nan")

    lo, hi = -0.9999, 10.0
    if not (np.isfinite(npv(lo)) and np.isfinite(npv(hi))):
        return None
    if npv(lo) * npv(hi) > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if abs(hi - lo) < 1e-8:
            break
        val_mid = npv(mid)
        if not np.isfinite(val_mid):
            return None
        if npv(lo) * val_mid < 0:
            hi = mid
        else:
            lo = mid
    result = (lo + hi) / 2.0
    if not np.isfinite(result) or result < -0.99 or result > 3.0:
        return None
    return result


def build_xirr_flows(
    data: dict[str, Any],
    da_frame: pd.DataFrame,
    proventi: list[dict[str, Any]],
    tickers: list[str] | None = None,
) -> tuple[list[float], list[date]]:
    """
    Costruisce liste (flows, dates) per il calcolo XIRR.
    tickers=None → tutti gli strumenti (livello portafoglio).
    tickers=[...] → solo gli strumenti indicati (livello categoria).
    """
    ops = sorted(data.get("operazioni", []), key=lambda x: str(x.get("data", "")))
    flows, dates = [], []
    for op in ops:
        tk = op.get("ticker")
        if tickers is not None and tk not in tickers:
            continue
        try:
            d = pd.to_datetime(op["data"]).date()
            q = float(op.get("qty", 0))
            p = float(op.get("price", 0))
            c = float(op.get("comm", 0))
        except Exception:
            continue
        if op.get("tipo") == "ACQUISTO":
            flows.append(-(q * p + c))
        else:
            flows.append(q * p - c)
        dates.append(d)
    for prov in (proventi or []):
        tk = prov.get("ticker")
        if tickers is not None and tk not in tickers:
            continue
        try:
            d = pd.to_datetime(prov["data"]).date()
            netto = float(prov.get("importo_netto", 0))
        except Exception:
            continue
        if netto > 0:
            flows.append(netto)
            dates.append(d)
    if da_frame is not None and not da_frame.empty:
        work = da_frame.copy()
        if tickers is not None:
            work = work[work["Ticker"].isin(tickers)]
        final_value = float(pd.to_numeric(work["Controvalore"], errors="coerce").fillna(0).sum())
        if final_value > 0:
            flows.append(final_value)
            dates.append(date.today())
    if not flows or not dates:
        return [], []
    paired = sorted(zip(dates, flows), key=lambda x: x[0])
    dates_s, flows_s = zip(*paired)
    return list(flows_s), list(dates_s)


# ══════════════════════════════════════════════════════════════════════════════
# Proventi
# ══════════════════════════════════════════════════════════════════════════════

def build_proventi_summary(proventi: list[dict[str, Any]], info_map: dict[str, dict[str, Any]]) -> pd.DataFrame:
    """Aggrega i proventi per ticker."""
    if not proventi:
        return pd.DataFrame(columns=["Ticker", "Strumento", "N", "Lordo totale", "Ritenute", "Netto totale"])
    agg = defaultdict(lambda: {"N": 0, "Lordo": 0.0, "Ritenute": 0.0, "Netto": 0.0})
    for p in proventi:
        tk = p.get("ticker", "")
        lordo = float(p.get("importo_lordo", 0))
        netto = float(p.get("importo_netto", 0))
        agg[tk]["N"] += 1
        agg[tk]["Lordo"] += lordo
        agg[tk]["Ritenute"] += lordo - netto
        agg[tk]["Netto"] += netto
    rows = []
    for tk, v in agg.items():
        rows.append({
            "Ticker": tk,
            "Strumento": info_map.get(tk, {}).get("nome", tk),
            "N": v["N"],
            "Lordo totale": v["Lordo"],
            "Ritenute": v["Ritenute"],
            "Netto totale": v["Netto"],
        })
    return pd.DataFrame(rows).sort_values("Netto totale", ascending=False).reset_index(drop=True)


# ══════════════════════════════════════════════════════════════════════════════
# GOV / Titoli di Stato
# ══════════════════════════════════════════════════════════════════════════════

def extract_gov_maturity_date(name: Any) -> date | None:
    txt = str(name or "").upper().strip()
    month_map = {
        "GE": 1, "GN": 1, "JAN": 1,
        "FB": 2, "FE": 2, "FEB": 2,
        "MR": 3, "MZ": 3, "MAR": 3,
        "AP": 4, "AV": 4, "APR": 4,
        "MG": 5, "MA": 5, "MAY": 5,
        "GI": 6, "JU": 6, "JUN": 6,
        "LG": 7, "JL": 7, "JUL": 7,
        "AG": 8, "AU": 8, "AUG": 8,
        "ST": 9, "SE": 9, "SET": 9, "SEP": 9,
        "OT": 10, "OC": 10, "OTT": 10, "OCT": 10,
        "NV": 11, "NO": 11, "NOV": 11,
        "DC": 12, "DI": 12, "DEC": 12,
    }
    m = re.search(r'(\d{1,2})\s*([A-Z]{2,3})\s*(20\d{2}|\d{2})(?!\d)', txt)
    if m:
        day = int(m.group(1))
        month = month_map.get(m.group(2)[:3], month_map.get(m.group(2)[:2]))
        year = int(m.group(3))
        if year < 100:
            year += 2000 if year < 80 else 1900
        if month:
            try:
                return pd.Timestamp(year=year, month=month, day=day)
            except Exception:
                pass
    m = re.search(r'(20\d{2}|\d{2})', txt)
    if m:
        year = int(m.group(1))
        if year < 100:
            year += 2000 if year < 80 else 1900
        try:
            return pd.Timestamp(year=year, month=12, day=31)
        except Exception:
            return pd.NaT
    return pd.NaT


def extract_gov_maturity_year(name: Any) -> int | None:
    dt = extract_gov_maturity_date(name)
    if pd.isna(dt):
        return np.nan
    return int(pd.Timestamp(dt).year)


def build_gov_dashboard_data(da_frame: pd.DataFrame, data: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    if da_frame is None or da_frame.empty:
        return pd.DataFrame(), {}
    gov = da_frame[da_frame["Tipo"].apply(macro_cat) == "GOV"].copy()
    if gov.empty:
        return pd.DataFrame(), {}
    total_ptf = float(pd.to_numeric(da_frame["Controvalore"], errors="coerce").fillna(0).sum())
    gov["Peso comparto %"] = pd.to_numeric(gov["Controvalore"], errors="coerce").fillna(0) / max(float(pd.to_numeric(gov["Controvalore"], errors="coerce").fillna(0).sum()), 1e-9)
    info_by_tk = {s.get("ticker"): s for s in data.get("strumenti", [])}
    gov["ISIN"] = gov["Ticker"].map(lambda tk: info_by_tk.get(tk, {}).get("isin", ""))
    gov["Data scadenza"] = gov["Strumento"].map(extract_gov_maturity_date)
    gov["Anno scadenza"] = gov["Data scadenza"].map(lambda x: pd.Timestamp(x).year if pd.notna(x) else np.nan)
    weighted_cur = np.average(gov["Prezzo"], weights=np.maximum(pd.to_numeric(gov["Quote"], errors="coerce").fillna(0.0), 1e-9)) if len(gov) else np.nan
    weighted_pmc = np.average(gov["PMC"], weights=np.maximum(pd.to_numeric(gov["Quote"], errors="coerce").fillna(0.0), 1e-9)) if len(gov) else np.nan
    maturity_valid = pd.to_numeric(gov["Anno scadenza"], errors="coerce").dropna()
    summary = {
        "count": int(len(gov)),
        "value": float(pd.to_numeric(gov["Controvalore"], errors="coerce").fillna(0).sum()),
        "weight": float(pd.to_numeric(gov["Controvalore"], errors="coerce").fillna(0).sum()) / total_ptf if total_ptf > 0 else 0.0,
        "pl": float(pd.to_numeric(gov["P/L €"], errors="coerce").fillna(0).sum()),
        "avg_price": float(weighted_cur) if np.isfinite(weighted_cur) else np.nan,
        "avg_pmc": float(weighted_pmc) if np.isfinite(weighted_pmc) else np.nan,
        "avg_maturity_year": float(maturity_valid.mean()) if not maturity_valid.empty else np.nan,
    }
    return gov, summary


def build_category_dashboard_data(da_frame: pd.DataFrame, category: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    empty_columns = ["Ticker", "Strumento", "Tipo", "Categoria", "Quote", "Prezzo", "PMC", "Controvalore", "Costo", "P/L €", "P/L %", "Peso comparto %"]
    if da_frame is None or da_frame.empty:
        return pd.DataFrame(columns=empty_columns), {}
    df = da_frame[da_frame["Tipo"].apply(macro_cat) == category].copy()
    if df.empty:
        return pd.DataFrame(columns=empty_columns), {}
    total_ptf = float(pd.to_numeric(da_frame["Controvalore"], errors="coerce").fillna(0).sum())
    total_cat = float(pd.to_numeric(df["Controvalore"], errors="coerce").fillna(0).sum())
    df["Peso comparto %"] = pd.to_numeric(df["Controvalore"], errors="coerce").fillna(0) / max(total_cat, 1e-9)
    weighted_cur = np.average(df["Prezzo"], weights=np.maximum(pd.to_numeric(df["Quote"], errors="coerce").fillna(0.0), 1e-9)) if len(df) else np.nan
    weighted_pmc = np.average(df["PMC"], weights=np.maximum(pd.to_numeric(df["Quote"], errors="coerce").fillna(0.0), 1e-9)) if len(df) else np.nan
    summary = {
        "count": int(len(df)),
        "value": total_cat,
        "weight": total_cat / total_ptf if total_ptf > 0 else 0.0,
        "pl": float(pd.to_numeric(df["P/L €"], errors="coerce").fillna(0).sum()),
        "avg_price": float(weighted_cur) if np.isfinite(weighted_cur) else np.nan,
        "avg_pmc": float(weighted_pmc) if np.isfinite(weighted_pmc) else np.nan,
    }
    return df, summary


def build_tutto_portfolio_dashboard_data(da_frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Aggrega dati di tutti gli strumenti (GOV + ETF + FND) per la vista complessiva."""
    if da_frame is None or da_frame.empty:
        return pd.DataFrame(), {}
    df = da_frame.copy()
    total_ptf = float(pd.to_numeric(df["Controvalore"], errors="coerce").fillna(0).sum())
    df["Peso comparto %"] = pd.to_numeric(df["Controvalore"], errors="coerce").fillna(0) / max(total_ptf, 1e-9)
    weighted_cur = np.average(df["Prezzo"], weights=np.maximum(pd.to_numeric(df["Quote"], errors="coerce").fillna(0.0), 1e-9)) if len(df) else np.nan
    weighted_pmc = np.average(df["PMC"], weights=np.maximum(pd.to_numeric(df["Quote"], errors="coerce").fillna(0.0), 1e-9)) if len(df) else np.nan
    summary = {
        "count": int(len(df)),
        "value": total_ptf,
        "weight": 1.0,
        "pl": float(pd.to_numeric(df["P/L €"], errors="coerce").fillna(0).sum()),
        "avg_price": float(weighted_cur) if np.isfinite(weighted_cur) else np.nan,
        "avg_pmc": float(weighted_pmc) if np.isfinite(weighted_pmc) else np.nan,
    }
    return df, summary


# ══════════════════════════════════════════════════════════════════════════════
# Summary payload
# ══════════════════════════════════════════════════════════════════════════════

def _build_summary_return_curve(dfh: pd.DataFrame | None) -> pd.DataFrame:
    """
    Costruisce una curva NAV/TWR proxy robusta ai flussi esterni.

    Usa solo le colonne già disponibili nello storico portafoglio:
    - Valore = patrimonio valorizzato alla data;
    - Capitale = capitale netto esterno cumulato.

    Il rendimento giornaliero viene stimato come:
        r_t = (Valore_t - Flusso_esterno_t) / Valore_{t-1} - 1
    dove Flusso_esterno_t = Capitale_t - Capitale_{t-1}.

    Non è un TWR certificato GIPS al singolo cash-flow intraday, ma evita il
    principale errore precedente: normalizzare il solo valore di portafoglio o
    usare (Valore - Capitale) / Capitale, che risente meccanicamente di PAC,
    versamenti e prelievi.
    """
    if dfh is None or dfh.empty:
        return pd.DataFrame(columns=["date_dt", "indice", "ret"])
    needed = {"Data", "Valore", "Capitale"}
    if not needed.issubset(set(dfh.columns)):
        return pd.DataFrame(columns=["date_dt", "indice", "ret"])

    curve = pd.DataFrame({
        "date_dt": pd.to_datetime(dfh["Data"], errors="coerce"),
        "value": pd.to_numeric(dfh["Valore"], errors="coerce"),
        "capital": pd.to_numeric(dfh["Capitale"], errors="coerce"),
    }).dropna(subset=["date_dt", "value"]).sort_values("date_dt").reset_index(drop=True)
    if len(curve) < 2:
        return pd.DataFrame(columns=["date_dt", "indice", "ret"])

    curve["capital"] = curve["capital"].ffill().fillna(0.0)
    curve["external_flow"] = curve["capital"].diff().fillna(0.0)
    curve["prev_value"] = curve["value"].shift(1)
    curve["ret"] = np.where(
        curve["prev_value"].abs() > 1e-9,
        (curve["value"] - curve["external_flow"]) / curve["prev_value"] - 1.0,
        np.nan,
    )
    curve.loc[curve.index[0], "ret"] = 0.0
    curve["ret"] = pd.to_numeric(curve["ret"], errors="coerce").replace([np.inf, -np.inf], np.nan)
    curve["ret"] = curve["ret"].fillna(0.0).clip(lower=-0.95, upper=5.0)
    curve["indice"] = 100.0 * (1.0 + curve["ret"]).cumprod()
    return curve[["date_dt", "indice", "ret", "value", "capital", "external_flow"]]


def _period_returns_from_curve(curve: pd.DataFrame, freq: str) -> list[dict[str, Any]]:
    """Rendimenti composti per mese o trimestre dalla curva NAV/TWR proxy."""
    if curve is None or curve.empty or "ret" not in curve.columns:
        return []
    work = curve.dropna(subset=["date_dt", "ret"]).copy()
    if work.empty:
        return []
    work["year"] = work["date_dt"].dt.year
    if freq == "Q":
        work["quarter"] = work["date_dt"].dt.quarter
        keys = ["year", "quarter"]
    else:
        work["month"] = work["date_dt"].dt.month
        keys = ["year", "month"]
    rows: list[dict[str, Any]] = []
    for group_key, grp in work.groupby(keys):
        vals = pd.to_numeric(grp["ret"], errors="coerce").dropna()
        if vals.empty:
            continue
        ret = float((1.0 + vals).prod() - 1.0)
        if freq == "Q":
            yr, quarter = group_key
            rows.append({"year": int(yr), "quarter": int(quarter), "ptf": ret})
        else:
            yr, month = group_key
            rows.append({"year": int(yr), "month": int(month), "ptf": ret})
    return rows


def _build_summary_value_curve_fallback(dfh: pd.DataFrame | None) -> pd.DataFrame:
    """
    Fallback conservativo per non lasciare la Summary senza grafici se la curva
    NAV/TWR non è costruibile per colonne storiche mancanti o dati anomali.

    Usa la vecchia base visiva: Valore normalizzato a 100. Non viene usata per
    sostituire la metrica TWR quando la curva flow-adjusted è disponibile.
    """
    if dfh is None or dfh.empty or "Data" not in dfh.columns or "Valore" not in dfh.columns:
        return pd.DataFrame(columns=["date_dt", "indice", "ret"])
    work = pd.DataFrame({
        "date_dt": pd.to_datetime(dfh["Data"], errors="coerce"),
        "value": pd.to_numeric(dfh["Valore"], errors="coerce"),
    }).dropna(subset=["date_dt", "value"]).sort_values("date_dt").reset_index(drop=True)
    work = work[work["value"] > 0]
    if len(work) < 2:
        return pd.DataFrame(columns=["date_dt", "indice", "ret"])
    work["indice"] = 100.0 * work["value"] / float(work["value"].iloc[0])
    work["ret"] = work["indice"].pct_change().fillna(0.0)
    return work[["date_dt", "indice", "ret", "value"]]


def build_portfolio_summary_payload(
    data: dict[str, Any],
    da_frame: pd.DataFrame,
    settings: dict[str, Any] | None,
    last_quotes_update: Any,
    proventi: list[dict[str, Any]] | None = None,
    dfh: pd.DataFrame | None = None,
    portfolio_df: pd.DataFrame | None = None,
    liquidita: float | None = None,
) -> dict[str, Any]:
    da_frame = da_frame.copy() if da_frame is not None else pd.DataFrame()
    proventi = proventi or []
    settings = settings or default_settings()
    portfolio_profile = settings.get("portfolio_profile", {}) if isinstance(settings, dict) else {}
    calculations_settings = settings.get("calculations_metrics", {}) if isinstance(settings, dict) else {}
    benchmark_config = get_effective_portfolio_benchmark_config(settings)
    effective_benchmark_label = str(benchmark_config.get("label") or "Blend automatico")
    portfolio_id = str(
        portfolio_profile.get("portfolio_id")
        or settings.get("portfolio_id")
        or data.get("portfolio_id", "main")
    )
    portfolio_name = str(portfolio_profile.get("portfolio_name") or "Portafoglio Principale")
    portfolio_description = str(portfolio_profile.get("description") or "")
    base_currency = str(portfolio_profile.get("base_currency") or "EUR")
    reporting_currency = str(portfolio_profile.get("reporting_currency") or base_currency)
    include_proventi = bool(calculations_settings.get("include_proventi_in_total_return", settings.get("include_proventi_in_total_return", True)))
    rolling_window_days = int(calculations_settings.get("rolling_window_days", 90))
    inflation_rate = float(calculations_settings.get("inflation_rate", 0.0) or 0.0)
    performance_fee_rate = float(calculations_settings.get("performance_fee_rate", 0.0) or 0.0)
    _state_all = None
    _df_all = portfolio_df.copy() if portfolio_df is not None else pd.DataFrame()
    if _df_all.empty:
        _state_all = compute_portfolio_state(data, include_closed=True)
        _df_all = _state_all.get("df", pd.DataFrame())
    if da_frame.empty and not _df_all.empty:
        da_frame = _df_all[_df_all["Quote"] > 0.0001].copy()
    if liquidita is None:
        liquidita = float((_state_all or compute_portfolio_state(data, include_closed=True)).get("liquidita", 0.0))
    capital_flows = calcola_flussi_capitale(get_registro_eventi(data))
    kpi = calcola_kpi_principali(
        _df_all,
        float(liquidita or 0.0),
        capitale_investito=capital_flows["cap_investito"],
    )
    tv = float(kpi["tv"])
    tc = float(kpi["tc"])
    pl = float(kpi["pl_totale"])
    pl_pct = float(kpi["pl_totale_pct"])
    holdings_count = int(len(da_frame)) if da_frame is not None else 0
    visible_categories = _resolve_finance_category_codes(settings)
    macro_alloc = {cat: 0.0 for cat in visible_categories}
    macro_values = {cat: 0.0 for cat in visible_categories}
    full_holdings = []
    if not da_frame.empty and tv > 0:
        macro_alloc, macro_values = _build_category_value_maps(da_frame, tv, visible_categories)
        tmp = da_frame.copy()
        tmp["Categoria"] = tmp["Tipo"].apply(macro_cat)
        full_holdings.extend(tmp.sort_values("Controvalore", ascending=False).apply(
            lambda r: {
                "ticker": r.get("Ticker"),
                "strumento": r.get("Strumento"),
                "categoria": macro_cat(r.get("Tipo", "")),
                "tipo": r.get("Tipo"),
                "peso": float(r.get("Controvalore", 0) / tv) if tv > 0 else 0.0,
                "controvalore": float(r.get("Controvalore", 0) or 0),
                "costo": float(r.get("Costo", 0) or 0),
                "pl_eur": float(r.get("P/L €", 0) or 0),
                "pl_pct": float(r.get("P/L %", 0) or 0),
                "quote": float(r.get("Quote", 0) or 0),
                "prezzo": float(r.get("Prezzo", 0) or 0),
            }, axis=1
        ).tolist())
    top_holdings = full_holdings[:15]
    xirr = twr_simple = cagr = vol_ann = max_dd = benchmark_return = excess_vs_benchmark = None
    sortino_ratio = calmar_ratio = information_ratio = tracking_error_ann = None
    quarterly_returns = []
    monthly_returns = []
    dfh = dfh if dfh is not None else build_portfolio_history_df(data)
    return_curve = pd.DataFrame()
    curve_for_charts = pd.DataFrame()
    benchmark_series = None
    try:
        flows, dates = build_xirr_flows(data, da_frame, proventi, tickers=None)
        xirr = compute_xirr(flows, dates)
    except Exception as e:
        logger.warning("XIRR computation failed: %s", e)
    try:
        return_curve = _build_summary_return_curve(dfh)
        curve_for_charts = return_curve if not return_curve.empty and len(return_curve) >= 2 else _build_summary_value_curve_fallback(dfh)
        benchmark_start_date = None
        if not curve_for_charts.empty and len(curve_for_charts) >= 2:
            benchmark_start_date = curve_for_charts["date_dt"].iloc[0]
        if benchmark_start_date is not None:
            benchmark_series = build_portfolio_benchmark_series(
                data,
                effective_benchmark_label,
                da_frame,
                min_date=benchmark_start_date,
                settings=settings,
            )
        if not return_curve.empty and len(return_curve) >= 2:
            idx_series = pd.to_numeric(return_curve["indice"], errors="coerce").dropna()
            ret_series = pd.to_numeric(return_curve["ret"], errors="coerce").dropna()

            if len(idx_series) >= 2 and idx_series.iloc[0] > 0:
                twr_simple = float(idx_series.iloc[-1] / idx_series.iloc[0] - 1.0)
            else:
                twr_simple = None

            elapsed_days = max(int((return_curve["date_dt"].iloc[-1] - return_curve["date_dt"].iloc[0]).days), 1)
            if twr_simple is not None and twr_simple > -1.0:
                cagr = float((1.0 + twr_simple) ** (365.25 / elapsed_days) - 1.0)
            else:
                cagr = None

            if len(ret_series) >= 3:
                vol_ann = float(ret_series.iloc[1:].std(ddof=1) * np.sqrt(252))
            else:
                vol_ann = None

            if len(idx_series) >= 2:
                running_max = idx_series.cummax()
                drawdowns = idx_series / running_max - 1.0
                max_dd = float(drawdowns.min())
            else:
                max_dd = None

            if benchmark_series is not None and not benchmark_series.empty and len(benchmark_series) >= 2 and benchmark_series.iloc[0] > 0:
                benchmark_return = float(benchmark_series.iloc[-1] / benchmark_series.iloc[0] - 1.0)
                # Protezione anti-benchmark palesemente spurio/incompleto.
                if benchmark_return > 0.50:
                    benchmark_return = None
                    benchmark_series = None
                elif twr_simple is not None:
                    excess_vs_benchmark = float(twr_simple - benchmark_return)

            try:
                _rets = ret_series.iloc[1:].dropna()
                if len(_rets) >= 4:
                    _neg = _rets[_rets < 0]
                    if len(_neg) >= 2:
                        _ds = float(np.sqrt((_neg ** 2).mean()) * np.sqrt(252))
                        sortino_ratio = float(cagr / _ds) if cagr is not None and _ds > 1e-9 else None
                    if cagr is not None and max_dd is not None and abs(max_dd) > 1e-9:
                        calmar_ratio = float(cagr / abs(max_dd))
                    if benchmark_series is not None and not benchmark_series.empty:
                        _bv = benchmark_series.reindex(pd.to_datetime(return_curve["date_dt"])).ffill().bfill()
                        _br = _bv.pct_change().dropna()
                        _min_len = min(len(_rets), len(_br))
                        if _min_len >= 4:
                            _ex = _rets.iloc[-_min_len:].values - _br.iloc[-_min_len:].values
                            _te = float(np.std(_ex, ddof=1) * np.sqrt(252))
                            tracking_error_ann = _te if _te > 1e-9 else None
                            if tracking_error_ann:
                                information_ratio = float(_ex.mean() * 252 / _te)
            except Exception as e:
                logger.warning("advanced stats failed: %s", e)
    except Exception as e:
        logger.warning("advanced stats failed: %s", e)

    summary_history = []
    benchmark_history = []
    category_history = []
    try:
        if not curve_for_charts.empty and len(curve_for_charts) >= 2:
            hist_payload = {
                "data": curve_for_charts["date_dt"].dt.strftime("%d/%m/%Y"),
                "indice": pd.to_numeric(curve_for_charts["indice"], errors="coerce").round(4),
            }
            if "value" in curve_for_charts.columns:
                hist_payload["value"] = pd.to_numeric(curve_for_charts["value"], errors="coerce").round(4)
            if "external_flow" in curve_for_charts.columns:
                hist_payload["external_flow"] = pd.to_numeric(curve_for_charts["external_flow"], errors="coerce").round(4)
            hist_df = pd.DataFrame(hist_payload).dropna(subset=["data", "indice"])
            summary_history = hist_df.to_dict("records")
            if benchmark_series is not None and not benchmark_series.empty and benchmark_series.iloc[0] > 0:
                bench_norm = (benchmark_series / benchmark_series.iloc[0]) * 100.0
                bench_df = pd.DataFrame({
                    "data": pd.to_datetime(bench_norm.index).strftime("%d/%m/%Y"),
                    "indice": bench_norm.round(4),
                })
                benchmark_history = bench_df.to_dict("records")
            # I rendimenti periodici usano la curva flow-adjusted se disponibile;
            # in fallback mantengono comunque viva la tabella invece di svuotare la Summary.
            quarterly_returns = _period_returns_from_curve(curve_for_charts, "Q")
            monthly_returns = _period_returns_from_curve(curve_for_charts, "M")
        try:
            dh_hist = build_hist_df(data)
            cat_idx = build_category_return_index(dh_hist, data, positions=calc_positions(data))
            if cat_idx is not None and not cat_idx.empty:
                category_history = _build_category_history_records(cat_idx, visible_categories)
        except Exception as e:
            logger.warning("category history failed: %s", e)
    except Exception as e:
        logger.warning("benchmark/period history failed: %s", e)
    _prov_netto = 0.0
    _prov_lordo = 0.0
    for _p in proventi:
        _prov_netto += float(_p.get("importo_netto", 0) or 0)
        _prov_lordo += float(_p.get("importo_lordo", 0) or 0)
    category_breakdown = [
        {
            "categoria": cat,
            "peso": float(macro_alloc.get(cat, 0.0)),
            "controvalore": float(macro_values.get(cat, 0.0)),
        }
        for cat in visible_categories
    ]
    return {
        "standard": "Internal Portfolio Summary inspired by GIPS presentation logic and openfunds-style data structuring",
        "compliance_note": "Documento interno di sintesi ispirato a logiche GIPS/openfunds. Non costituisce una rendicontazione GIPS certificata né un file openfunds ufficiale.",
        "portfolio_id": portfolio_id,
        "portfolio_name": portfolio_name,
        "portfolio_description": portfolio_description,
        "valuation_timestamp": last_quotes_update,
        "base_currency": base_currency,
        "reporting_currency": reporting_currency,
        "target_profile": settings.get("target_profile_default", "Prudente"),
        "portfolio_benchmark": effective_benchmark_label,
        "portfolio_benchmark_is_custom": bool(benchmark_config.get("is_custom", False)),
        "portfolio_benchmark_components": benchmark_config.get("components", []),
        "include_proventi_in_total_return": include_proventi,
        "rolling_window_days": rolling_window_days,
        "inflation_rate": inflation_rate,
        "performance_fee_rate": performance_fee_rate,
        "total_market_value": tv,
        "total_cost": tc,
        "total_pl": pl,
        "total_pl_pct": pl_pct,
        "xirr": xirr,
        "twr": twr_simple,
        "cagr": cagr,
        "volatility_ann": vol_ann,
        "max_drawdown": max_dd,
        "benchmark_return": benchmark_return,
        "excess_vs_benchmark": excess_vs_benchmark,
        "net_proventi": _prov_netto,
        "gross_proventi": _prov_lordo,
        "holdings_count": holdings_count,
        "macro_allocation": macro_alloc,
        "category_breakdown": category_breakdown,
        "top_holdings": top_holdings,
        "full_holdings": full_holdings,
        "summary_history": summary_history,
        "benchmark_history": benchmark_history,
        "category_history": category_history,
        "sortino": sortino_ratio,
        "calmar": calmar_ratio,
        "information_ratio": information_ratio,
        "tracking_error": tracking_error_ann,
        "quarterly_returns": quarterly_returns,
        "monthly_returns": monthly_returns,
        "methodology": {
            "valuation_rule": "Controvalore = quantità x ultimo prezzo disponibile letto o mantenuto in cache.",
            "money_weighted_return": "XIRR calcolato sui flussi irregolari di acquisto, vendita, proventi e controvalore finale.",
            "time_weighted_proxy": "TWR proxy calcolato su curva NAV flow-adjusted: i flussi esterni stimati dalla variazione del capitale netto vengono neutralizzati prima di calcolare rendimento, drawdown, volatilità e rendimenti periodici.",
            "benchmark_method": (
                "Benchmark personalizzato definito da componenti e pesi configurati nelle impostazioni, costruito come serie normalizzata a 100 dalla prima data utile."
                if bool(benchmark_config.get("is_custom", False))
                else "Benchmark di portafoglio definito da impostazioni e costruito come serie normalizzata a 100 dalla prima data utile."
            ),
            "include_proventi": "Sì" if include_proventi else "No",
            "rolling_window_days": rolling_window_days,
            "inflation_rate": inflation_rate,
            "performance_fee_rate": performance_fee_rate,
        }
    }


def build_scenario_impact(da_frame: pd.DataFrame, scenarios: list[dict[str, Any]]) -> pd.DataFrame:
    """
    Calcola l'impatto di scenari di mercato sulla portafoglio.

    Args:
        da_frame: DataFrame con posizioni (colonne: Categoria/Tipo, Controvalore)
        scenarios: list di dict {"nome": str, "GOV": shock%, "ETF": shock%, "FND": shock%}

    Returns:
        pd.DataFrame con colonne: Scenario, Impatto P/L €, Impatto P/L %
    """
    if da_frame is None or da_frame.empty:
        return pd.DataFrame()

    categories = list(ACTIVE_CATEGORY_CODES)
    cat_col = "Categoria" if "Categoria" in da_frame.columns else None
    rows = []
    total_value = da_frame["Controvalore"].sum()

    if cat_col:
        da_cat = da_frame["Categoria"]
    else:
        da_cat = da_frame["Tipo"].apply(macro_cat)

    controvalore = da_frame["Controvalore"].astype(float)

    for sc in scenarios:
        shocks = da_cat.map({k: sc.get(k, 0.0) for k in categories})
        delta_tot = float((controvalore * shocks).sum())
        delta_pct = delta_tot / total_value if total_value > 0 else 0
        rows.append({
            "Scenario": sc["nome"],
            "Impatto P/L €": delta_tot,
            "Impatto P/L %": delta_pct,
        })
    return pd.DataFrame(rows) if rows else pd.DataFrame()


DEFAULT_SCENARIOS = [
    {"nome": "Rialzo tassi +1%", "GOV": -0.08, "ETF": 0.02, "FND": 0.01},
    {"nome": "Ribasso azionario", "GOV": 0.02, "ETF": -0.15, "FND": -0.12},
    {"nome": "Ripresa mercati", "GOV": 0.01, "ETF": 0.12, "FND": 0.10},
    {"nome": "Crisi finanziaria", "GOV": -0.05, "ETF": -0.25, "FND": -0.20},
    {"nome": "Scenario personaliz.", "GOV": 0.0, "ETF": 0.0, "FND": 0.0},
]


def compute_portfolio_alerts(
    da_frame: pd.DataFrame,
    dfh: pd.DataFrame,
    cat_flow_returns: pd.DataFrame | None = None,
) -> list[dict[str, str]]:
    """
    Calcola alert automatici sulla salute del portafoglio.

    Args:
        da_frame: DataFrame posizioni attuali
        dfh: DataFrame storico con colonna 'Valore'
        cat_flow_returns: DataFrame optional con ritorni per categoria

    Returns:
        list di dict {"tipo": str, "messaggio": str, "severity": "warning"|"error"|"info"}
    """
    alerts = []

    # Alert 1: Drawdown corrente > 10%
    if dfh is not None and not dfh.empty and "Valore" in dfh.columns:
        val_series = pd.Series(dfh["Valore"]).dropna()
        if len(val_series) > 1:
            peak = val_series.max()
            current = val_series.iloc[-1]
            if peak > 0:
                dd = (current - peak) / peak
                if dd < -0.10:
                    alerts.append({
                        "tipo": "Drawdown",
                        "severity": "error",
                        "messaggio": f"Portafoglio in drawdown del {dd:.1%} dal massimo storico"
                    })

    # Alert 2: Concentrazione eccessiva > 35%
    if da_frame is not None and not da_frame.empty:
        total = da_frame["Controvalore"].sum()
        if total > 0:
            weights = da_frame["Controvalore"] / total
            concentrated = weights[weights > 0.35]
            for ticker, pct in concentrated.items():
                row = da_frame.iloc[ticker] if isinstance(ticker, int) else da_frame.loc[ticker]
                alerts.append({
                    "tipo": "Concentrazione",
                    "severity": "warning",
                    "messaggio": f"{row.get('Ticker', 'Strumento')} pesa il {pct:.1%} del portafoglio"
                })

    # Alert 3: Correlazione alta GOV-ETF > 0.75
    if cat_flow_returns is not None and not cat_flow_returns.empty:
        if "GOV" in cat_flow_returns.columns and "ETF" in cat_flow_returns.columns:
            corr = float(cat_flow_returns["GOV"].corr(cat_flow_returns["ETF"]))
            if abs(corr) > 0.75:
                alerts.append({
                    "tipo": "Correlazione",
                    "severity": "warning",
                    "messaggio": f"Alta correlazione GOV-ETF ({corr:.2f}): diversificazione ridotta"
                })

    # Alert 4: P/L negativo per categoria < -500€
    if da_frame is not None and not da_frame.empty:
        cat_col = "Categoria" if "Categoria" in da_frame.columns else None
        if cat_col:
            group = da_frame.groupby("Categoria")["P/L €"].sum()
        else:
            group = da_frame.groupby(da_frame["Tipo"].apply(macro_cat))["P/L €"].sum()
        for cat, pl in group.items():
            if pl < -500:
                alerts.append({
                    "tipo": f"P/L {cat}",
                    "severity": "info",
                    "messaggio": f"La categoria {cat} ha un P/L negativo di {pl:,.0f}€"
                })

    return alerts


def build_rebalancing_suggestions(
    da_frame: pd.DataFrame,
    target_weights: dict[str, float] | None = None,
    settings: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """
    Suggerimenti di ribilanciamento per categoria.

    Args:
        da_frame: DataFrame con posizioni aperte (colonne: Ticker, Controvalore, Tipo, etc.)
        target_weights: dict {"GOV": 0.33, "ETF": 0.34, "FND": 0.33}. Se None, usa equal weight.

    Returns:
        pd.DataFrame con colonne: Categoria, Peso Attuale %, Peso Target %, Delta %, Importo €, Azione
    """
    if da_frame is None or da_frame.empty:
        return pd.DataFrame()
    total = float(da_frame["Controvalore"].sum())
    if total < 1e-9:
        return pd.DataFrame()

    cat_col = "Categoria" if "Categoria" in da_frame.columns else None
    if cat_col:
        by_cat = da_frame.groupby("Categoria")["Controvalore"].sum()
    else:
        by_cat = da_frame.groupby(da_frame["Tipo"].apply(macro_cat))["Controvalore"].sum()

    cats = _resolve_finance_category_codes(settings)
    by_cat = by_cat.reindex(cats, fill_value=0.0)

    if target_weights is None:
        target_weights = {c: 1 / len(cats) for c in cats} if cats else {}

    rows = []
    for cat in cats:
        attuale = float(by_cat.get(cat, 0.0))
        pct_att = attuale / total if total > 0 else 0.0
        pct_target = target_weights.get(cat, (1 / len(cats)) if cats else 0.0)
        delta_pct = pct_target - pct_att
        delta_eur = delta_pct * total
        azione = "Acquista" if delta_eur > 50 else ("Vendi" if delta_eur < -50 else "OK")
        rows.append({
            "Categoria": cat,
            "Peso Attuale %": pct_att,
            "Peso Target %": pct_target,
            "Delta %": delta_pct,
            "Importo €": delta_eur,
            "Azione": azione,
        })
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def build_bucket_rebalancing_suggestions(
    da_frame: pd.DataFrame,
    bucket_of_ticker: dict[str, str],
    target_weights: dict[str, float],
) -> pd.DataFrame:
    """
    Suggerimenti di ribilanciamento per bucket strategico (Core/Difensivo/Satellite),
    stesso schema di `build_rebalancing_suggestions` ma raggruppato per ruolo invece
    che per involucro/categoria.

    Args:
        da_frame: DataFrame posizioni aperte (colonne Ticker, Controvalore).
        bucket_of_ticker: mappa ticker -> "Core"/"Difensivo"/"Satellite".
        target_weights: dict {"Core": 0.6, "Difensivo": 0.25, "Satellite": 0.15}.

    Returns:
        pd.DataFrame con colonne: Bucket, Peso Attuale %, Peso Target %, Delta %, Importo €, Azione
    """
    cats = ["Core", "Difensivo", "Satellite"]
    if da_frame is None or da_frame.empty:
        return pd.DataFrame()
    total = float(pd.to_numeric(da_frame["Controvalore"], errors="coerce").fillna(0.0).sum())
    if total < 1e-9:
        return pd.DataFrame()

    work = da_frame.copy()
    work["Bucket"] = work["Ticker"].astype(str).map(lambda t: bucket_of_ticker.get(t, "Satellite"))
    by_bucket = work.groupby("Bucket")["Controvalore"].sum().reindex(cats, fill_value=0.0)

    rows = []
    for cat in cats:
        attuale = float(by_bucket.get(cat, 0.0))
        pct_att = attuale / total if total > 0 else 0.0
        pct_target = float(target_weights.get(cat, 0.0))
        delta_pct = pct_target - pct_att
        delta_eur = round(delta_pct * total, 2)
        azione = "Acquista" if delta_eur >= 50 else ("Vendi" if delta_eur <= -50 else "OK")
        rows.append({
            "Bucket": cat,
            "Peso Attuale %": pct_att,
            "Peso Target %": pct_target,
            "Delta %": delta_pct,
            "Importo €": delta_eur,
            "Azione": azione,
        })
    return pd.DataFrame(rows)

